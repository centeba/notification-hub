import { useState } from "react";
import { api, ApiError } from "../api";
import { useResource } from "../useResource";
import { Async, Toggle } from "../ui";

export function PreferencesPage() {
  const state = useResource(() => api.myPreferences(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function toggle(channelId: string, enabled: boolean) {
    setBusy(channelId);
    setActionError(null);
    try {
      await api.updatePreference(channelId, { is_enabled: enabled });
      state.reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Update failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <h1>My Preferences</h1>
      <p className="muted">Choose which channels may notify you.</p>
      {actionError ? <div className="error pad">{actionError}</div> : null}

      <Async state={state}>
        {(env) => (
          <div className="card">
            {env.data.length === 0 ? (
              <p className="muted pad">No channels available.</p>
            ) : (
              <ul className="pref-list">
                {env.data.map((p) => (
                  <li key={p.channel_id} className={busy === p.channel_id ? "row-busy" : ""}>
                    <div>
                      <div className="pref-name">{p.channel}</div>
                      {typeof p.priority === "number" ? (
                        <div className="muted small">Priority {p.priority}</div>
                      ) : null}
                    </div>
                    <Toggle
                      checked={p.is_enabled}
                      onChange={(v) => toggle(p.channel_id, v)}
                      label={p.is_enabled ? "On" : "Off"}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Async>
    </section>
  );
}
