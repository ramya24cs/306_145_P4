import { api } from "../api.js";
import { Countdown, CategoryBadge, CountUp, Empty, ErrorBox, Ring, Skeleton, ago, useLoad, useServerNow } from "../ui.jsx";

const tone = (d) => (/ESCALAT|ERROR/.test(d) ? "crit" : /ASSIGNED|RESOLVED/.test(d) ? "ok" : /WAITING|REVIEW/.test(d) ? "warn" : /SUBMITTED/.test(d) ? "" : "slate");
const human = (d) => d.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

export default function Overview({ go }) {
  const now = useServerNow(5000);
  const table = useLoad(() => api.routingTable(), []);
  const stats = useLoad(() => api.analytics(), []);
  const review = useLoad(() => api.queue("review"), []);
  const errors = useLoad(() => api.queue("error"), []);

  if ((table.loading || stats.loading) && !table.data) return <><div className="hero" style={{ height: 230 }} /><Skeleton n={3} /></>;
  if (table.error && !table.data) return <ErrorBox message={table.error} onRetry={table.reload} />;
  const t = table.data, s = stats.data?.summary;
  const urgent = t.priority_overrides.filter((r) => r.status !== "Resolved");
  const atRisk = urgent.filter((r) => !r.assigned_at).length;

  return (
    <>
      <section className="hero">
        <h1>Every result, routed to the right doctor in minutes.</h1>
        <p>Live view of submissions, ward queues and the 15-minute assignment promise for Critical and Stat reports.</p>
        <div className="hero-nums">
          <button className="hero-num" onClick={() => go("reports")}><b><CountUp value={s?.unresolved} /></b><span>Open reports</span></button>
          <button className="hero-num" onClick={() => go("routing")}><b><CountUp value={t.waiting.length} /></b><span>Waiting for a doctor</span></button>
          <button className={`hero-num ${t.escalated.length ? "hot" : ""}`} onClick={() => go("routing")}><b><CountUp value={t.escalated.length} /></b><span>Escalated</span></button>
          <button className={`hero-num ${atRisk ? "hot" : ""}`} onClick={() => go("routing")}><b><CountUp value={atRisk} /></b><span>Critical/Stat awaiting a doctor</span></button>
        </div>
      </section>

      <div className="grid g4" style={{ marginBottom: 20 }}>
        <button className="qtile" onClick={() => go("routing")}><i className="qdot stat" /><div><b><CountUp value={t.waiting.length} /></b><span>Waiting queue</span></div></button>
        <button className="qtile" onClick={() => go("routing")}><i className="qdot crit" /><div><b><CountUp value={t.escalated.length} /></b><span>Central escalation</span></div></button>
        <button className="qtile" onClick={() => go("reports")}><i className="qdot purple" /><div><b><CountUp value={review.data?.count} /></b><span>Review queue</span></div></button>
        <button className="qtile" onClick={() => go("reports")}><i className="qdot slate" /><div><b><CountUp value={errors.data?.count} /></b><span>Error queue</span></div></button>
      </div>

      <div className="grid g2" style={{ marginBottom: 20 }}>
        <section className="card">
          <h3>15-minute watchlist</h3>
          {urgent.length === 0 ? <Empty>No open Critical or Stat reports. Submit one to watch the countdown.</Empty> : urgent.slice(0, 7).map((r) => (
            <div className="sla-row" key={r.report_id}>
              <CategoryBadge category={r.category} />
              <div><b>{r.report_id}</b><div className="muted">Zone {r.ward_zone} · {r.assigned_doctor ? `with ${r.assigned_doctor}` : r.queue_state.toLowerCase()}</div></div>
              <Countdown deadline={r.sla_deadline} assignedAt={r.assigned_at} />
            </div>
          ))}
        </section>
        <section className="card">
          <h3>Live activity</h3>
          {t.history.length === 0 ? <Empty>No activity yet. Submit a report to see routing decisions appear here instantly.</Empty> : (
            <ul className="feed">
              {t.history.slice(0, 14).map((h) => (
                <li key={h.log_id}><i className={`fd ${tone(h.decision)}`} /><div><b>{human(h.decision)}</b> · {h.report_id}<small>{h.detail || "-"} · {ago(h.created_at, now)}</small></div></li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section>
        <h3 style={{ marginBottom: 12 }}>Ward zones</h3>
        <div className="grid g4">
          {t.zones.map((z) => (
            <button key={z.zone_id} className="qtile" style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }} onClick={() => go("routing")}>
              <div className="row between"><b style={{ fontSize: "1.3rem" }}>{z.name}</b><span className="muted">{z.waiting} waiting</span></div>
              <div className="row" style={{ justifyContent: "space-around" }}>
                {[z.primary, z.backup].map((d) => d && (
                  <div key={d.doctor_id} style={{ textAlign: "center" }}>
                    <Ring value={d.current_load} max={d.max_capacity} size={78} label={d.available ? "" : "off"} />
                    <div style={{ fontWeight: 600 }}>{d.name}</div><div className="muted">{d.role}{d.available ? "" : " · unavailable"}</div>
                  </div>
                ))}
              </div>
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
