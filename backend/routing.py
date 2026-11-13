"""Routing & dispatch engine (BCS502 side: server-side processing behind the REST API).

All functions expect to be called INSIDE a database transaction (see database.transaction).
"""
from datetime import timedelta
from classification import SLA_CATEGORIES
from database import iso, now, parse_iso

SLA_MINUTES = 15
VALID_ZONES = ("A", "B", "C", "D")
ACTIVE = ("Assigned", "In Progress")


def queue_sort_key(priority, submitted_at, report_id):
    """Priority first (1 = Critical), then FIFO by timestamp, then report ID as tie-breaker."""
    return (priority, submitted_at, report_id)


def log(conn, report_id, decision, detail=""):
    conn.execute("INSERT INTO routing_log(report_id,decision,detail,created_at) VALUES (?,?,?,?)",
                 (report_id, decision, detail, iso(now(conn))))


def doctor_load(conn, doctor_id) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM reports WHERE assigned_doctor_id=? AND status IN ('Assigned','In Progress')",
        (doctor_id,)).fetchone()[0]


def routing_lookup(conn, zone):
    """Routing-table lookup: zone -> [primary, backup]."""
    return conn.execute(
        "SELECT * FROM doctors WHERE zone_id=? ORDER BY CASE role WHEN 'Primary' THEN 0 ELSE 1 END", (zone,)
    ).fetchall()


def eligible(conn, doc):
    """Availability + capacity check."""
    if not doc["available"]:
        return False, "unavailable"
    if doctor_load(conn, doc["doctor_id"]) >= doc["max_capacity"]:
        return False, "at capacity"
    return True, "ok"


def record_status(conn, report_id, old, new, by, note=""):
    conn.execute("INSERT INTO report_status_history(report_id,old_status,new_status,changed_by,note,changed_at) VALUES (?,?,?,?,?,?)",
                 (report_id, old, new, by, note, iso(now(conn))))


def escalate(conn, report_id, reason):
    t = iso(now(conn))
    conn.execute("UPDATE reports SET queue_state='Escalated', escalation_reason=?, routing_decision=?, status_updated_at=? WHERE report_id=?",
                 (reason, f"Central Escalation Queue: {reason}", t, report_id))
    conn.execute("INSERT INTO escalation_records(report_id,reason,created_at) VALUES (?,?,?)", (report_id, reason, t))
    log(conn, report_id, "ESCALATED", reason)


def try_assign(conn, report) -> bool:
    """Primary first, then backup. The guarded UPDATE + UNIQUE(report_id) make duplicate
    assignment impossible even under concurrency."""
    rid, zone = report["report_id"], report["ward_zone"]
    notes = []
    for doc in routing_lookup(conn, zone):
        ok, why = eligible(conn, doc)
        if not ok:
            notes.append(f"{doc['role']} {doc['name']} {why}")
            continue
        t = iso(now(conn))
        changed = conn.execute(
            "UPDATE reports SET assigned_doctor_id=?, status='Assigned', queue_state='Assigned', assigned_at=?, "
            "status_updated_at=?, escalation_reason=NULL, routing_decision=? "
            "WHERE report_id=? AND assigned_doctor_id IS NULL AND status!='Resolved'",
            (doc["doctor_id"], t, t,
             f"Assigned to {doc['role'].lower()} doctor {doc['name']} (Zone {zone})"
             + (f" - {'; '.join(notes)}" if notes else ""), rid)).rowcount
        if changed != 1:
            return False  # someone else already assigned it
        conn.execute("INSERT INTO routing_assignments(report_id,doctor_id,assignment_type,assigned_at) VALUES (?,?,?,?)",
                     (rid, doc["doctor_id"], doc["role"], t))
        conn.execute("UPDATE escalation_records SET resolved_at=? WHERE report_id=? AND resolved_at IS NULL", (t, rid))
        record_status(conn, rid, report["status"], "Assigned", "system", f"{doc['role']} assignment: {doc['name']}")
        log(conn, rid, f"ASSIGNED_{doc['role'].upper()}", f"{doc['name']} (load now {doctor_load(conn, doc['doctor_id'])}/{doc['max_capacity']})"
            + (f"; skipped: {'; '.join(notes)}" if notes else ""))
        return True
    report_note = "; ".join(notes) or "no doctor configured"
    conn.execute("UPDATE reports SET routing_decision=? WHERE report_id=?",
                 (f"No doctor free in Zone {zone} ({report_note})", rid))
    return False


def dispatch(conn, rid):
    """Route one freshly validated report. Returns the refreshed row."""
    r = conn.execute("SELECT * FROM reports WHERE report_id=?", (rid,)).fetchone()
    cat, zone = r["category"], r["ward_zone"]

    if cat == "Error":
        conn.execute("UPDATE reports SET queue_state='Error', routing_decision='Error Queue: unknown/unsupported report code' WHERE report_id=?", (rid,))
        log(conn, rid, "ERROR_QUEUE", "Unsupported report code - needs manual correction")
    elif zone not in VALID_ZONES:                                   # exceptional scenario A
        escalate(conn, rid, f"Unknown ward zone '{zone}' - no routing-table entry")
    elif cat == "Pending":
        conn.execute("UPDATE reports SET queue_state='Review', routing_decision=? WHERE report_id=?",
                     (f"Review Queue (Zone {zone})", rid))
        log(conn, rid, "REVIEW_QUEUE", "Pending report held for review")
    else:                                                           # Critical / Stat / Routine
        lane = "Ward duty doctor" if cat in SLA_CATEGORIES else "Standard queue"
        log(conn, rid, "ROUTING_LOOKUP", f"{cat} -> {lane}; Zone {zone} table checked")
        if not try_assign(conn, r):
            t = iso(now(conn))
            conn.execute("UPDATE reports SET queue_state='Waiting', routing_decision=? WHERE report_id=?",
                         (f"Waiting queue: primary and backup unavailable in Zone {zone}", rid))
            log(conn, rid, "WAITING_QUEUE", f"Primary and backup unavailable in Zone {zone}")
    return conn.execute("SELECT * FROM reports WHERE report_id=?", (rid,)).fetchone()


def promote_waiting(conn):
    """Called whenever capacity may have freed up. Walks the waiting + escalated (known zone)
    queues in strict priority / FIFO / report-ID order."""
    rows = conn.execute(
        "SELECT * FROM reports WHERE queue_state IN ('Waiting','Escalated') AND assigned_doctor_id IS NULL "
        "AND category IN ('Critical','Stat','Routine') AND ward_zone IN ('A','B','C','D')").fetchall()
    rows = sorted(rows, key=lambda r: queue_sort_key(r["priority"], r["submitted_at"], r["report_id"]))
    promoted = []
    for r in rows:
        if try_assign(conn, r):
            promoted.append(r["report_id"])
    return promoted


def sla_sweep(conn):
    """Escalate Critical/Stat reports still unassigned after the 15-minute SLA."""
    t = iso(now(conn))
    rows = conn.execute(
        "SELECT report_id FROM reports WHERE queue_state='Waiting' AND sla_deadline IS NOT NULL AND sla_deadline < ?", (t,)).fetchall()
    for r in rows:
        escalate(conn, r["report_id"], f"SLA breach: not assigned within {SLA_MINUTES} minutes")
    return [r["report_id"] for r in rows]


def sla_deadline(conn, category):
    return iso(now(conn) + timedelta(minutes=SLA_MINUTES)) if category in SLA_CATEGORIES else None


def sla_status(conn, row):
    if not row["sla_deadline"]:
        return "N/A"
    deadline = parse_iso(row["sla_deadline"])
    if row["assigned_at"]:
        return "Met" if parse_iso(row["assigned_at"]) <= deadline else "Breached"
    return "Breached" if now(conn) > deadline else "Running"
