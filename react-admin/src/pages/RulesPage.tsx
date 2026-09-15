import { useState } from "react";
import { api, ApiError } from "../api";
import type { Rule } from "../api";
import { useResource } from "../useResource";
import { Async, Toggle } from "../ui";

export function RulesPage() {
  const state = useResource(() => api.rules(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setActionError(null);
    try {
      await fn();
      state.reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <h1>Routing Rules</h1>
      <p className="muted">
        Rules decide which channels fire for an event. Higher priority wins.
      </p>
      {actionError ? <div className="error pad">{actionError}</div> : null}

      <Async state={state}>
        {(env) => (
          <div className="card">
            <table className="table">
              <thead>
                <tr>
                  <th>Active</th>
                  <th>Name</th>
                  <th>Event</th>
                  <th>Channels</th>
                  <th>Priority</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {env.data.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted pad">
                      No rules defined yet.
                    </td>
                  </tr>
                ) : (
                  env.data.map((r: Rule) => (
                    <tr key={r.id} className={busy === r.id ? "row-busy" : ""}>
                      <td>
                        <Toggle
                          checked={r.is_active}
                          onChange={(v) =>
                            run(r.id, () => api.updateRule(r.id, { is_active: v }))
                          }
                        />
                      </td>
                      <td>{r.name}</td>
                      <td className="muted">{r.event_type ?? "—"}</td>
                      <td>
                        {(r.channel_ids ?? []).length === 0
                          ? "—"
                          : `${r.channel_ids.length} channel(s)`}
                      </td>
                      <td>{r.priority}</td>
                      <td>
                        <button
                          className="danger"
                          disabled={busy === r.id}
                          onClick={() => {
                            if (confirm(`Delete rule "${r.name}"?`)) {
                              run(r.id, () => api.deleteRule(r.id));
                            }
                          }}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </section>
  );
}
