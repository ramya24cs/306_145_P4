import { useEffect, useState } from "react";
import { api } from "../api.js";
import { CategoryBadge, PageHeader, Segmented, SlaBadge, StatusBadge, useToast } from "../ui.jsx";

const ZONES = [["A", "Zone A"], ["B", "Zone B"], ["C", "Zone C"], ["D", "Zone D"], ["X", "Unlisted"]];
const URGENCY = [["Normal", "Normal"], ["Urgent", "Urgent"], ["Emergency", "Emergency"]];

function previewRoute(cls, zone) {
  if (!cls) return "Enter a report code to preview where this report will go.";
  if (cls.category === "Error") return "Error queue: the code is not supported, so no doctor is assigned.";
  if (zone === "X") return "Central escalation queue: this ward zone has no routing-table entry.";
  if (cls.category === "Pending") return `Review queue for Zone ${zone}.`;
  return `Ward duty doctor in Zone ${zone}: primary, then backup, then the waiting queue.${cls.sla_applies ? " The 15-minute SLA starts at submission." : ""}`;
}
const EMPTY = { patient_id: "", report_code: "", ward_zone: "A", reporter_name: "", reporter_contact: "", description: "", urgency: "Normal" };

function Trace({ trace }) {
  return (
    <div className="trace" aria-label="DFA state trace">
      {trace.map((t, i) => (
        <span key={i} className={t.state === "q_dead" ? "dead" : t.state === "q15" ? "acc" : ""}>{t.symbol ? `${t.symbol}→` : ""}{t.state}</span>
      ))}
    </div>
  );
}

export default function SubmitReport() {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY);
  const [touched, setTouched] = useState(false);
  const [validation, setValidation] = useState(null);
  const [cls, setCls] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [serverErrors, setServerErrors] = useState([]);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  // Live DFA + regex validation (debounced calls to Flask)
  useEffect(() => {
    if (!touched) { setValidation(null); return undefined; }
    const t = setTimeout(() => api.validate(form.patient_id).then(setValidation).catch((e) => toast("error", e.message)), 250);
    return () => clearTimeout(t);
  }, [form.patient_id, touched]); // eslint-disable-line react-hooks/exhaustive-deps

  // Live classification
  useEffect(() => {
    if (!form.report_code.trim()) { setCls(null); return undefined; }
    const t = setTimeout(() => api.classify(form.report_code).then(setCls).catch((e) => toast("error", e.message)), 250);
    return () => clearTimeout(t);
  }, [form.report_code]); // eslint-disable-line react-hooks/exhaustive-deps

  const complete = form.report_code.trim() && form.reporter_name.trim() && form.reporter_contact.trim();
  const canSubmit = validation?.valid && complete && !busy;

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setServerErrors([]); setResult(null);
    try {
      const res = await api.submitReport(form);
      setResult(res);
      toast("success", `Report ${res.report.report_id} submitted`);
      setForm(EMPTY); setTouched(false); setValidation(null); setCls(null);
    } catch (err) {
      setServerErrors(err.data?.errors || [err.message]);
      if (err.data?.validation) setValidation(err.data.validation);
      toast("error", err.message);
    } finally { setBusy(false); }
  }

  const idState = !touched ? "" : validation ? (validation.valid ? "valid" : "invalid") : "";
  return (
    <>
      <PageHeader title="Submit a lab report" sub="The patient ID is checked by a DFA and a regex, then the report code is classified before dispatch." />
      <div className="pipeline">
        <div className={`pipe ${!validation ? "" : validation.valid ? "ok" : "bad"}`}><i>{validation ? (validation.valid ? "✓" : "!") : "1"}</i>Patient ID</div>
        <div className={`pipe ${!cls ? "" : cls.recognised ? "ok" : "bad"}`}><i>{cls ? (cls.recognised ? "✓" : "!") : "2"}</i>Classified</div>
        <div className={`pipe ${form.ward_zone === "X" ? "bad" : "ok"}`}><i>{form.ward_zone === "X" ? "!" : "✓"}</i>Ward zone</div>
        <div className={`pipe ${canSubmit ? "ok" : ""}`}><i>{canSubmit ? "✓" : "4"}</i>Ready to dispatch</div>
      </div>
      <div className="grid g2">
        <form className="card" onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="pid">Patient ID</label>
            <input id="pid" className={idState} value={form.patient_id} placeholder="PAT123456-LABHR" autoComplete="off"
              onChange={(e) => { setTouched(true); set("patient_id")(e); }} onBlur={() => setTouched(true)} />
            {validation && !validation.valid && validation.errors.map((m, i) => <div key={i} className="field-error">{m}</div>)}
            {!touched && <div className="hint">Format: PAT + 6 digits + hyphen + LAB + 2 capital letters.</div>}
          </div>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="code">Report code</label>
              <input id="code" value={form.report_code} onChange={set("report_code")} placeholder="CRIT, STAT, ROUT or PEND" autoComplete="off" />
            </div>
            <div className="field">
              <label>Ward zone</label>
              <Segmented label="Ward zone" options={ZONES} value={form.ward_zone} onChange={(v) => setForm({ ...form, ward_zone: v })} />
            </div>
            <div className="field">
              <label htmlFor="rn">Reporter name</label>
              <input id="rn" value={form.reporter_name} onChange={set("reporter_name")} maxLength={100} />
            </div>
            <div className="field">
              <label htmlFor="rc">Reporter contact</label>
              <input id="rc" value={form.reporter_contact} onChange={set("reporter_contact")} placeholder="Phone or email" maxLength={100} />
            </div>
          </div>
          <div className="field">
            <label>Urgency</label>
            <Segmented label="Urgency" options={URGENCY} value={form.urgency} onChange={(v) => setForm({ ...form, urgency: v })} />
          </div>
          <div className="field">
            <label htmlFor="desc">Report description</label>
            <textarea id="desc" rows={3} value={form.description} onChange={set("description")} maxLength={2000} />
          </div>
          {serverErrors.length > 0 && <div className="alert error"><div>{serverErrors.map((m, i) => <div key={i}>{m}</div>)}</div></div>}
          <button className="btn primary big" disabled={!canSubmit}>{busy ? "Submitting…" : "Submit report"}</button>
          {!canSubmit && !busy && <span className="hint"> {validation?.valid ? "Fill in all required fields." : "Enter a valid patient ID to enable submission."}</span>}
        </form>

        <div>
          <section className="card">
            <h3>Patient ID validation</h3>
            {!validation ? <p className="muted">Start typing a patient ID to see both validators run.</p> : (
              <div className="grid">
                <div className="check-box">
                  <h4>DFA <span className={validation.dfa.valid ? "pill-ok" : "pill-bad"}>{validation.dfa.valid ? "Accepted" : "Rejected"}</span></h4>
                  <div className="muted">Final state: {validation.dfa.final_state} (accepting: {validation.dfa.accepting_states.join(", ")})</div>
                  <Trace trace={validation.dfa.trace} />
                </div>
                <div className="check-box">
                  <h4>Regex <span className={validation.regex.valid ? "pill-ok" : "pill-bad"}>{validation.regex.valid ? "Accepted" : "Rejected"}</span></h4>
                  <code>{validation.regex.pattern}</code>
                </div>
                <div className={`alert ${validation.agree ? "ok" : "error"}`}>{validation.agree ? "DFA and regex agree." : "DFA and regex disagree."}</div>
              </div>
            )}
          </section>
          <section className="card">
            <h3>Detected category</h3>
            {!cls ? <p className="muted">Enter a report code to see its category and priority.</p> : (
              <dl className="kv">
                <dt>Category</dt><dd><CategoryBadge category={cls.category} /></dd>
                <dt>Priority</dt><dd>P{cls.priority} - {cls.priority_label}</dd>
                <dt>Routing rule</dt><dd>{cls.route}</dd>
                <dt>15-minute SLA</dt><dd>{cls.sla_applies ? "Applies" : "Not applicable"}</dd>
                <dt>Note</dt><dd>{cls.reason}</dd>
              </dl>
            )}
            <div className="route-preview"><b>Dispatch preview.</b> {previewRoute(cls, form.ward_zone)}</div>
            {cls && !cls.recognised && <div className="alert warn" style={{ marginTop: 12 }}>This code is not supported. The report will go to the Error queue instead of a doctor.</div>}
          </section>
          {result && (
            <section className="card">
              <h3>Report submitted</h3>
              <dl className="kv">
                <dt>Report ID</dt><dd><strong>{result.report.report_id}</strong></dd>
                <dt>Category</dt><dd><CategoryBadge category={result.report.category} /> priority P{result.report.priority}</dd>
                <dt>Status</dt><dd><StatusBadge status={result.report.status} /></dd>
                <dt>Routing result</dt><dd>{result.report.routing_decision}</dd>
                <dt>Queue</dt><dd>{result.report.queue_state}</dd>
                {result.report.escalation_reason && (<><dt>Escalation reason</dt><dd>{result.report.escalation_reason}</dd></>)}
                <dt>SLA</dt><dd><SlaBadge sla={result.report.sla_status} /></dd>
              </dl>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
