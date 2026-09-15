import { useMemo, useState } from "react";
import { api, ApiError } from "../api";
import type { ConnectorStatus, IntegrationCatalogEntry } from "../api";
import { useResource } from "../useResource";
import { Async } from "../ui";

type SecretField = { key: string; value: string };

// Sensible default secret fields per api_key connector so the form isn't blank.
const DEFAULT_FIELDS: Record<string, string[]> = {
  s3: ["access_key_id", "secret_access_key", "region", "bucket"],
  stripe: ["api_key"],
  mailchimp: ["api_key", "server_prefix"],
  datadog: ["api_key", "app_key"],
  splunk: ["hec_token", "hec_url"],
  grafana: ["api_key", "base_url"],
  elasticsearch: ["api_key", "base_url"],
  kibana: ["api_key", "base_url"],
  claude: ["api_key"],
};

function authLabel(auth: string): string {
  return auth === "oauth2" ? "OAuth" : auth === "api_key" ? "API key" : "No auth";
}

export function IntegrationsPage() {
  const catalog = useResource(() => api.integrations(), []);
  // Connected state is JWT-admin only; tolerate failure (badges just won't show).
  const status = useResource(() => api.connectorStatus(), []);

  const statusByConnector = useMemo(() => {
    const map = new Map<string, ConnectorStatus>();
    for (const s of status.data ?? []) map.set(s.connector, s);
    return map;
  }, [status.data]);

  function reloadAll() {
    catalog.reload();
    status.reload();
  }

  return (
    <section>
      <h1>Integrations</h1>
      <p className="muted">
        Connect the notification hub to external services. OAuth connectors open a
        consent screen; API-key connectors store credentials securely for your company.
      </p>

      <Async state={catalog}>
        {(entries) => {
          const byCategory = groupByCategory(entries);
          return (
            <>
              {byCategory.map(([category, items]) => (
                <div key={category}>
                  <h2 className="cat-title">{category}</h2>
                  <div className="integration-grid">
                    {items.map((e) => (
                      <IntegrationCard
                        key={e.key}
                        entry={e}
                        connected={statusByConnector.get(e.key) ?? null}
                        onChanged={reloadAll}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </>
          );
        }}
      </Async>
    </section>
  );
}

function groupByCategory(
  entries: IntegrationCatalogEntry[],
): [string, IntegrationCatalogEntry[]][] {
  const groups = new Map<string, IntegrationCatalogEntry[]>();
  for (const e of entries) {
    const list = groups.get(e.category) ?? [];
    list.push(e);
    groups.set(e.category, list);
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function IntegrationCard({
  entry,
  connected,
  onChanged,
}: {
  entry: IntegrationCatalogEntry;
  connected: ConnectorStatus | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oauthUrl, setOauthUrl] = useState<string | null>(null);

  async function disconnect() {
    if (!connected) return;
    if (!confirm(`Disconnect ${entry.name}?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.disconnectIntegration(connected.credential_id);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Disconnect failed");
    } finally {
      setBusy(false);
    }
  }

  async function startOauth() {
    setBusy(true);
    setError(null);
    setOauthUrl(null);
    try {
      const { authorize_url } = await api.oauthAuthorizeUrl(entry.key, entry.name);
      setOauthUrl(authorize_url);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Could not start OAuth");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="integration-card">
      <div className="integration-head">
        <span className="integration-name">{entry.name}</span>
        {connected ? (
          <span className="pill pill-ok">Connected</span>
        ) : (
          <span className="pill pill-neutral">{authLabel(entry.auth)}</span>
        )}
      </div>
      <p className="integration-desc">{entry.description}</p>

      <div className="integration-actions">
        {connected ? (
          <button className="danger" disabled={busy} onClick={disconnect}>
            Disconnect
          </button>
        ) : entry.auth === "none" ? (
          <span className="muted small">No credentials required.</span>
        ) : entry.auth === "oauth2" ? (
          <button className="primary" disabled={busy} onClick={startOauth}>
            {busy ? "…" : "Connect"}
          </button>
        ) : (
          <button className="primary" disabled={busy} onClick={() => setOpen((v) => !v)}>
            {open ? "Cancel" : "Connect"}
          </button>
        )}
      </div>

      {error ? <div className="error pad small">{error}</div> : null}

      {oauthUrl ? (
        <div className="connect-form">
          <span className="small muted">
            Open this URL in your browser to grant access:
          </span>
          <div className="oauth-url">{oauthUrl}</div>
          <a className="small" href={oauthUrl} target="_blank" rel="noreferrer">
            Open consent screen ↗
          </a>
        </div>
      ) : null}

      {open && entry.auth === "api_key" ? (
        <ApiKeyForm
          entry={entry}
          onDone={() => {
            setOpen(false);
            onChanged();
          }}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

function ApiKeyForm({
  entry,
  onDone,
  onError,
}: {
  entry: IntegrationCatalogEntry;
  onDone: () => void;
  onError: (msg: string | null) => void;
}) {
  const [name, setName] = useState(entry.name);
  const [fields, setFields] = useState<SecretField[]>(
    (DEFAULT_FIELDS[entry.key] ?? ["api_key"]).map((k) => ({ key: k, value: "" })),
  );
  const [busy, setBusy] = useState(false);

  function setField(i: number, patch: Partial<SecretField>) {
    setFields((fs) => fs.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }

  async function save() {
    const secret_data: Record<string, string> = {};
    for (const f of fields) {
      if (f.key.trim() && f.value.trim()) secret_data[f.key.trim()] = f.value;
    }
    if (Object.keys(secret_data).length === 0) {
      onError("Enter at least one credential field.");
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api.connectIntegration({ connector: entry.key, name, secret_data });
      onDone();
    } catch (e) {
      onError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Connect failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="connect-form">
      <input
        placeholder="Display name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      {fields.map((f, i) => (
        <div key={i} className="kv-row">
          <input
            placeholder="field"
            value={f.key}
            onChange={(e) => setField(i, { key: e.target.value })}
          />
          <input
            placeholder="value"
            type="password"
            value={f.value}
            onChange={(e) => setField(i, { value: e.target.value })}
          />
          <button
            className="danger"
            disabled={fields.length === 1}
            onClick={() => setFields((fs) => fs.filter((_, idx) => idx !== i))}
            title="Remove field"
          >
            ✕
          </button>
        </div>
      ))}
      <div className="integration-actions">
        <button onClick={() => setFields((fs) => [...fs, { key: "", value: "" }])}>
          Add field
        </button>
        <button className="primary" disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
