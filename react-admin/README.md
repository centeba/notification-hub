# notification-hub — React admin

A small Vite + React + TypeScript admin UI for Notification Hub, with parity to
the [`flutter_package`](../flutter_package) (`notification_hub_ui`):

- **Dashboard** — delivery health (sent / failed / rate) + by-channel breakdown,
  computed from the most recent `/logs`.
- **History** — every delivery attempt, filterable by channel and status, paged.
- **Rules** — enable/disable and delete routing rules.
- **Preferences** — per-channel opt-in for the current user.

## Develop

```bash
npm install
npm run dev            # http://localhost:5174
```

Dev requests to `/api` are proxied to the backend. Point the proxy at your API
with `VITE_API_TARGET` (default `http://localhost:8001`):

```bash
VITE_API_TARGET=http://localhost:8001 npm run dev
```

## Configuration

| Env | Default | Effect |
|---|---|---|
| `VITE_API_BASE` | `/api/v1` | API base path the client calls |
| `VITE_API_TARGET` | `http://localhost:8001` | Dev-proxy upstream for `/api` |

Auth: if present, `localStorage["notif_hub_token"]` is sent as a bearer token and
`localStorage["notif_hub_company_id"]` as `X-Company-Id`.

## Build

```bash
npm run build         # tsc -b && vite build → dist/
```

Serve `dist/` behind the same origin as the API (the platform's reverse-proxy
model), or set `VITE_API_BASE` to an absolute URL at build time.
