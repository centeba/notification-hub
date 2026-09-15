"""Vendored platform utilities.

These modules were originally provided by the SentinelBuild internal SDK
(``sentinelbuild_sdk``). They are small, self-contained helpers — SSRF egress
guarding, HMAC webhook signing/verification, a per-IP rate-limit middleware, and
an optional authorization hook — vendored here verbatim so notification-hub is a
dependency-clean standalone service. Keep them in sync with upstream if you pull
fixes from the platform SDK.
"""
