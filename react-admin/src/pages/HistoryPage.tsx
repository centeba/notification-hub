import { useState } from "react";
import { api } from "../api";
import { useResource } from "../useResource";
import { Async, StatusPill } from "../ui";

const PAGE_SIZE = 25;
const STATUSES = ["", "sent", "failed", "pending"];

export function HistoryPage() {
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);

  const state = useResource(
    () => api.logs({ skip: page * PAGE_SIZE, limit: PAGE_SIZE, channel, status }),
    [channel, status, page],
  );

  const channelsState = useResource(() => api.channels(), []);

  return (
    <section>
      <h1>Delivery History</h1>
      <p className="muted">Every notification attempt, newest first.</p>

      <div className="toolbar">
        <label>
          Channel
          <select
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All</option>
            {(channelsState.data?.data ?? []).map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s === "" ? "All" : s}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Async state={state}>
        {(env) => (
          <>
            <div className="card">
              <table className="table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Channel</th>
                    <th>Event</th>
                    <th>Recipient</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {env.data.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="muted pad">
                        No deliveries match these filters.
                      </td>
                    </tr>
                  ) : (
                    env.data.map((l) => (
                      <tr key={l.id}>
                        <td>
                          <StatusPill status={l.status} />
                        </td>
                        <td>{l.channel}</td>
                        <td>{l.event_type}</td>
                        <td className="muted">{l.recipient ?? "—"}</td>
                        <td className="muted">{new Date(l.created_at).toLocaleString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="pager">
              <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                ← Prev
              </button>
              <span className="muted">
                Page {page + 1}
                {typeof env.count === "number" ? ` of ${Math.max(1, Math.ceil(env.count / PAGE_SIZE))}` : ""}
              </span>
              <button
                disabled={env.data.length < PAGE_SIZE}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </button>
            </div>
          </>
        )}
      </Async>
    </section>
  );
}
