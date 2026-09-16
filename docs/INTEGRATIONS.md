# notification-hub — Integrations Setup Guide

The hub ships a catalog of external-service **connectors**. This guide documents,
per connector: **what it does**, **how to set it up**, the **credentials/config**
it needs, and — importantly — its **current support status** in this build (some
connectors have working action code but no in-product way to supply credentials
yet; those are called out explicitly).

- Browse the catalog in the app on the **Integrations** page (React admin tab /
  Flutter *Connect* screen), or via `GET /api/v1/integrations`.
- The catalog is defined in
  [`integrations_catalog.py`](../src/integration_hub_backend/api/api/routes/integrations_catalog.py);
  the action routes live under
  [`api/api/routes/integrations/`](../src/integration_hub_backend/api/api/routes/integrations).

---

## How connectors are wired (read this first)

There are **two separate steps** to using any connector, and **three different
ways** credentials are supplied. Getting these right is the whole game.

### The two steps

1. **Store credentials** — done as a **company admin** (JWT auth), either:
   - the **Connect** flow on the Integrations page → `POST /api/v1/credentials/connect`
     (API-key connectors) or the OAuth consent flow (`/api/v1/oauth/*`); or
   - a **platform admin** setting global config; or
   - the **smart-llm key store** (for Claude).
2. **Invoke the connector** — the action endpoints under
   `/api/v1/integrations/<key>/…` are **machine-to-machine**: they authenticate
   with an **API key** (`X-API-Key` header), not the user JWT, and each requires
   the scope **`integrations:<key>`**. Create a key under **API Keys**
   (`POST /api/v1/api-keys`) with the scopes you need.

> So even after credentials are stored, a workflow/automation calls the
> integration with an API key that carries `integrations:<key>`.

### The three credential models

| Model | Who configures | Where it's read | Connectors |
|---|---|---|---|
| **Per-tenant credential** (Connect UI) | Company admin | `resolve_integration_secrets()` — per-company credential, else global | datadog, splunk, grafana, elasticsearch, kibana |
| **Per-tenant OAuth / API-key credential** (passed by `credential_id`) | Company admin | the credential the request names | gmail, outlook, mailchimp |
| **Global platform config** | Platform admin | `ObservabilityService.get_decrypted_config()` — **global only** | s3, stripe, google-drive, google-sheets |
| **smart-llm key store** | Company admin | `DatabaseKeyStore` (or legacy `credential_id`) | claude |
| **none** | — | — | excel |

---

## Support status at a glance

| Connector | Category | Auth | Set up in-product? | Status |
|---|---|---|---|---|
| **Gmail** | Email | OAuth2 | ✅ (needs server OAuth app) | Supported |
| **Outlook** | Email | OAuth2 | ✅ (needs server OAuth app) | Supported |
| **Mailchimp** | Marketing | API key | ✅ Connect UI | Supported |
| **Claude** | AI | API key | ✅ key store | Supported |
| **Excel** | Productivity | none | ✅ nothing to configure | Supported |
| **Datadog** | Observability | API key | ✅ Connect UI / global | Supported |
| **Splunk** | Observability | HEC token | ✅ Connect UI / global | Supported |
| **Grafana** | Observability | API key | ✅ Connect UI / global | Supported |
| **Elasticsearch** | Observability | API key / basic | ✅ Connect UI / global | Supported |
| **Kibana** | Observability | API key / basic | ✅ Connect UI / global | Supported |
| **Amazon S3** | Storage | AWS keys | ⚠️ **No config path** | Action code works; see [Not-yet-wired](#not-yet-wired-connectors) |
| **Stripe** | Payments | API key | ⚠️ **No config path** | Action code works; see [Not-yet-wired](#not-yet-wired-connectors) |
| **Google Drive** | Storage | service account | ⚠️ **No config path** | Action code works; OAuth connect is vestigial |
| **Google Sheets** | Productivity | service account | ⚠️ **No config path** | Action code works; OAuth connect is vestigial |

Legend: ✅ configurable through the product · ⚠️ implemented in code but not yet
configurable without a direct DB write (details below).

---

## Email

### Gmail

**What it does** — send mail and read the inbox via the Gmail API.
`POST /api/v1/integrations/gmail/send`, `POST /api/v1/integrations/gmail/read`
(scope `integrations:gmail`). Each request names a stored OAuth credential by
`credential_id`.

**Setup**

1. **Platform (once):** create a Google Cloud OAuth 2.0 **Web application** client
   and set these server env vars:
   - `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`
   - `GMAIL_REDIRECT_URI` — must equal the callback the hub serves,
     `…/api/v1/oauth/gmail/callback`, and be listed as an authorized redirect URI
     in Google.
   - Enable the **Gmail API** on the project. Scopes requested:
     `gmail.send`, `gmail.readonly`, `gmail.modify`, `userinfo.email`.
2. **Per tenant:** on the Integrations page click **Connect** on Gmail (or
   `GET /api/v1/oauth/gmail/authorize-url?name=My Gmail` → open the returned URL).
   Completing consent stores an `oauth2` credential; its `credential_id` is what
   `send`/`read` calls reference.
3. **To invoke:** create an API key with scope `integrations:gmail`.

### Outlook / Microsoft 365

**What it does** — send mail and read folders via Microsoft Graph.
`POST /api/v1/integrations/outlook/send`, `POST /api/v1/integrations/outlook/read`
(scope `integrations:outlook`), referencing a stored `credential_id`.

**Setup**

1. **Platform (once):** register an **Azure AD app** (Microsoft Entra) and set:
   - `OUTLOOK_CLIENT_ID`, `OUTLOOK_CLIENT_SECRET`
   - `OUTLOOK_TENANT_ID` (your tenant id, or `common` for multi-tenant)
   - `OUTLOOK_REDIRECT_URI` = `…/api/v1/oauth/outlook/callback` (add it as a
     redirect URI in Azure). Delegated Graph permissions:
     `Mail.ReadWrite`, `Mail.Send`, `offline_access`.
2. **Per tenant:** **Connect** on Outlook (or
   `GET /api/v1/oauth/outlook/authorize-url?name=…`) and complete consent → stores
   the credential.
3. **To invoke:** API key with scope `integrations:outlook`.

---

## Marketing

### Mailchimp

**What it does** — subscribe / update / archive / tag / fetch list members.
`POST /api/v1/integrations/mailchimp/member` (scope `integrations:mailchimp`),
referencing a `credential_id`.

**Setup**

1. In Mailchimp, create an **API key** (Account → Extras → API keys).
2. On the Integrations page click **Connect** on Mailchimp and paste the key into
   the **`api_key`** field (`POST /api/v1/credentials/connect`,
   `secret_data: {"api_key": "…"}`). The data-center prefix (e.g. `us21`) is
   parsed automatically from the key suffix — no separate field needed.
3. **To invoke:** API key with scope `integrations:mailchimp`. Pass the stored
   credential's `credential_id`, plus `list_id`, `email`, and `operation`.

---

## AI

### Claude (Anthropic)

**What it does** — chat completions through the smart-llm Agent.
`POST /api/v1/integrations/claude/complete` (scope `integrations:claude`).

**Setup** — the API key is resolved from the **smart-llm key store** first
(register via `POST /api/v1/ai-agents/llm-keys/`, keyed by company + provider),
and only falls back to a legacy `IntegrationCredential` if you pass `credential_id`.
Prefer the key store. Model/provider default to Claude 3.5 Sonnet / `anthropic`
and are overridable per request.

> Claude powers the hub's whole AI layer (agents, skills, tools); see the AI
> sections of the [User Guide](USER_GUIDE.md). The `/integrations/claude/complete`
> route is a thin convenience endpoint over that.

---

## Productivity

### Excel

**What it does** — parse and generate `.xlsx`. `POST /api/v1/integrations/excel/read`
(multipart file upload → JSON rows) and `POST /api/v1/integrations/excel/write`
(JSON rows → downloadable `.xlsx`). Scope `integrations:excel`.

**Setup** — none. No credentials or external service. Just call it with an API
key carrying `integrations:excel`.

---

## Observability

All five read credentials via `resolve_integration_secrets()`, which prefers a
**per-company** Connect-UI credential and falls back to a **global** platform
config. Two ways to configure each:

- **Per tenant (recommended):** company admin clicks **Connect** on the
  Integrations page and enters the fields below
  (`POST /api/v1/credentials/connect`).
- **Platform-wide:** a platform admin sets global config via
  `PUT /api/v1/admin/observability/{name}` with `{"is_enabled": true, "config": {…}}`
  (this endpoint accepts only `datadog`, `splunk`, `grafana`, `elasticsearch`,
  `kibana`).

To **invoke** any of them, use an API key with `integrations:<name>`.

### Datadog
`POST /integrations/datadog/event`, `/integrations/datadog/log` (async via
Temporal). **Fields:** `api_key` (required); `site` (optional — one of
`us1`,`us3`,`us5`,`eu1`,`ap1`; default `us1`). Create the key in Datadog under
**Organization Settings → API Keys**.

### Splunk
`POST /integrations/splunk/event`. **Fields:** `hec_token`, `hec_url` (your HEC
base, e.g. `https://http-inputs-xxx.splunkcloud.com:8088`). Enable an **HTTP
Event Collector** token in Splunk and allow the `event` endpoint.

### Grafana
`POST /integrations/grafana/annotation`. **Fields:** `api_key` (a Grafana service-
account token) and `base_url` (e.g. `https://myorg.grafana.net`).

### Elasticsearch
`POST /integrations/elasticsearch/index`. **Fields:** `base_url` and **either**
`api_key` **or** `username` + `password` (basic auth).

### Kibana
`GET /integrations/kibana/dashboards`. **Fields:** `base_url` and **either**
`api_key` **or** `username` + `password`.

---

## Not-yet-wired connectors

These four connectors have **fully implemented action code** (real AWS/Stripe/
Google SDK calls), but there is currently **no supported way to supply their
credentials** through the product:

- Their services read **only** the global `NotificationSystemIntegration` table
  (`ObservabilityService.get_decrypted_config`), which has **no per-company
  path** — so a credential stored via the Integrations page **Connect** flow is
  *not* read by these connectors.
- The global-config admin endpoint `PUT /api/v1/admin/observability/{name}`
  **deliberately rejects** these names (it only allows the five observability
  connectors), and no migration seeds them.

The only way to make them work today is to insert a row into
`notification_system_integrations` directly in the database. Treat them as
**preview / not production-ready** until a config path is added.

| Connector | Endpoints (scope) | Config keys the code reads (global row `name`) |
|---|---|---|
| **Amazon S3** | `POST /integrations/s3/operation` — `upload`/`download`/`list`/`delete`/`get_url` (`integrations:s3`) | `s3`: `access_key_id`, `secret_access_key`, `region` (default `us-east-1`) |
| **Stripe** | `GET /integrations/stripe/customers/{id}`, `POST /integrations/stripe/payments/intent`, `GET /integrations/stripe/invoices` (`integrations:stripe`) | `stripe`: `api_key` |
| **Google Drive** | `GET /integrations/google-drive/files`, `POST /integrations/google-drive/files/upload` (`integrations:google_drive`) | `google_drive`: `credentials_json` (a Google **service-account** JSON) |
| **Google Sheets** | `GET /integrations/google-sheets/values`, `POST /integrations/google-sheets/values/append` (`integrations:google_sheets`) | `google_sheets`: `credentials_json` (service-account JSON) |

> **Google Drive/Sheets caveat:** the catalog lists these as `oauth2` and an
> OAuth **Connect** flow exists (`/api/v1/oauth/google-drive/authorize-url`,
> `…/google-sheets/…`), **but the action services authenticate with a global
> service-account JSON and ignore the per-user OAuth token.** So the OAuth connect
> is currently vestigial; a service account is the only auth the code honors.

### Making a not-yet-wired connector functional (interim)

Until a supported path lands, a platform operator can seed the global row, e.g.
for Stripe:

```
notification_system_integrations
  name              = 'stripe'
  is_enabled        = true
  encrypted_config  = <Fernet-encrypted JSON: {"api_key": "sk_live_…"}>
```

`encrypted_config` is Fernet-encrypted with the hub's field-encryption key, so
seed it with a small script that reuses the hub's
`crud.system_integrations.update_system_integration` (which encrypts for you)
rather than writing the column by hand.

---

## Summary

- **Ready to use in-product:** Gmail, Outlook (need a server OAuth app), Mailchimp,
  Claude, Excel, Datadog, Splunk, Grafana, Elasticsearch, Kibana.
- **Implemented but needs a config path before use:** Amazon S3, Stripe,
  Google Drive, Google Sheets.
- Every connector action is called with an **API key** carrying
  `integrations:<key>`; credentials are stored separately (Connect UI, OAuth,
  smart-llm key store, or global admin config).
