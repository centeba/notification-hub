import type { ReactNode } from "react";
import type { AsyncState } from "./useResource";

/** Renders loading / error / empty / data states for an async resource. */
export function Async<T>({
  state,
  children,
  empty,
}: {
  state: AsyncState<T>;
  children: (data: T) => ReactNode;
  empty?: ReactNode;
}) {
  if (state.loading && state.data === null) {
    return <div className="muted pad">Loading…</div>;
  }
  if (state.error) {
    return (
      <div className="error pad">
        <p>{state.error}</p>
        <button onClick={state.reload}>Retry</button>
      </div>
    );
  }
  if (state.data === null) return <>{empty ?? <div className="muted pad">No data.</div>}</>;
  return <>{children(state.data)}</>;
}

/** A status pill with semantic color derived from the delivery status. */
export function StatusPill({ status }: { status: string }) {
  const s = status.toLowerCase();
  const kind =
    s === "sent" || s === "delivered"
      ? "ok"
      : s === "failed" || s === "error"
        ? "bad"
        : "warn";
  return <span className={`pill pill-${kind}`}>{status}</span>;
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label ? <span>{label}</span> : null}
    </label>
  );
}
