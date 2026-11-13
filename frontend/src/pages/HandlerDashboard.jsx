import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, ErrorBox, PageHeader, ReportDetail, ReportTable, Spinner, StatCard, useLoad, useToast } from "../ui.jsx";

export default function HandlerDashboard() {
  const toast = useToast();
  const doctors = useLoad(() => api.doctors(), [], 10000);
  const [doctorId, setDoctorId] = useState(null);
  const [cap, setCap] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => { if (!doctorId && doctors.data?.length) setDoctorId(doctors.data[0].doctor_id); }, [doctors.data, doctorId]);
  const me = useLoad(() => (doctorId ? api.doctor(doctorId) : Promise.resolve(null)), [doctorId], 6000);
  const queues = useLoad(async () => {
    const [review, waiting, escalated] = await Promise.all([api.queue("review"), api.queue("waiting"), api.queue("escalation")]);
    return [...review.reports, ...waiting.reports, ...escalated.reports].filter((r) => r.ward_zone && !r.assigned_doctor_id);
  }, [], 6000);
  useEffect(() => { if (me.data) setCap(String(me.data.max_capacity)); }, [me.data?.max_capacity, doctorId]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { me.reload(); queues.reload(); doctors.reload(); };
  const run = async (fn, okMsg) => {
    try { const res = await fn(); if (okMsg) toast("success", okMsg); refresh(); return res; } catch (e) { toast("error", e.message); return null; }
  };
  const setStatus = (r, status) => run(() => api.updateStatus(r.report_id, { status, handler_id: doctorId, note: status === "In Progress" ? "Assignment accepted" : "" }), `${r.report_id} marked ${status}`);

  const doc = me.data;
  return (
    <>
      <PageHeader title="Handler desk" sub="Pick a doctor to work as. New assignments appear here the moment they are routed.">
        </PageHeader>
      <div className="chips" role="tablist" aria-label="Sign in as doctor">
        {(doctors.data || []).map((d) => (
          <button key={d.doctor_id} role="tab" aria-selected={doctorId === d.doctor_id} className={`chip ${doctorId === d.doctor_id ? "on" : ""}`} onClick={() => { setDoctorId(d.doctor_id); setSelected(null); }}>
            <i className={`dot ${d.available ? "" : "off"}`} /><span><b>{d.name}</b><small>Zone {d.zone_id} · {d.current_load}/{d.max_capacity}</small></span>
          </button>
        ))}
      </div>
      {doctors.error && <ErrorBox message={doctors.error} onRetry={doctors.reload} />}
      {!doc ? <Spinner /> : (
        <>
          <div className="stats">
            <StatCard label="Active assignments" value={doc.current_load} />
            <StatCard label="Maximum capacity" value={doc.max_capacity} />
            <StatCard label="Free capacity" value={doc.available_capacity} tone={doc.available_capacity === 0 ? "bad" : "ok"} />
            <StatCard label="Availability" value={doc.available ? "Available" : "Unavailable"} tone={doc.available ? "ok" : "bad"} />
          </div>
          <section className="card row between">
            <div className="row">
              <button className={`btn ${doc.available ? "" : "primary"}`} onClick={() => run(() => api.setAvailability(doc.doctor_id, !doc.available), doc.available ? "Marked unavailable" : "Marked available")}>
                {doc.available ? "Set unavailable" : "Set available"}
              </button>
            </div>
            <form className="row" onSubmit={(e) => { e.preventDefault(); run(() => api.setCapacity(doc.doctor_id, Number(cap)), "Capacity updated"); }}>
              <label htmlFor="cap" style={{ margin: 0 }}>Maximum capacity</label>
              <input id="cap" type="number" min="0" max="50" style={{ width: 90 }} value={cap} onChange={(e) => setCap(e.target.value)} />
              <button className="btn primary">Save capacity</button>
            </form>
          </section>
          {selected && <ReportDetail report={selected} onClose={() => setSelected(null)} />}
          <section className="card">
            <h3>My assigned reports</h3>
            {doc.assigned_reports.length === 0 ? <Empty>No open assignments for {doc.name}.</Empty> : (
              <ReportTable reports={doc.assigned_reports} columns={["id", "patient", "category", "zone", "priority", "status", "sla", "submitted"]}
                onRowClick={async (r) => { try { setSelected(await api.report(r.report_id)); } catch (e) { toast("error", e.message); } }}
                actions={(r) => (
                  <div className="btn-row">
                    {r.status === "Assigned" && <button className="btn small primary" onClick={() => setStatus(r, "In Progress")}>Accept</button>}
                    {r.status !== "Resolved" && <button className="btn small" onClick={() => setStatus(r, "Resolved")}>Resolve</button>}
                  </div>
                )} />
            )}
          </section>
          <section className="card">
            <h3>Unassigned reports you can claim</h3>
            <p className="muted">Review-queue, waiting and escalated reports. Claiming needs free capacity.</p>
            {queues.loading && !queues.data ? <Spinner /> : queues.error ? <ErrorBox message={queues.error} onRetry={queues.reload} /> :
              queues.data.length === 0 ? <Empty>Nothing waiting to be claimed.</Empty> : (
                <ReportTable reports={queues.data} columns={["id", "patient", "category", "zone", "priority", "queue", "submitted"]}
                  actions={(r) => <button className="btn small primary" disabled={!doc.available || doc.available_capacity === 0}
                    onClick={() => run(() => api.claim(r.report_id, doc.doctor_id), `${r.report_id} claimed`)}>Claim</button>} />
              )}
          </section>
        </>
      )}
    </>
  );
}
