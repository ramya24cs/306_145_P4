import { useState } from "react";
import { api } from "../api.js";
import { Countdown, Empty, ErrorBox, PageHeader, ReportTable, Ring, Skeleton, StatCard, fmtTime, useLoad, useToast } from "../ui.jsx";

function DoctorControls({ doc, onChange }) {
  const toast = useToast();
  const [cap, setCap] = useState(String(doc.max_capacity));
  const act = async (fn, msg) => { try { await fn(); toast("success", msg); onChange(); } catch (e) { toast("error", e.message); } };
  return (
    <div className={`doc-panel ${doc.available ? "" : "off"}`}>
      <div><strong>{doc.name}</strong> <span className="muted">({doc.role.toLowerCase()})</span></div>
      <Ring value={doc.current_load} max={doc.max_capacity} label={`${doc.available_capacity} free`} />
      <span className={doc.available ? "pill-ok" : "pill-bad"}>{doc.available ? "Available" : "Unavailable"}</span>
      <button className="btn small" onClick={() => act(() => api.setAvailability(doc.doctor_id, !doc.available), `${doc.name} ${doc.available ? "unavailable" : "available"}`)}>
        {doc.available ? "Set unavailable" : "Set available"}
      </button>
      <form className="row" style={{ justifyContent: "center" }} onSubmit={(e) => { e.preventDefault(); act(() => api.setCapacity(doc.doctor_id, Number(cap)), `${doc.name} capacity ${cap}`); }}>
        <input type="number" min="0" max="50" value={cap} onChange={(e) => setCap(e.target.value)} aria-label={`Capacity for ${doc.name}`} />
        <button className="btn small primary">Set</button>
      </form>
    </div>
  );
}

function ZoneFixer({ report, onDone }) {
  const toast = useToast();
  const [zone, setZone] = useState("A");
  const go = async () => { try { await api.fixZone(report.report_id, zone); toast("success", `${report.report_id} re-routed to Zone ${zone}`); onDone(); } catch (e) { toast("error", e.message); } };
  return (
    <div className="row">
      <select style={{ width: 90 }} value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Corrected zone">{["A", "B", "C", "D"].map((z) => <option key={z}>{z}</option>)}</select>
      <button className="btn small primary" onClick={go}>Fix zone</button>
    </div>
  );
}

export default function RoutingDashboard() {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad(() => api.routingTable(), [], 5000);
  const advance = async (m) => {
    try { const r = await api.advanceClock(m); toast("success", `Clock +${m} min. ${r.escalated_by_sla.length} report(s) escalated by SLA.`); reload(); } catch (e) { toast("error", e.message); }
  };
  if (loading && !data) return <Skeleton n={4} />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <>
      <PageHeader title="Routing" sub={`Critical and Stat reports must be assigned within ${data.sla_minutes} minutes. Simulated clock: ${fmtTime(data.clock)}`}>
        <button className="btn" onClick={() => advance(5)}>Advance clock 5 min</button>
        <button className="btn primary" onClick={() => advance(16)}>Advance clock 16 min</button>
      </PageHeader>
      <div className="stats">
        <StatCard label="Waiting reports" value={data.waiting.length} tone={data.waiting.length ? "warn" : ""} />
        <StatCard label="Escalated reports" value={data.escalated.length} tone={data.escalated.length ? "bad" : ""} />
        <StatCard label="Active Critical / Stat" value={data.priority_overrides.length} />
      </div>

      <h3 style={{ marginBottom: 12 }}>Four-zone routing table</h3>
      <div className="grid g2" style={{ marginBottom: 20 }}>
        {data.zones.map((z) => (
          <div className="zone-card" key={z.zone_id}>
            <div className="zone-head"><span className="zone-letter">{z.zone_id}</span><div><b>{z.name}</b><div style={{ opacity: .75, fontSize: ".85rem" }}>Primary {z.primary?.name} · Backup {z.backup?.name}</div></div>
              <small>{(z.primary?.available_capacity || 0) + (z.backup?.available_capacity || 0)} free slots<br />{z.waiting} waiting</small></div>
            <div className="doc-panels">{z.primary && <DoctorControls doc={z.primary} onChange={reload} />}{z.backup && <DoctorControls doc={z.backup} onChange={reload} />}</div>
          </div>
        ))}
      </div>

      <div className="grid g2">
        <section className="card">
          <h3>Waiting queue <span className="muted">(priority, then FIFO, then report ID)</span></h3>
          {data.waiting.length === 0 ? <Empty>No reports are waiting for a doctor.</Empty> :
            <ReportTable reports={data.waiting} columns={["id", "category", "zone", "priority", "sla", "submitted"]} />}
        </section>
        <section className="card">
          <h3>Central escalation queue</h3>
          {data.escalated.length === 0 ? <Empty>No escalated reports.</Empty> :
            <ReportTable reports={data.escalated} columns={["id", "category", "zone", "reason"]}
              actions={(r) => (["A", "B", "C", "D"].includes(r.ward_zone) ? <span className="muted">Auto-assigns when capacity frees</span> : <ZoneFixer report={r} onDone={reload} />)} />}
        </section>
      </div>

      <section className="card">
        <h3>Priority overrides</h3>
        <p className="muted">Open Critical and Stat reports are always served before lower-priority work. “Jumped ahead of” counts earlier waiting reports they overtake.</p>
        {data.priority_overrides.length === 0 ? <Empty>No open Critical or Stat reports.</Empty> : (
          <div className="table-wrap">
            <table className="stack">
              <thead><tr><th>Report</th><th>Category</th><th>Zone</th><th>Status</th><th>Doctor</th><th>SLA</th><th>Jumped ahead of</th></tr></thead>
              <tbody>
                {data.priority_overrides.map((r) => (
                  <tr key={r.report_id}>
                    <td data-label="Report"><strong>{r.report_id}</strong></td><td data-label="Category">{r.category} (P{r.priority})</td><td data-label="Zone">{r.ward_zone}</td>
                    <td data-label="Status">{r.status} / {r.queue_state}</td><td data-label="Doctor">{r.assigned_doctor || "-"}</td><td data-label="SLA"><Countdown deadline={r.sla_deadline} assignedAt={r.assigned_at} /></td><td data-label="Jumped ahead of">{r.jumped_ahead_of}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h3>Routing history</h3>
        {data.history.length === 0 ? <Empty>No routing decisions yet.</Empty> : (
          <div className="table-wrap">
            <table className="stack">
              <thead><tr><th>Time</th><th>Report</th><th>Decision</th><th>Detail</th></tr></thead>
              <tbody>
                {data.history.map((h) => (
                  <tr key={h.log_id}><td data-label="Time">{fmtTime(h.created_at)}</td><td data-label="Report">{h.report_id}</td><td data-label="Decision"><strong>{h.decision}</strong></td><td data-label="Detail">{h.detail}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
