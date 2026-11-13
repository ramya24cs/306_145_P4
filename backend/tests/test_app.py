"""Automated tests (stdlib unittest - no extra packages needed).
Run from /backend:   python run_tests.py      (also works with:  python -m unittest discover -v)
Each test records  input / expected / actual  rows that run_tests.py writes to docs/TEST_RESULTS.md.
"""
import os, random, sqlite3, string, tempfile, threading, unittest

from app import create_app
import database as db
import routing as rt
from classification import classify
from validation import dfa_validate, regex_validate, validate_patient_id

RECORDS = []
_counter = iter(range(1, 10_000))


def pid():
    return f"PAT{next(_counter):06d}-LABHR"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "test.db")
        self.app = create_app(self.path)
        self.c = self.app.test_client()

    def submit(self, code="ROUT", zone="A", patient=None, **kw):
        body = dict(patient_id=patient or pid(), report_code=code, ward_zone=zone, reporter_name="Tech One",
                    reporter_contact="9999999999", description="CBC panel", urgency="Normal")
        body.update(kw)
        return self.c.post("/api/reports", json=body)

    def doctor_id(self, name):
        return self.c.application.test_client().get("/api/doctors").json and next(
            d["doctor_id"] for d in self.c.get("/api/doctors").json if d["name"] == name)

    def check(self, case, inputs, expected, actual):
        RECORDS.append({"case": case, "input": inputs, "expected": str(expected), "actual": str(actual),
                        "result": "PASS" if expected == actual else "FAIL"})
        self.assertEqual(expected, actual, case)


class TestValidation(Base):
    def test_01_valid_identifier(self):
        r = validate_patient_id("PAT123456-LABHR")
        self.check("1. Valid patient identifier", "PAT123456-LABHR", "DFA=True, Regex=True, agree",
                   f"DFA={r['dfa']['valid']}, Regex={r['regex']['valid']}, {'agree' if r['agree'] else 'DISAGREE'}")

    def test_02_invalid_identifiers(self):
        cases = {"": "empty", "PAT12345-LABHR": "digit count", "PAT1234567-LABHR": "digit count", "PAT123456LABHR": "hyphen",
                 "XYZ123456-LABHR": "prefix", "PAT12A456-LABHR": "Invalid character", "PAT123456-LABhr": "suffix",
                 "PAT123456-LAB12": "suffix", "PAT123456-LABHRX": "too long", "PAT123456-ABCHR": "lab prefix"}
        got = {}
        for text, word in cases.items():
            r = validate_patient_id(text)
            self.assertFalse(r["valid"], text)
            self.assertTrue(any(word.lower() in e.lower() for e in r["errors"]), f"{text!r}: {r['errors']}")
            got[text] = "rejected + message mentions '%s'" % word
        self.check("2. Invalid patient identifiers (empty, digits, hyphen, prefix, chars, suffix)", "10 malformed IDs",
                   {k: "rejected + message mentions '%s'" % v for k, v in cases.items()}, got)

    def test_03_incomplete_identifier(self):
        r = validate_patient_id("PAT1234")
        self.check("3. Incomplete identifier", "PAT1234", "invalid, 'Incomplete identifier' error",
                   f"{'invalid' if not r['valid'] else 'valid'}, '{r['errors'][0].split(':')[0]}' error")

    def test_04_dfa_regex_agreement(self):
        rng = random.Random(7)
        alphabet = "PATLB-0123456789ABCXYZabc \n"
        samples = ["PAT123456-LABHR", "PAT123456-LABHR\n", "PAT١٢٣٤٥٦-LABHR", "pat123456-labhr", ""]
        for _ in range(4000):
            samples.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 17))))
        for _ in range(2000):  # mutate a valid ID
            s = list("PAT123456-LABHR")
            s[rng.randrange(15)] = rng.choice(alphabet)
            samples.append("".join(s))
        mismatches = [s for s in samples if dfa_validate(s) != regex_validate(s)]
        self.check("4. DFA and regex agreement", f"{len(samples)} random/mutated strings incl. trailing newline & Unicode digits",
                   "0 mismatches", f"{len(mismatches)} mismatches")


class TestClassification(Base):
    def test_05_to_09_classification(self):
        for n, code, exp in [(5, "CRIT", "Critical"), (6, "STAT", "Stat"), (7, "ROUT", "Routine"), (8, "PEND", "Pending"), (9, "XYZ9", "Error")]:
            r = classify(code)
            self.check(f"{n}. Classification of {code}", code, f"{exp} (priority {1 + ['Critical','Stat','Routine','Pending','Error'].index(exp)})",
                       f"{r['category']} (priority {r['priority']})")

    def test_multiple_patterns_priority(self):
        self.check("Extra: multiple matching codes use priority Critical>Stat>Routine>Pending>Error", "ROUT,CRIT,STAT", "Critical",
                   classify("ROUT,CRIT,STAT")["category"])

    def test_unknown_code_not_valid_report(self):
        r = self.submit("ZZZZ")
        self.check("Extra: unknown code goes to Error queue (never silently valid)", "ZZZZ", "Error / Error / unassigned",
                   f"{r.json['report']['category']} / {r.json['report']['queue_state']} / {r.json['report']['assigned_doctor'] or 'unassigned'}")


class TestRouting(Base):
    def test_10_unknown_zone(self):
        r = self.submit("STAT", zone="Z").json["report"]
        self.check("10. Unknown ward zone", "STAT, zone Z", "Escalated + reason recorded",
                   f"{r['queue_state']} + reason {'recorded' if 'Unknown ward zone' in (r['escalation_reason'] or '') else 'MISSING'}")
        esc = self.c.get("/api/queues/escalation").json
        self.assertEqual(esc["count"], 1)

    def test_11_primary_available(self):
        r = self.submit("CRIT", zone="B").json["report"]
        self.check("11. Primary doctor available", "CRIT, zone B", "Assigned to Dr. B (Primary)",
                   f"{r['status']} to {r['assigned_doctor']} ({r['routing_decision'].split()[2].capitalize()})")

    def test_12_primary_unavailable(self):
        self.c.put(f"/api/doctors/{self.doctor_id('Dr. C')}/availability", json={"available": False})
        r = self.submit("STAT", zone="C").json["report"]
        self.check("12. Primary doctor unavailable", "Dr. C unavailable; STAT zone C", "Assigned to Dr. C1", f"Assigned to {r['assigned_doctor']}")

    def test_13_backup_assignment_on_capacity(self):
        self.c.put(f"/api/doctors/{self.doctor_id('Dr. D')}/capacity", json={"max_capacity": 1})
        a = self.submit("ROUT", zone="D").json["report"]
        b = self.submit("ROUT", zone="D").json["report"]
        self.check("13. Backup doctor assignment", "Dr. D capacity=1; two ROUT in zone D", "Dr. D, then Dr. D1",
                   f"{a['assigned_doctor']}, then {b['assigned_doctor']}")

    def test_14_capacity_exceeded(self):
        did = {n: self.doctor_id(n) for n in ("Dr. A", "Dr. A1")}
        self.c.put(f"/api/doctors/{did['Dr. A']}/capacity", json={"max_capacity": 1})
        self.c.put(f"/api/doctors/{did['Dr. A1']}/capacity", json={"max_capacity": 1})
        rs = [self.submit("STAT", zone="A").json["report"] for _ in range(3)]
        self.check("14. Capacity exceeded -> waiting queue", "A=1, A1=1; 3 STAT in zone A",
                   "Assigned, Assigned, Waiting", ", ".join(r["queue_state"] for r in rs))
        self.assertEqual(self.c.get("/api/queues/waiting").json["count"], 1)

    def test_15_priority_override(self):
        did = {n: self.doctor_id(n) for n in ("Dr. A", "Dr. A1")}
        self.c.put(f"/api/doctors/{did['Dr. A']}/capacity", json={"max_capacity": 1})
        self.c.put(f"/api/doctors/{did['Dr. A1']}/availability", json={"available": False})
        first = self.submit("ROUT", "A").json["report"]                  # occupies the only slot
        routine = self.submit("ROUT", "A").json["report"]                # waits
        stat = self.submit("STAT", "A").json["report"]                   # waits (later, but higher priority)
        crit = self.submit("CRIT", "A").json["report"]                   # waits (latest, highest priority)
        order = [r["report_id"] for r in self.c.get("/api/queues/waiting").json["reports"]]
        self.assertEqual(order, [crit["report_id"], stat["report_id"], routine["report_id"]])
        res = self.c.put(f"/api/reports/{first['report_id']}/status", json={"status": "In Progress", "role": "admin"}).json
        res = self.c.put(f"/api/reports/{first['report_id']}/status", json={"status": "Resolved", "role": "admin"}).json
        got = self.c.get(f"/api/reports/{crit['report_id']}").json
        self.check("15. Priority override", "A cap=1; ROUT(assigned), ROUT, STAT, CRIT waiting; resolve first",
                   "queue order CRIT,STAT,ROUT; CRIT assigned first", f"queue order CRIT,STAT,ROUT; CRIT {got['status'].lower()} first"
                   if res["promoted_from_queue"] == [crit["report_id"]] else f"promoted {res['promoted_from_queue']}")
        self.check("15b. Equal priority is FIFO, report ID breaks timestamp ties", "same priority, same timestamp, IDs RPT-000002 / RPT-000001",
                   ["RPT-000001", "RPT-000002"],
                   [x[2] for x in sorted([rt.queue_sort_key(2, "T", "RPT-000002"), rt.queue_sort_key(2, "T", "RPT-000001")])])

    def test_16_duplicate_report(self):
        p = pid()
        first = self.submit("CRIT", "A", patient=p)
        dup = self.submit("CRIT", "A", patient=p)
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute("INSERT INTO routing_assignments(report_id,doctor_id,assignment_type,assigned_at) VALUES (?,1,'Primary','x')",
                         (first.json["report"]["report_id"],))
            db_blocked = False
        except sqlite3.IntegrityError:
            db_blocked = True
        self.check("16. Duplicate report / duplicate assignment", "same patient+code+zone twice; raw 2nd assignment INSERT",
                   "HTTP 409; DB UNIQUE blocks 2nd assignment", f"HTTP {dup.status_code}; DB {'UNIQUE blocks' if db_blocked else 'ALLOWED'} 2nd assignment")

    def test_17_multiple_simultaneous_reports(self):
        results = []
        def worker():
            results.append(self.app.test_client().post("/api/reports", json=dict(
                patient_id=pid(), report_code="ROUT", ward_zone="A", reporter_name="T", reporter_contact="1")).status_code)
        threads = [threading.Thread(target=worker) for _ in range(12)]
        [t.start() for t in threads]; [t.join() for t in threads]
        docs = {d["name"]: d for d in self.c.get("/api/doctors").json}
        a, a1 = docs["Dr. A"]["current_load"], docs["Dr. A1"]["current_load"]
        conn = sqlite3.connect(self.path)
        n_assign = conn.execute("SELECT COUNT(*) FROM routing_assignments").fetchone()[0]
        n_dist = conn.execute("SELECT COUNT(DISTINCT report_id) FROM routing_assignments").fetchone()[0]
        waiting = self.c.get("/api/queues/waiting").json["count"]
        self.check("17. Multiple simultaneous reports", "12 concurrent ROUT in zone A (capacity 3 + 2)",
                   "12x201; loads A=3, A1=2; 5 unique assignments (5 rows); 7 waiting",
                   f"{results.count(201)}x201; loads A={a}, A1={a1}; {n_dist} unique assignments ({n_assign} rows); {waiting} waiting")

    def test_sla_escalation(self):
        self.c.put(f"/api/doctors/{self.doctor_id('Dr. B')}/availability", json={"available": False})
        self.c.put(f"/api/doctors/{self.doctor_id('Dr. B1')}/availability", json={"available": False})
        r = self.submit("CRIT", "B").json["report"]
        before = r["queue_state"]
        adv = self.c.post("/api/simulation/advance", json={"minutes": 16}).json
        after = self.c.get(f"/api/reports/{r['report_id']}").json
        self.check("Extra: 15-minute SLA breach escalates a waiting Critical report", "CRIT zone B, both doctors off, clock +16 min",
                   "Waiting -> Escalated, SLA Breached", f"{before} -> {after['queue_state']}, SLA {after['sla_status']}")


class TestWorkflow(Base):
    def test_18_status_update(self):
        r = self.submit("STAT", "A").json["report"]
        rid, d = r["report_id"], r["assigned_doctor_id"]
        bad_user = self.c.put(f"/api/reports/{rid}/status", json={"status": "In Progress", "handler_id": d + 3}).status_code
        skip = self.c.put(f"/api/reports/{rid}/status", json={"status": "Pending", "handler_id": d}).status_code
        ok = self.c.put(f"/api/reports/{rid}/status", json={"status": "In Progress", "handler_id": d}).json["report"]["status"]
        done = self.c.put(f"/api/reports/{rid}/status", json={"status": "Resolved", "handler_id": d}).json["report"]
        hist = [h["new_status"] for h in self.c.get(f"/api/reports/{rid}").json["history"]]
        self.check("18. Report status update", "other doctor; backwards move; Assigned->In Progress->Resolved",
                   "403; 409; In Progress; Resolved; history Pending>Assigned>In Progress>Resolved",
                   f"{bad_user}; {skip}; {ok}; {done['status']}; history {'>'.join(hist)}")

    def test_19_database_persistence(self):
        rid = self.submit("CRIT", "C").json["report"]["report_id"]
        app2 = create_app(self.path)  # brand-new app / connection on the same file
        got = app2.test_client().get(f"/api/reports/{rid}").json
        self.check("19. Database persistence", "create report, restart app on same SQLite file", f"{rid} still present, Assigned to Dr. C",
                   f"{got['report_id']} still present, {got['status']} to {got['assigned_doctor']}")

    def test_20_end_to_end(self):
        v = self.c.post("/api/validate/patient-id", json={"patient_id": "PAT555555-LABQQ"}).json
        k = self.c.post("/api/classify", json={"report_code": "CRIT"}).json
        sub = self.submit("CRIT", "D", patient="PAT555555-LABQQ").json["report"]
        did = sub["assigned_doctor_id"]
        handler_list = self.c.get(f"/api/reports?doctor_id={did}").json["reports"]
        self.c.put(f"/api/reports/{sub['report_id']}/status", json={"status": "In Progress", "handler_id": did})
        self.c.put(f"/api/reports/{sub['report_id']}/status", json={"status": "Resolved", "handler_id": did})
        an = self.c.get("/api/analytics").json
        self.check("20. Complete end-to-end workflow", "validate -> classify -> submit -> handler sees -> In Progress -> Resolved -> analytics",
                   "valid; Critical; Dr. D; in handler list; analytics resolved=1 unresolved=0 workload 0",
                   f"{'valid' if v['valid'] else 'invalid'}; {k['category']}; {sub['assigned_doctor']}; "
                   f"{'in' if any(x['report_id'] == sub['report_id'] for x in handler_list) else 'NOT in'} handler list; "
                   f"analytics resolved={an['summary']['resolved']} unresolved={an['summary']['unresolved']} workload {sum(w['load'] for w in an['doctor_workload'])}")

    def test_realtime_event_stream(self):
        threading.Timer(0.4, lambda: self.app.test_client().post("/api/reports", json=dict(
            patient_id=pid(), report_code="CRIT", ward_zone="A", reporter_name="T", reporter_contact="1"))).start()
        body = self.c.get("/api/events?limit=2").get_data(as_text=True)
        self.check("Extra: real-time push (Server-Sent Events) announces a new report", "open /api/events, then submit a CRIT report",
                   "'hello' event then 'change' event with kind=submitted",
                   "'hello' event then 'change' event with kind=submitted" if ("event: hello" in body and "event: change" in body and '"kind": "submitted"' in body) else body)

    def test_malformed_rejected_before_dispatch(self):
        r = self.submit("CRIT", "A", patient="PAT12-LABHR")
        total = self.c.get("/api/reports").json["count"]
        self.check("Extra: malformed ID rejected before dispatch", "PAT12-LABHR", "HTTP 422, 0 reports stored", f"HTTP {r.status_code}, {total} reports stored")

    def test_api_input_validation(self):
        codes = [self.c.post("/api/reports", data="notjson", content_type="text/plain").status_code,
                 self.submit("CRIT", "A", reporter_name="").status_code,
                 self.submit("CRIT", "A", urgency="Whenever").status_code,
                 self.c.get("/api/reports/RPT-999999").status_code,
                 self.c.put("/api/doctors/1/capacity", json={"max_capacity": -2}).status_code,
                 self.c.put("/api/doctors/1/availability", json={"available": "yes"}).status_code]
        self.check("Extra: API input validation and HTTP status codes", "bad JSON, no name, bad urgency, unknown report, bad capacity, bad flag",
                   [400, 400, 400, 404, 400, 400], codes)

    def test_pending_review_and_claim_and_zone_fix(self):
        p = self.submit("PEND", "A").json["report"]
        claimed = self.c.post(f"/api/reports/{p['report_id']}/claim", json={"handler_id": 1}).json
        e = self.submit("ROUT", "Q").json["report"]
        fixed = self.c.put(f"/api/reports/{e['report_id']}/zone", json={"ward_zone": "B"}).json
        self.check("Extra: Pending -> Review queue -> claim; unknown zone corrected by admin", "PEND zone A; ROUT zone Q then fixed to B",
                   "Review -> Assigned Dr. A; Escalated -> Assigned Dr. B", f"{p['queue_state']} -> {claimed['status']} {claimed['assigned_doctor']}; "
                   f"{e['queue_state']} -> {fixed['status']} {fixed['assigned_doctor']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
