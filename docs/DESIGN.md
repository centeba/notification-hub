# notification-hub — Design

## Overview

notification-hub is a set of cooperating processes built from one Python package
(`integration_hub_backend`) and one image. A control-plane **API** evaluates
events against rules and orchestrates delivery through **Temporal**; dedicated
**channel** processes (email / SMS / webhook) perform the actual sends. State
lives in **Postgres**; **Redis** backs caching, idempotency, and rate limiting.

```
             POST /events/ingest
 client ───────────────────────────▶  API (start-api, :8001)
                                        │  match rules, load prefs/templates
                                        ▼
                                   Temporal workflow  ◀── worker (start-worker)
                                        │  fan out per channel, retry, dedupe
                          ┌─────────────┼──────────────┐
                          ▼             ▼              ▼
                   email (:8002)   sms (:8003)   webhook (:8004)
                          │             │              │
                          ▼             ▼              ▼
                     SMTP/SES      Twilio/SNS    signed HTTP POST
                          └─────────────┴──────────────┘
                                        ▼
                                delivery log (/logs)
```

## Processes

Selected by the `integration-hub` CLI subcommand (see the README table): the
orchestration **API**, the Temporal **worker**, the three **channel** services,
and an **MCP** tool server. One image; the process is chosen by the command, so
they share code, config, and migrations.

## Data model

Tables are SQLAlchemy models under `api/models` plus the smart-llm AI tables.
Alembic migrations (`src/integration_hub_backend/api/alembic`, driven by
repo-root `alembic.ini`) are the source of truth for schema; `alembic upgrade
head` creates everything. Core entities: events, rules (+ conditions), channels,
templates, delivery logs, preferences, company settings, api-keys, webhooks,
integration credentials (connector-tagged, encrypted), and the AI
agent/skill/usage tables.

## Integrations (connectors)

Beyond the notification channels, the hub ships a catalog of **external-service
connectors** (Gmail, Outlook, Stripe, S3, Google Drive/Sheets, Excel, Datadog,
Splunk, Grafana, Elasticsearch, Kibana, Mailchimp, Claude) that workflows and
AI tools can act through. Two surfaces:

- **Catalog** — `GET /integrations` returns descriptor-only entries
  (`key`, `name`, `category`, `description`, `auth`), curated in
  `api/routes/integrations_catalog.py` and kept in sync with the mounted
  `/integrations/<key>` action routers by a drift test. Any authenticated user
  may read it; it exposes no secrets or per-tenant state.
- **Connect / credentials** — connecting stores an encrypted credential tagged
  with its connector `key`. API-key connectors use the JWT-admin
  `POST /credentials/connect` (+ `DELETE /credentials/connect/{id}` to
  disconnect); OAuth connectors (Gmail/Outlook/Drive/Sheets) use the
  `/oauth/<key>/authorize-url` consent flow, whose callback persists the token
  as an `oauth2` credential. `GET /credentials/status` returns per-connector
  connected state for the tenant so the UI can render badges. The machine-to-
  machine `/credentials` surface (API-key-gated, scoped) remains for
  programmatic credential management.

The admin UIs' **Integrations** page renders the catalog grouped by category,
shows connected state, and drives the connect/disconnect flows.

## AI layer (smart-llm)

The AI surface (`/ai-agents`, `/ai-invoke`, `/ai-search`, `/ai-tools`) is built on
the standalone **smart-llm** package: agent loop, deny-by-default tool-policy
gate, PII firewall, key store, usage/budgets, and multi-provider access. Routers
are composed from smart-llm's router factories (`create_agents_router`,
`create_skills_router`, `create_usage_router`, …), so the AI capabilities track
smart-llm rather than being reimplemented here.

## Safety & hardening

- **Signed webhooks** — `_platform.webhooks` signs outbound and verifies inbound
  requests (HMAC-SHA256 over `timestamp.body`, replay-protected via Redis).
- **SSRF egress guard** — `_platform.ssrf` validates every outbound URL and pins
  the resolved IP, refusing private/loopback/link-local/metadata targets.
- **Rate limiting** — `_platform.rate_limit` mounts an optional per-IP limiter
  (no-op unless `RATE_LIMIT_REDIS_URL` is set; degrades to in-process on Redis
  blips).
- **Authorization hook** — `_platform.authz.authz_check` defaults to permissive
  standalone; a host with an authorization service registers a real checker via
  `set_authz_checker`.
- **Field encryption** — secrets/PII columns encrypt with a Fernet key derived
  from (or overriding) `SECRET_KEY`.
- **Tool-policy gate** — AI tool use is deny-by-default (from smart-llm).

## Decoupling from SentinelBuild

This repo was extracted from the SentinelBuild monorepo and made dependency-clean:

| Original coupling | Standalone treatment |
|---|---|
| `smart_llm` (26 files) | **External dependency** — public `smart-llm`, pinned by git ref |
| `sentinelbuild_sdk.ssrf` / `.webhooks` / `.middleware` | **Vendored** into `_platform/` (self-contained) |
| `sentinelbuild_sdk.authz` | **Pluggable hook** — permissive default (`_platform.authz`) |
| `sb_core` (chassis packs) | **Optional** — guarded imports; endpoints degrade to "no packs" |

The only remaining first-party dependency is smart-llm, over its public package.

## Observability

`smart_llm.observability.install_observability` and `smart_llm.logging_config`
provide Prometheus `/metrics`, OpenTelemetry traces, Sentry, and structured JSON
logs — all activated only when their env is set (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`SENTRY_DSN`, `LOG_LEVEL`). Liveness is `/health`; deep readiness (db / redis /
temporal) is `/healthz` via `smart_llm.service_runtime.add_readiness_route`.

## Deployment

`docker build .` yields one image. Run each process as its own service with the
matching `start-*` command (see `railway.*.json` for a five-service split:
api / email / sms / webhook / worker). The API service runs `migrate` on boot via
`docker-entrypoint.sh` (with boot-time DB retry).
