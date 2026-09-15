import { api } from "../api";
import type { DeliveryLog } from "../api";
import { useResource } from "../useResource";
import { Async, StatusPill } from "../ui";

function statsFrom(logs: DeliveryLog[]) {
  const total = logs.length;
  const sent = logs.filter((l) => ["sent", "delivered"].includes(l.status.toLowerCase())).length;
  const failed = logs.filter((l) => ["failed", "error"].includes(l.status.toLowerCase())).length;
  const rate = total > 0 ? ((sent / total) * 100).toFixed(1) : "0";
  const byChannel = new Map<string, number>();
  for (const l of logs) byChannel.set(l.channel, (byChannel.get(l.channel) ?? 0) + 1);
  return { total, sent, failed, rate, byChannel };
}

export function DashboardPage() {
  const state = useResource(() => api.logs({ limit: 100 }), []);

  return (
    <section>
      <h1>Dashboard</h1>
      <p className="muted">Delivery health over the most recent 100 notifications.</p>
      <Async state={state}>
        {(env) => {
          const s = statsFrom(env.data);
          const maxChannel = Math.max(1, ...Array.from(s.byChannel.values()));
          return (
            <>
              <div className="stat-row">
                <StatCard label="Total Sent" value={s.sent} kind="ok" />
                <StatCard label="Total Failed" value={s.failed} kind="bad" />
                <StatCard label="Delivery Rate" value={`${s.rate}%`} kind="info" />
                <StatCard label="Total Events" value={s.total} kind="neutral" />
              </div>

              <div className="card">
                <h2>By channel</h2>
                {s.byChannel.size === 0 ? (
                  <p className="muted">No events yet.</p>
                ) : (
                  <ul className="bars">
                    {Array.from(s.byChannel.entries())
                      .sort((a, b) => b[1] - a[1])
                      .map(([channel, n]) => (
                        <li key={channel}>
                          <span className="bar-label">{channel}</span>
                          <span className="bar-track">
                            <span
                              className="bar-fill"
                              style={{ width: `${(n / maxChannel) * 100}%` }}
                            />
                          </span>
                          <span className="bar-value">{n}</span>
                        </li>
                      ))}
                  </ul>
                )}
              </div>

              <div className="card">
                <h2>Recent activity</h2>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Channel</th>
                      <th>Event</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {env.data.slice(0, 10).map((l) => (
                      <tr key={l.id}>
                        <td>
                          <StatusPill status={l.status} />
                        </td>
                        <td>{l.channel}</td>
                        <td>{l.event_type}</td>
                        <td className="muted">{new Date(l.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          );
        }}
      </Async>
    </section>
  );
}

function StatCard({
  label,
  value,
  kind,
}: {
  label: string;
  value: string | number;
  kind: "ok" | "bad" | "info" | "neutral";
}) {
  return (
    <div className={`stat-card stat-${kind}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
