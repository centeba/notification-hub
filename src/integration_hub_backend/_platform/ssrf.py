"""Canonical SSRF guard for outbound HTTP from platform services.

Any feature that fetches an author- or tenant-supplied URL (workflow
``http_request`` / ``web_scraper`` nodes, outbound webhooks) can be steered at
cloud metadata (``169.254.169.254``), ``localhost``, or internal services — and
can replay an injected credential to an attacker-chosen internal host. This is
the single implementation every service should use, replacing the previously
duplicated per-service guards.

Two layers:

1. :func:`validate_url` — reject non-http(s) schemes and any host that resolves
   to a private / loopback / link-local / CGNAT / metadata address. Sufficient
   on its own for a pre-flight check.

2. :func:`guarded_send` — **connect-time IP pinning** that closes the
   TOCTOU / DNS-rebind window the pre-flight check alone leaves open. It
   resolves the host once, validates *every* resolved address, then connects to
   the exact validated IP while preserving the original ``Host`` header and TLS
   SNI (so certificate verification still checks the real hostname). Redirects
   are followed manually and each hop is re-validated + re-pinned, and a
   cross-host redirect drops the ``Authorization`` header so an injected
   credential can't be bounced to another origin.
"""

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # RFC 6598 carrier-grade NAT

# ``ipaddress.ip_address`` returns one of these concrete types; the base
# ``_BaseAddress`` intentionally does not expose the ``is_*`` classifiers.
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class SsrfError(Exception):
    """Raised when a URL is rejected by the SSRF guard."""


def _ip_blocked(ip: IPAddress) -> bool:
    if ip.version == 4 and ip in _CGNAT:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # covers 169.254.0.0/16 incl. the metadata IP
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str, port: int) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfError(f"cannot resolve host {host!r}") from exc
    out: list[IPAddress] = []
    for info in infos:
        addr = str(info[4][0]).split("%")[0]  # strip any IPv6 zone id
        try:
            out.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return out


def _host_addresses(url: str) -> tuple[str, int, str, list[IPAddress]]:
    """Parse+resolve ``url``; return (scheme, port, host, resolved_ips).

    Raises :class:`SsrfError` for a bad scheme, missing host, or a host that
    doesn't resolve. Does *not* apply the block policy — callers do.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfError(f"scheme {parsed.scheme!r} not allowed (http/https only)")
    host = parsed.hostname
    if not host:
        raise SsrfError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        ips: list[IPAddress] = [ipaddress.ip_address(host)]
    except ValueError:
        ips = _resolve(host, port)
    if not ips:
        raise SsrfError(f"host {host!r} did not resolve")
    return parsed.scheme, port, host, ips


def validate_url(url: str) -> None:
    """Raise :class:`SsrfError` unless ``url`` is a public http(s) endpoint.

    Rejects if **any** resolved address is internal, so a name that round-robins
    between a public and a private IP is blocked.
    """
    _, _, host, ips = _host_addresses(url)
    for ip in ips:
        if _ip_blocked(ip):
            raise SsrfError(f"host {host!r} resolves to blocked address {ip} (internal/metadata)")


def resolve_pinned_ip(url: str) -> str:
    """Validate ``url`` and return the single IP to connect to.

    Every resolved address is checked; if any is internal the whole URL is
    rejected (same policy as :func:`validate_url`). The returned IP is the exact
    address the caller must connect to — resolving again at connect time is what
    would reopen the DNS-rebind window.
    """
    _, _, host, ips = _host_addresses(url)
    for ip in ips:
        if _ip_blocked(ip):
            raise SsrfError(f"host {host!r} resolves to blocked address {ip} (internal/metadata)")
    return str(ips[0])


def _pin_url_to_ip(url: str, ip: str) -> str:
    """Return ``url`` with its host replaced by ``ip`` (IPv6 bracketed)."""
    parsed = urlparse(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = literal if parsed.port is None else f"{literal}:{parsed.port}"
    if parsed.username or parsed.password:
        # Userinfo shouldn't reach here (guarded URLs are author-supplied), but
        # never fold credentials into the pinned netloc if it somehow does.
        raise SsrfError("URL must not contain userinfo")
    return urlunparse(parsed._replace(netloc=netloc))


def build_pinned_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    ip: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Request:
    """Build a request that connects to ``ip`` but keeps the real host for the
    ``Host`` header, TLS SNI, and certificate verification."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    hdrs = dict(headers or {})
    hdrs["Host"] = host if parsed.port is None else f"{host}:{parsed.port}"
    request = client.build_request(method.upper(), _pin_url_to_ip(url, ip), headers=hdrs, **kwargs)
    # httpcore uses this for both the SNI server name and the cert-check
    # hostname, so verification still validates against the real host, not the
    # IP we dialled.
    request.extensions = {**request.extensions, "sni_hostname": host}
    return request


async def guarded_send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_redirects: int = 5,
    strip_auth_cross_host: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    """Send an SSRF-guarded request with connect-time IP pinning.

    ``client`` must be created with ``follow_redirects=False`` (this function
    walks redirects itself so it can re-validate + re-pin each hop). Raises
    :class:`SsrfError` if the target — or any redirect target — is internal.
    """
    hdrs = dict(headers or {})
    current = url
    prev_host = urlparse(url).hostname
    for _ in range(max_redirects + 1):
        ip = resolve_pinned_ip(current)  # validates + pins this hop
        request = build_pinned_request(client, method, current, ip, headers=hdrs, **kwargs)
        resp = await client.send(request)
        if not resp.is_redirect or not resp.headers.get("location"):
            return resp
        next_url = str(resp.next_request.url) if resp.next_request else None
        if not next_url:
            return resp
        next_host = urlparse(next_url).hostname
        if strip_auth_cross_host and next_host != prev_host:
            hdrs.pop("Authorization", None)  # don't leak creds cross-host
        current, prev_host = next_url, next_host
    raise SsrfError(f"too many redirects (> {max_redirects}) from {url}")
