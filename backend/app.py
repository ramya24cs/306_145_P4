import json
import os
import threading
from flask import Flask, Response, g, jsonify, request

import database as db
import routing as rt
from classification import CATEGORIES, PRIORITY_LABEL, classify
from validation import dfa_run, dfa_validate, diagnose, regex_validate, validate_patient_id, PATIENT_ID_REGEX

STATUSES = ["Pending", "Assigned", "In Progress", "Resolved"]
URGENCIES = ("Normal", "Urgent", "Emergency")
TRANSITIONS = {"Assigned": {"In Progress", "Resolved"}, "In Progress": {"Resolved"}, "Pending": {"Resolved"}}


# ---- real-time push (Server-Sent Events): every successful write bumps a version and wakes all listeners ----
_cv = threading.Condition()
_bus = {"version": 0, "last": {}}


def publish(info):
    with _cv:
        _bus["version"] += 1
        _bus["last"] = {**info, "version": _bus["version"]}
        _cv.notify_all()


class ApiError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "lab_notifier.db")
    db.init_db(app.config["DB_PATH"])

    # ------------------------------------------------------------------ plumbing
    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.after_request
    def cors(resp):  # lets a browser on another origin (e.g. Vite :5173) call the API
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        if request.method in ("POST", "PUT", "DELETE") and resp.status_code < 400 and request.path.startswith("/api/") \
                and not request.path.startswith("/api/validate") and request.path != "/api/classify":
            data = resp.get_json(silent=True) or {}
            rep = data.get("report") if isinstance(data.get("report"), dict) else data
            kind = "submitted" if (request.method == "POST" and request.path == "/api/reports") else "update"
            publish({"kind": kind, "method": request.method, "path": request.path,
                     "report_id": rep.get("report_id"), "category": rep.get("category"),
                     "queue_state": rep.get("queue_state"), "status": rep.get("status")})
        return resp

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify({"error": e.message, **e.extra}), e.status

    @app.errorhandler(404)
    def nf(_e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def na(_e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(Exception)
    def boom(e):
        app.logger.exception(e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError("Request body must be a JSON object", 400)
        return data

    def text(data, key, required=True, maxlen=500):
        v = data.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            if required:
                raise ApiError(f"'{key}' is required", 400, field=key)
            return ""
        if not isinstance(v, str):
            raise ApiError(f"'{key}' must be text", 400, field=key)
        if len(v) > maxlen:
            raise ApiError(f"'{key}' is too long (max {maxlen})", 400, field=key)
        return v.strip()

    # ------------------------------------------------------------------ serializers
    def doctor_dict(c, d):
        load = rt.doctor_load(c, d["doctor_id"])
        return {"doctor_id": d["doctor_id"], "name": d["name"], "zone_id": d["zone_id"], "role": d["role"],
                "available": bool(d["available"]), "max_capacity": d["max_capacity"], "current_load": load,
                "available_capacity": max(0, d["max_capacity"] - load) if d["available"] else 0}

    def report_dict(c, r, detail=False):
        doc = c.execute("SELECT name FROM doctors WHERE doctor_id=?", (r["assigned_doctor_id"],)).fetchone() if r["assigned_doctor_id"] else None
        out = {k: r[k] for k in r.keys()}
        out.update({"assigned_doctor": doc["name"] if doc else None, "priority_label": PRIORITY_LABEL[r["priority"]],
                    "sla_status": rt.sla_status(c, r), "validation_result": r["validation_result"]})
        if detail:
            out["history"] = [dict(x) for x in c.execute("SELECT * FROM report_status_history WHERE report_id=? ORDER BY history_id", (r["report_id"],))]
            out["routing_log"] = [dict(x) for x in c.execute("SELECT * FROM routing_log WHERE report_id=? ORDER BY log_id", (r["report_id"],))]
            out["escalations"] = [dict(x) for x in c.execute("SELECT * FROM escalation_records WHERE report_id=? ORDER BY escalation_id", (r["report_id"],))]
            a = c.execute("SELECT * FROM routing_assignments WHERE report_id=?", (r["report_id"],)).fetchone()
            out["assignment"] = dict(a) if a else None
        return out
        return r

    def sweep():
        c = conn()
        with db.transaction(c):
            rt.sla_sweep(c)

    @app.get("/api/events")
    def events():
        """Server-Sent Events stream. The browser keeps this connection open and refetches data on 'change'."""
        limit = request.args.get("limit", type=int)          # tests: stop after N messages

        def stream():
            sent, seen = 0, _bus["version"]
            yield "retry: 3000\n\n"
            yield f"event: hello\ndata: {json.dumps({'version': seen})}\n\n"
            sent += 1
            while limit is None or sent < limit:
                with _cv:
                    changed = _cv.wait_for(lambda: _bus["version"] != seen, timeout=15 if limit is None else 3)
                    seen, last = _bus["version"], dict(_bus["last"])
                if not changed:
                    if limit is not None:
                        return
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: change\ndata: {json.dumps(last)}\n\n"
                sent += 1
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ health
    @app.get("/api/health")
    def health():
        conn().execute("SELECT 1")
        return jsonify({"status": "ok", "database": "connected", "server_time": db.iso(db.now(conn()))})

    # ------------------------------------------------------------------ validation / classification
    @app.post("/api/validate/patient-id")
    def v_both():
        return jsonify(validate_patient_id(body().get("patient_id")))

    @app.post("/api/validate/dfa")
    def v_dfa():
        pid = body().get("patient_id")
        acc, state, trace, _ = dfa_run(pid) if isinstance(pid, str) else (False, "q_dead", [], 0)
        return jsonify({"method": "DFA", "valid": acc, "final_state": state, "trace": trace,
                        "errors": [] if acc else diagnose(pid)})

    @app.post("/api/validate/regex")
    def v_regex():
        pid = body().get("patient_id")
        ok = regex_validate(pid)
        return jsonify({"method": "Regex", "pattern": PATIENT_ID_REGEX.pattern, "valid": ok,
                        "errors": [] if ok else diagnose(pid)})

    @app.post("/api/classify")
    def classify_ep():
        return jsonify(classify(body().get("report_code")))

    # ------------------------------------------------------------------ reports
    @app.post("/api/reports")
    def submit():
        data = body()
        pid = data.get("patient_id")
        v = validate_patient_id(pid)
        if not v["agree"]:
            raise ApiError("Internal validator disagreement (DFA vs regex)", 500, validation=v)
        if not v["valid"]:
            raise ApiError("Invalid patient identifier - report rejected before dispatch", 422,
                           validation=v, errors=v["errors"])

        # Category, urgency and ward zone are derived on the server from report_code.
        code = text(data, "report_code").upper()
        cls = classify(code)
        if not cls["recognised"]:
            raise ApiError(cls["reason"], 400, classification=cls)

        zone = cls["ward_zone"]
        urgency = cls["urgency"]
        name = text(data, "reporter_name", maxlen=100)
        contact = text(data, "reporter_contact", maxlen=100)
        desc = text(data, "description", required=False, maxlen=2000)

        c = conn()
        with db.transaction(c):
            dup = c.execute(
                "SELECT report_id FROM reports WHERE patient_id=? AND report_code=? AND ward_zone=? AND status!='Resolved'",
                (pid, cls["report_code"], zone)
            ).fetchone()
            if dup:
                raise ApiError(
                    f"Duplicate report: an unresolved report for this patient, code and ward already exists ({dup['report_id']})",
                    409,
                    existing_report_id=dup["report_id"]
                )

            rid = db.next_report_id(c)
            t = db.iso(db.now(c))
            c.execute(
                """INSERT INTO reports(report_id,patient_id,report_code,category,priority,validation_result,ward_zone,
                   reporter_name,reporter_contact,description,urgency,status,queue_state,submitted_at,status_updated_at,sla_deadline)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'Pending','Waiting',?,?,?)""",
                (
                    rid, pid, cls["report_code"], cls["category"], cls["priority"],
                    "VALID (DFA=accept, Regex=accept)", zone, name, contact, desc,
                    urgency, t, t, rt.sla_deadline(c, cls["category"])
                )
            )
            rt.record_status(c, rid, None, "Pending", name, "Report submitted")
            rt.log(c, rid, "SUBMITTED",
                   f"{cls['category']} ({urgency}), Zone {zone}")
            row = rt.dispatch(c, rid)

        return jsonify({
            "message": "Report submitted",
            "report": report_dict(c, row, True),
            "validation": v,
            "classification": cls
        }), 201

    @app.get("/api/reports")
    def list_reports():
        sweep()
        c = conn()
        sql, args = "SELECT * FROM reports WHERE 1=1", []
        for col, key in (("status", "status"), ("category", "category"), ("ward_zone", "zone"),
                         ("queue_state", "queue_state"), ("assigned_doctor_id", "doctor_id")):
            v = request.args.get(key)
            if v:
                sql += f" AND {col}=?"
                args.append(v)
        q = request.args.get("q")
        if q:
            sql += " AND (report_id LIKE ? OR patient_id LIKE ?)"
            args += [f"%{q.strip()}%"] * 2
        sql += " ORDER BY priority, submitted_at, report_id" if request.args.get("sort") == "priority" else " ORDER BY submitted_at DESC, report_id DESC"
        rows = c.execute(sql, args).fetchall()
        return jsonify({"count": len(rows), "reports": [report_dict(c, r) for r in rows]})

    @app.get("/api/reports/<rid>")
    def one_report(rid):
        sweep()
        c = conn()
        return jsonify(report_dict(c, get_report(c, rid.upper()), True))

    @app.put("/api/reports/<rid>/status")
    def update_status(rid):
        data, rid = body(), rid.upper()
        new = data.get("status")
        if new not in STATUSES:
            raise ApiError(f"'status' must be one of {STATUSES}", 400, field="status")
        role = data.get("role", "handler")
        note = text(data, "note", required=False, maxlen=300)
        c = conn()
        with db.transaction(c):
            r = get_report(c, rid)
            admin = role == "admin"
            if not admin and (data.get("handler_id") is None or r["assigned_doctor_id"] != int(data["handler_id"])):
                raise ApiError("Not authorised: only the assigned doctor or an administrator can update this report", 403)
            if new not in TRANSITIONS.get(r["status"], set()):
                raise ApiError(f"Invalid transition {r['status']} -> {new}", 409)
            if r["status"] == "Pending" and not admin:
                raise ApiError("Only an administrator can resolve an unassigned report", 403)
            t = db.iso(db.now(c))
            queue = "Closed" if new == "Resolved" else r["queue_state"]
            c.execute("UPDATE reports SET status=?, status_updated_at=?, queue_state=? WHERE report_id=?", (new, t, queue, rid))
            rt.record_status(c, rid, r["status"], new, "admin" if admin else f"doctor:{data.get('handler_id')}", note)
            rt.log(c, rid, f"STATUS_{new.upper().replace(' ', '_')}", note or f"{r['status']} -> {new}")
            promoted = []
            if new == "Resolved":
                c.execute("UPDATE escalation_records SET resolved_at=? WHERE report_id=? AND resolved_at IS NULL", (t, rid))
                promoted = rt.promote_waiting(c)
        return jsonify({"report": report_dict(c, get_report(c, rid), True), "promoted_from_queue": promoted})

    @app.post("/api/reports/<rid>/claim")
    def claim(rid):
        data, rid = body(), rid.upper()
        c = conn()
        with db.transaction(c):
            r = get_report(c, rid)
            doc = c.execute("SELECT * FROM doctors WHERE doctor_id=?", (data.get("handler_id"),)).fetchone()
            if not doc:
                raise ApiError("Unknown handler", 404)
            if r["queue_state"] not in ("Review", "Waiting", "Escalated") or r["assigned_doctor_id"]:
                raise ApiError("Report is not claimable (already assigned or closed)", 409)
            ok, why = rt.eligible(c, doc)
            if not ok:
                raise ApiError(f"{doc['name']} is {why}", 409)
            t = db.iso(db.now(c))
            n = c.execute("UPDATE reports SET assigned_doctor_id=?, status='Assigned', queue_state='Assigned', assigned_at=?, status_updated_at=?, "
                          "routing_decision=? WHERE report_id=? AND assigned_doctor_id IS NULL",
                          (doc["doctor_id"], t, t, f"Claimed manually by {doc['name']}", rid)).rowcount
            if n != 1:
                raise ApiError("Report was assigned by someone else", 409)
            c.execute("INSERT INTO routing_assignments(report_id,doctor_id,assignment_type,assigned_at) VALUES (?,?,?,?)", (rid, doc["doctor_id"], "Manual", t))
            c.execute("UPDATE escalation_records SET resolved_at=? WHERE report_id=? AND resolved_at IS NULL", (t, rid))
            rt.record_status(c, rid, r["status"], "Assigned", f"doctor:{doc['doctor_id']}", "Claimed from queue")
            rt.log(c, rid, "ASSIGNED_MANUAL", f"Claimed by {doc['name']}")
        return jsonify(report_dict(c, get_report(c, rid), True))

    @app.put("/api/reports/<rid>/zone")
    def fix_zone(rid):
        """Administrator corrects an unknown zone; the report is re-dispatched."""
        data, rid = body(), rid.upper()
        zone = text(data, "ward_zone").upper()
        if zone not in rt.VALID_ZONES:
            raise ApiError(f"ward_zone must be one of {list(rt.VALID_ZONES)}", 400, field="ward_zone")
        c = conn()
        with db.transaction(c):
            r = get_report(c, rid)
            if r["assigned_doctor_id"] or r["status"] == "Resolved":
                raise ApiError("Only unassigned, open reports can be re-zoned", 409)
            c.execute("UPDATE reports SET ward_zone=?, queue_state='Waiting' WHERE report_id=?", (zone, rid))
            c.execute("UPDATE escalation_records SET resolved_at=? WHERE report_id=? AND resolved_at IS NULL", (db.iso(db.now(c)), rid))
            rt.log(c, rid, "ZONE_CORRECTED", f"{r['ward_zone']} -> {zone}; re-dispatching")
            row = rt.dispatch(c, rid)
        return jsonify(report_dict(c, row, True))

    @app.delete("/api/reports/<rid>")
    def delete_report(rid):
        rid, c = rid.upper(), conn()
        with db.transaction(c):
            r = get_report(c, rid)
            if r["status"] != "Resolved":
                raise ApiError("Only Resolved reports can be deleted", 409)
            c.execute("DELETE FROM reports WHERE report_id=?", (rid,))
        return jsonify({"deleted": rid})

    # ------------------------------------------------------------------ doctors
    @app.get("/api/doctors")
    def doctors():
        c = conn()
        return jsonify([doctor_dict(c, d) for d in c.execute("SELECT * FROM doctors ORDER BY zone_id, role DESC")])

    @app.get("/api/doctors/<int:did>")
    def doctor(did):
        c = conn()
        d = c.execute("SELECT * FROM doctors WHERE doctor_id=?", (did,)).fetchone()
        if not d:
            raise ApiError("Doctor not found", 404)
        out = doctor_dict(c, d)
        out["assigned_reports"] = [report_dict(c, r) for r in c.execute(
            "SELECT * FROM reports WHERE assigned_doctor_id=? AND status!='Resolved' ORDER BY priority, submitted_at, report_id", (did,))]
        return jsonify(out)

    @app.put("/api/doctors/<int:did>/availability")
    def set_availability(did):
        flag = body().get("available")
        if not isinstance(flag, bool):
            raise ApiError("'available' must be true or false", 400, field="available")
        c = conn()
        with db.transaction(c):
            if not c.execute("SELECT 1 FROM doctors WHERE doctor_id=?", (did,)).fetchone():
                raise ApiError("Doctor not found", 404)
            c.execute("UPDATE doctors SET available=? WHERE doctor_id=?", (int(flag), did))
            promoted = rt.promote_waiting(c) if flag else []
        return jsonify({"doctor": doctor_dict(c, c.execute("SELECT * FROM doctors WHERE doctor_id=?", (did,)).fetchone()), "promoted_from_queue": promoted})

    @app.put("/api/doctors/<int:did>/capacity")
    def set_capacity(did):
        cap = body().get("max_capacity")
        if isinstance(cap, bool) or not isinstance(cap, int) or not 0 <= cap <= 50:
            raise ApiError("'max_capacity' must be an integer between 0 and 50", 400, field="max_capacity")
        c = conn()
        with db.transaction(c):
            if not c.execute("SELECT 1 FROM doctors WHERE doctor_id=?", (did,)).fetchone():
                raise ApiError("Doctor not found", 404)
            c.execute("UPDATE doctors SET max_capacity=? WHERE doctor_id=?", (cap, did))
            promoted = rt.promote_waiting(c)
        return jsonify({"doctor": doctor_dict(c, c.execute("SELECT * FROM doctors WHERE doctor_id=?", (did,)).fetchone()), "promoted_from_queue": promoted})

    # ------------------------------------------------------------------ routing & queues
    def queue_rows(c, state):
        rows = c.execute("SELECT * FROM reports WHERE queue_state=? ORDER BY priority, submitted_at, report_id", (state,)).fetchall()
        out = []
        for i, r in enumerate(rows, 1):
            d = report_dict(c, r)
            d["queue_position"] = i
            out.append(d)
        return out

    @app.get("/api/queues/<name>")
    def queue(name):
        states = {"waiting": "Waiting", "escalation": "Escalated", "review": "Review", "error": "Error"}
        if name not in states:
            raise ApiError(f"Unknown queue. Use one of {list(states)}", 404)
        sweep()
        c = conn()
        rows = queue_rows(c, states[name])
        return jsonify({"queue": name, "count": len(rows), "reports": rows})

    @app.get("/api/routing/table")
    def routing_table():
        sweep()
        c = conn()
        zones = []
        for z in c.execute("SELECT * FROM ward_zones ORDER BY zone_id"):
            docs = {d["role"]: doctor_dict(c, d) for d in rt.routing_lookup(c, z["zone_id"])}
            zones.append({"zone_id": z["zone_id"], "name": z["name"], "primary": docs.get("Primary"), "backup": docs.get("Backup"),
                          "waiting": c.execute("SELECT COUNT(*) FROM reports WHERE ward_zone=? AND queue_state='Waiting'", (z["zone_id"],)).fetchone()[0]})
        overrides = []
        for r in c.execute("SELECT * FROM reports WHERE category IN ('Critical','Stat') AND status!='Resolved' ORDER BY priority, submitted_at, report_id"):
            d = report_dict(c, r)
            d["jumped_ahead_of"] = c.execute(
                "SELECT COUNT(*) FROM reports WHERE queue_state='Waiting' AND priority>? AND submitted_at<? AND report_id!=?",
                (r["priority"], r["submitted_at"], r["report_id"])).fetchone()[0] if r["queue_state"] == "Waiting" else 0
            overrides.append(d)
        history = [dict(x) for x in c.execute("SELECT * FROM routing_log ORDER BY log_id DESC LIMIT 60")]
        return jsonify({"zones": zones, "waiting": queue_rows(c, "Waiting"), "escalated": queue_rows(c, "Escalated"),
                        "priority_overrides": overrides, "history": history,
                        "clock": db.iso(db.now(c)), "sla_minutes": rt.SLA_MINUTES})

    @app.post("/api/simulation/advance")
    def advance():
        minutes = body().get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 1440:
            raise ApiError("'minutes' must be an integer between 1 and 1440", 400)
        c = conn()
        with db.transaction(c):
            c.execute("UPDATE settings SET value = CAST(value AS INTEGER) + ? WHERE key='clock_offset_minutes'", (minutes,))
            escalated = rt.sla_sweep(c)
        return jsonify({"advanced_minutes": minutes, "clock": db.iso(db.now(c)), "escalated_by_sla": escalated})

    # ------------------------------------------------------------------ analytics
    @app.get("/api/analytics")
    def analytics():
        sweep()
        c = conn()
        q = lambda sql, *a: c.execute(sql, a).fetchall()
        total = q("SELECT COUNT(*) FROM reports")[0][0]
        status_counts = {s: 0 for s in STATUSES}
        for r in q("SELECT status, COUNT(*) n FROM reports GROUP BY status"):
            status_counts[r["status"]] = r["n"]
        zone = {z: 0 for z in "ABCD"}
        zone["Unknown"] = 0
        for r in q("SELECT ward_zone, COUNT(*) n FROM reports GROUP BY ward_zone"):
            zone[r["ward_zone"] if r["ward_zone"] in zone else "Unknown"] += r["n"]
        cat = {k: 0 for k in CATEGORIES}
        for r in q("SELECT category, COUNT(*) n FROM reports GROUP BY category"):
            cat[r["category"]] = r["n"]
        pri = {PRIORITY_LABEL[p] + f" (P{p})": 0 for p in range(1, 6)}
        for r in q("SELECT priority, COUNT(*) n FROM reports GROUP BY priority"):
            pri[PRIORITY_LABEL[r["priority"]] + f" (P{r['priority']})"] = r["n"]
        avg = c.execute("SELECT AVG((julianday(assigned_at)-julianday(submitted_at))*1440) FROM reports WHERE assigned_at IS NOT NULL").fetchone()[0]
        return jsonify({
            "summary": {"total": total, "resolved": status_counts["Resolved"], "unresolved": total - status_counts["Resolved"],
                        "waiting": q("SELECT COUNT(*) FROM reports WHERE queue_state='Waiting'")[0][0],
                        "escalated": q("SELECT COUNT(*) FROM reports WHERE queue_state='Escalated'")[0][0],
                        "errors": cat["Error"],
                        "sla_breached": sum(1 for r in q("SELECT * FROM reports WHERE sla_deadline IS NOT NULL") if rt.sla_status(c, r) == "Breached"),
                        "avg_assignment_minutes": round(avg, 2) if avg is not None else None},
            "status_counts": status_counts,
            "zone_distribution": [{"name": k if k == "Unknown" else f"Zone {k}", "value": v} for k, v in zone.items()],
            "category_distribution": [{"name": k, "value": v} for k, v in cat.items()],
            "priority_distribution": [{"name": k, "value": v} for k, v in pri.items()],
            "resolution": [{"name": "Resolved", "value": status_counts["Resolved"]}, {"name": "Unresolved", "value": total - status_counts["Resolved"]}],
            "doctor_workload": [{"name": d["name"], "load": d["current_load"], "capacity": d["max_capacity"]}
                                for d in (doctor_dict(c, x) for x in c.execute("SELECT * FROM doctors ORDER BY zone_id, role DESC"))],
        })

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False, threaded=True)
