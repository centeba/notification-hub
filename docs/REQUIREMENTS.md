# notification-hub — Requirements

## Purpose

A standalone, multi-tenant **notification service**: applications hand it events,
and it decides which channels to notify, delivers durably, records the outcome,
and honors per-user preferences. An optional agentic AI layer lets tenants define
agents/skills that can compose and route notifications.

## Scope

### In scope

1. **Event ingest** — `POST /events/ingest` accepts a typed event and enqueues
   evaluation.
2. **Routing rules** — CRUD over rules (`/rules`) that match events by type and
   conditions and select channels, priorities, and recipient strategies.
3. **Channels** — email, SMS, and outbound webhooks, each a separately
   deployable delivery process behind a uniform interface (`/channels`).
4. **Templates** — reusable message templates (`/templates`) with variable
   substitution.
5. **Durable delivery** — orchestration via Temporal workflows with retry and
   idempotency; delivery attempts recorded to a queryable log (`/logs`).
6. **Preferences** — per-user channel opt-in (`/preferences/me`) and per-tenant
   company settings (`/company-settings/me`).
7. **AI layer** — agents, skills, tool-policy-gated tool use, usage/budgets, and
   multi-provider LLM access, provided by **smart-llm**.
8. **Security** — HMAC-signed webhooks, SSRF egress guarding on outbound calls,
   optional per-IP rate limiting, field encryption for secrets/PII.
9. **Admin UIs** — Flutter and React front-ends for dashboard, history, rules,
   integrations, and preferences.
10. **Operability** — health/readiness endpoints, structured logs, Prometheus
    metrics, and OpenTelemetry traces (opt-in).
11. **Integration connectors** — a JWT-readable catalog of external-service
    connectors (`GET /integrations`) — Gmail, Outlook, Stripe, S3, Datadog,
    Claude, and more. Tenants connect API-key connectors by storing encrypted
    credentials (`/credentials/connect`) and OAuth connectors via the consent
    flow (`/oauth/*`); per-connector connected state is exposed at
    `/credentials/status`. Managed from the admin UIs' Integrations page.

### Out of scope

- The SentinelBuild **chassis "packs"** plugin system (`sb_core`) — optional;
  the pack endpoints degrade to "no packs" when the chassis is absent.
- Central platform **authorization service** — replaced by a pluggable, permissive
  default hook (`_platform.authz`).
- In-app **push / device** transport beyond the existing device-token surface.
- A bundled frontend host app (the UIs are libraries the host embeds).

## Functional acceptance criteria

- Ingesting an event that matches an active rule produces one delivery attempt
  per selected channel, each recorded in `/logs` with a terminal status.
- A disabled rule (`is_active=false`) produces no deliveries.
- A recipient who has disabled a channel in `/preferences/me` is not delivered to
  on that channel.
- Outbound webhooks carry a valid HMAC signature and timestamp; a receiver can
  verify them; requests to private/loopback/link-local/metadata addresses are
  refused (SSRF guard).
- `GET /integrations` returns the connector catalog; connecting an API-key
  connector via `POST /credentials/connect` makes it appear as connected in
  `GET /credentials/status`, and `DELETE /credentials/connect/{id}` removes it.
- `alembic upgrade head` on an empty database creates every model table.

## Non-functional requirements

- **Python** ≥ 3.11; **strict typing** (mypy strict on `src`).
- **Lint/format** clean on the blocking ruff gate; CI enforces both.
- **Tests** run against Postgres + Redis; Temporal is mocked. Coverage floor
  enforced (`--cov-fail-under`).
- **Dependency-clean**: no imports of any private host package; `smart-llm` is the
  only first-party dependency, consumed from its public repo.
- **Deployable** as a single image running any of the api/worker/email/sms/
  webhook/mcp processes.
