# Standalone image for notification-hub. Build context: the repository root.
# One image serves api / worker / email / sms / webhook / mcp — the process is
# selected by the CMD (see cli.py subcommands).
#
# Digest-pinned. Bump the tag+digest together; a bot (Dependabot/Renovate)
# should keep it fresh.
FROM python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6

WORKDIR /app

# System dependencies. `git` is required to install the smart-llm git dependency
# declared in pyproject; gcc/libpq for building asyncpg/psycopg.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Optionally trust a TLS-inspection root CA (e.g. a dev laptop's AV/proxy that
# re-signs HTTPS). Supplied as a BuildKit secret so the cert is used only during
# the build and never baked into the image. No-op when the secret is absent, so
# CI / clean networks build unchanged.
#   docker buildx build --secret id=extra_ca,src=<root-ca.crt> ...
RUN \
    if [ -s /run/secrets/extra_ca ]; then \
        cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra-ca.crt && \
        update-ca-certificates; \
    fi
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# pip's PEP517 build-isolation subprocess verifies against certifi's bundled CA,
# not the OS trust store, so append the extra CA there before the first install.
RUN pip install --no-cache-dir certifi
RUN \
    if [ -s /run/secrets/extra_ca ]; then \
        cat /run/secrets/extra_ca >> "$(python -c 'import certifi; print(certifi.where())')"; \
    fi

# Install the app. `pip install .` resolves every runtime dependency, including
# smart-llm from its pinned git ref (needs the `git` package installed above).
# Copy only what's needed to build the wheel first, so dependency layers cache.
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir .

# httpx (used by smart_llm for outbound LLM/moderation calls) verifies TLS
# against certifi's bundle at runtime — append the extra CA there too. No-op
# without the secret.
RUN \
    if [ -s /run/secrets/extra_ca ]; then \
        cat /run/secrets/extra_ca >> "$(python -c 'import certifi; print(certifi.where())')"; \
    fi

COPY alembic.ini /app/alembic.ini
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Run as a non-root user (shrinks RCE blast radius).
RUN useradd --system --no-create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Default process; override per service (start-worker / start-email / …).
# $PORT (if set) is read by cli.py's argparse defaults.
CMD ["integration-hub", "start-api"]
