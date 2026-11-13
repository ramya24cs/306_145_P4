import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

/* ================= toasts ================= */
const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);
  const push = useCallback((type, message) => {
    const id = ++idRef.current;
    setItems((x) => [...x.slice(-3), { id, type, message }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 5200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.type}`}>{t.message}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/* ================= real-time (Server-Sent Events) ================= */
const LiveCtx = createContext({ version: 0, connected: false, offset: 0, last: null });
export const useLiveCtx = () => useContext(LiveCtx);

export function LiveProvider({ children }) {
  const toast = useToast();
  const [state, setState] = useState({ version: 0, connected: false, last: null });
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const sync = () => api.health().then((h) => setOffset(new Date(h.server_time).getTime() - Date.now())).catch(() => {});
    sync();
    const es = new EventSource((import.meta.env.VITE_API_URL || "/api") + "/events");
    es.onopen = () => setState((s) => ({ ...s, connected: true }));
    es.onerror = () => setState((s) => ({ ...s, connected: false }));
    es.addEventListener("hello", () => setState((s) => ({ ...s, connected: true })));
    es.addEventListener("change", (e) => {
      const d = JSON.parse(e.data);
      setState({ version: d.version, connected: true, last: d });
      sync();
      if (d.kind === "submitted" && d.report_id) {
        toast("live", `New ${d.category} report ${d.report_id} → ${d.queue_state === "Assigned" ? "assigned" : (d.queue_state || "").toLowerCase()}`);
      }
    });
    return () => es.close();
  }, [toast]);

  return <LiveCtx.Provider value={{ ...state, offset }}>{children}</LiveCtx.Provider>;
}

/** Server-adjusted "now" that ticks every second (honours the simulated lab clock). */
export function useServerNow(tickMs = 1000) {
  const { offset } = useLiveCtx();
  const [t, setT] = useState(Date.now());
  useEffect(() => { const i = setInterval(() => setT(Date.now()), tickMs); return () => clearInterval(i); }, [tickMs]);
  return t + offset;
}

/** Data hook: loads on mount, refetches instantly on every server push, with a slow poll as safety net. */
export function useLoad(fn, deps = [], interval = 0) {
  const { version } = useLiveCtx();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const first = useRef(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(async (silent) => {
    if (!silent) setLoading(true);
    try { setData(await fn()); setError(null); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, deps);
  useEffect(() => {
    run(!first.current);
    first.current = false;
    if (!interval) return undefined;
    const t = setInterval(() => run(true), Math.max(interval, 15000));
    return () => clearInterval(t);
  }, [run, interval, version]);
  return { data, loading, error, reload: () => run(true) };
}

/* ================= visual primitives ================= */
const ICONS = {
  home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  plus: "M12 5v14M5 12h14",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  pulse: "M3 12h4l2-6 4 12 2-6h6",
  route: "M5 4v8a4 4 0 0 0 4 4h10M16 12l4 4-4 4",
  chart: "M4 20V10M10 20V4M16 20v-8M22 20H2",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3",
  menu: "M4 6h16M4 12h16M4 18h16",
};
export const Icon = ({ name }) => <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[name]} /></svg>;

export function CountUp({ value }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (typeof value !== "number") return undefined;
    const start = performance.now(), a = from.current, dur = 650;
    let raf;
    const step = (t) => {
      const p = Math.min(1, (t - start) / dur);
      setShown(Math.round(a + (value - a) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step); else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return typeof value === "number" ? shown : "-";
}

export function Ring({ value, max, size = 92, label = "load" }) {
  const r = (size - 14) / 2, c = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(1, value / max) : 1;
  const color = pct >= 1 ? "#e5484d" : pct >= 0.66 ? "#e8940c" : "#1d6fe8";
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e6eefa" strokeWidth="10" />
        <circle className="rc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <div className="ring-label"><b>{value}/{max}</b><span>{label}</span></div>
    </div>
  );
}

const pad = (n) => String(n).padStart(2, "0");
/** Live SLA countdown to a deadline (turns amber, then red, ticks every second). */
export function Countdown({ deadline, assignedAt }) {
  const now = useServerNow();
  if (!deadline) return <span className="muted">-</span>;
  if (assignedAt) return <span className="cd done">Assigned</span>;
  const left = new Date(deadline).getTime() - now;
  if (left <= 0) return <span className="cd bad">Breached</span>;
  const s = Math.floor(left / 1000);
  return <span className={`cd ${s < 180 ? "bad" : s < 420 ? "warn" : ""}`}>{pad(Math.floor(s / 60))}:{pad(s % 60)}</span>;
}

export const Skeleton = ({ n = 3 }) => <div>{Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" />)}</div>;
export const Spinner = ({ label = "Loading" }) => <div className="spinner-wrap"><span className="spinner" aria-hidden="true" />{label}…</div>;
export const ErrorBox = ({ message, onRetry }) => (
  <div className="alert error"><span>{message}</span>{onRetry && <button className="btn small" onClick={onRetry}>Retry</button>}</div>
);
export const Empty = ({ children }) => <div className="empty">{children}</div>;

const slug = (s) => String(s || "").toLowerCase().replace(/\s+/g, "-");
export const StatusBadge = ({ status }) => <span className={`badge st-${slug(status)}`}>{status}</span>;
export const CategoryBadge = ({ category }) => <span className={`badge cat-${slug(category)}`}>{category}</span>;
export const SlaBadge = ({ sla }) => (sla === "N/A" ? <span className="muted">-</span> : <span className={`badge sla-${slug(sla)}`}>{sla}</span>);
export const StatCard = ({ label, value, tone = "" }) => (
  <div className={`stat ${tone}`}><div className="stat-value"><CountUp value={value} /></div><div className="stat-label">{label}</div></div>
);

export const Segmented = ({ options, value, onChange, label }) => (
  <div className="seg" role="group" aria-label={label}>
    {options.map(([v, l]) => <button type="button" key={v} className={value === v ? "on" : ""} aria-pressed={value === v} onClick={() => onChange(v)}>{l}</button>)}
  </div>
);

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" }) : "-");
export function ago(iso, now) {
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function PageHeader({ title, sub, children }) {
  return (
    <header className="page-head">
      <div><h1>{title}</h1>{sub && <p className="muted">{sub}</p>}</div>
      <div className="head-actions">{children}</div>
    </header>
  );
}

/* ================= report drawer + table ================= */
const FLOW = ["Pending", "Assigned", "In Progress", "Resolved"];

export function ReportDetail({ report, onClose }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!report) return null;
  const at = FLOW.indexOf(report.status);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`Report ${report.report_id}`}>
        <div className="row between">
          <h3 style={{ margin: 0 }}>{report.report_id}</h3>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
        <div className="row" style={{ marginTop: 8 }}><CategoryBadge category={report.category} /><StatusBadge status={report.status} /><SlaBadge sla={report.sla_status} /></div>
        <div className="steps">{FLOW.map((s, i) => <div key={s} className={`step ${i < at ? "done" : i === at ? (s === "Resolved" ? "done" : "now") : ""}`}><i />{s}</div>)}</div>
        {report.sla_deadline && !report.assigned_at && <div className="row" style={{ marginBottom: 14 }}><span className="muted">Time left to assign</span><Countdown deadline={report.sla_deadline} assignedAt={report.assigned_at} /></div>}
        <dl className="kv">
          <dt>Patient ID</dt><dd>{report.patient_id}</dd>
          <dt>Report code</dt><dd>{report.report_code}</dd>
          <dt>Priority</dt><dd>P{report.priority} - {report.priority_label}</dd>
          <dt>Queue</dt><dd>{report.queue_state}</dd>
          <dt>Ward zone</dt><dd>{report.ward_zone}</dd>
          <dt>Assigned doctor</dt><dd>{report.assigned_doctor || "Not assigned"}</dd>
          <dt>Routing decision</dt><dd>{report.routing_decision || "-"}</dd>
          {report.escalation_reason && (<><dt>Escalation reason</dt><dd>{report.escalation_reason}</dd></>)}
          <dt>Validation</dt><dd>{report.validation_result}</dd>
          <dt>Reporter</dt><dd>{report.reporter_name} ({report.reporter_contact})</dd>
          <dt>Urgency</dt><dd>{report.urgency}</dd>
          <dt>Description</dt><dd>{report.description || "-"}</dd>
          <dt>Submitted</dt><dd>{fmtTime(report.submitted_at)}</dd>
          <dt>Assigned</dt><dd>{fmtTime(report.assigned_at)}</dd>
          <dt>Last update</dt><dd>{fmtTime(report.status_updated_at)}</dd>
        </dl>
        {report.history && (
          <>
            <h4>Status history</h4>
            <ul className="timeline">{report.history.map((h) => <li key={h.history_id}><strong>{h.new_status}</strong> by {h.changed_by} <span className="muted">{fmtTime(h.changed_at)}</span>{h.note ? ` - ${h.note}` : ""}</li>)}</ul>
            <h4>Routing decisions</h4>
            <ul className="timeline">{report.routing_log.map((l) => <li key={l.log_id}><strong>{l.decision}</strong> <span className="muted">{fmtTime(l.created_at)}</span>{l.detail ? ` - ${l.detail}` : ""}</li>)}</ul>
          </>
        )}
      </aside>
    </>
  );
}

export function ReportTable({ reports, columns = ["id", "patient", "category", "zone", "priority", "status", "doctor", "submitted"], onRowClick, actions }) {
  const defs = {
    id: ["Report ID", (r) => <strong>{r.report_id}</strong>],
    patient: ["Patient ID", (r) => r.patient_id],
    category: ["Category", (r) => <CategoryBadge category={r.category} />],
    zone: ["Zone", (r) => r.ward_zone],
    priority: ["Priority", (r) => `P${r.priority} ${r.priority_label}`],
    status: ["Status", (r) => <StatusBadge status={r.status} />],
    queue: ["Queue", (r) => r.queue_state],
    doctor: ["Doctor", (r) => r.assigned_doctor || "-"],
    submitted: ["Submitted", (r) => fmtTime(r.submitted_at)],
    sla: ["SLA", (r) => (r.sla_deadline && !r.assigned_at ? <Countdown deadline={r.sla_deadline} assignedAt={r.assigned_at} /> : <SlaBadge sla={r.sla_status} />)],
    reason: ["Reason", (r) => r.escalation_reason || r.routing_decision || "-"],
  };
  return (
    <div className="table-wrap">
      <table className="stack">
        <thead><tr>{columns.map((c) => <th key={c}>{defs[c][0]}</th>)}{actions && <th>Actions</th>}</tr></thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.report_id} className={onRowClick ? "clickable" : ""} onClick={onRowClick ? () => onRowClick(r) : undefined}>
              {columns.map((c) => <td key={c} data-label={defs[c][0]}>{defs[c][1](r)}</td>)}
              {actions && <td data-label="Actions" onClick={(e) => e.stopPropagation()}>{actions(r)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
