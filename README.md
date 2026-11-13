# Pathology Lab Result Notifier (P4)

React + Flask + SQLite. Demonstrates **BCS503** (DFA vs regex validation, deterministic classification),
**BCS502** (client-server over HTTP/REST, JSON, status codes, GET/POST/PUT/DELETE) and full-stack development.

## Folder structure
```
pathology-lab-notifier/
├── backend/
│   ├── app.py              Flask REST API (all endpoints)
│   ├── validation.py       DFA (states, transitions, dead state) + independent regex validator + error diagnostics
│   ├── classification.py   5 categories, priority Critical > Stat > Routine > Pending > Error
│   ├── routing.py          routing-table lookup, availability/capacity checks, backup, waiting queue, escalation, SLA
│   ├── database.py         SQLite schema (7 tables), seed data, transactions, simulated clock
│   ├── run_tests.py        runs the suite and writes docs/TEST_RESULTS.md
│   ├── tests/test_app.py   23 tests / 28 recorded checks (stdlib unittest)
│   └── requirements.txt
├── frontend/               Vite + React 18 + Recharts
│   └── src/ App.jsx, api.js, ui.jsx (live context, countdowns, rings, drawer), styles.css,
│            pages/{Overview,SubmitReport,UserDashboard,HandlerDashboard,RoutingDashboard,Analytics}.jsx
└── docs/TEST_RESULTS.md    inputs / expected / actual for every check
```

## Install and run (two terminals)
Requires Python 3.10+ and Node 18+.

**Terminal 1 - backend** (http://127.0.0.1:5000)
```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
The SQLite file `backend/lab_notifier.db` and the 4 zones / 8 doctors are created automatically on first start.

**Terminal 2 - frontend** (http://localhost:5173)
```bash
cd frontend
npm install
npm run dev
```
Vite proxies `/api/*` to Flask, so no CORS setup is needed (Flask also sends CORS headers if you set `VITE_API_URL=http://127.0.0.1:5000/api`).

## Run the tests
```bash
cd backend
python run_tests.py            # prints results and regenerates ../docs/TEST_RESULTS.md
```

## Try the scenarios in the UI
| Scenario | Do this |
|---|---|
| Valid ID | Submit `PAT123456-LABHR`, code `CRIT`, Zone A -> assigned to Dr. A |
| Malformed ID | `PAT12345-LABHR`, `PAT123456LABHR`, `PAT123456-LABhr` -> inline errors, button disabled, server also returns 422 |
| Unknown code | code `XYZ` -> category Error -> Error queue (never a valid report) |
| Unknown zone | choose "Other / unlisted zone" -> Central Escalation Queue with reason; admin can fix the zone on Routing management |
| Backup / capacity | On Routing management set Dr. A unavailable (or capacity 0) -> next Zone A report goes to Dr. A1; disable both -> Waiting queue |
| Priority override | With both Zone A doctors full, submit ROUT, STAT, CRIT; then resolve a report on Handler dashboard -> CRIT is assigned first |
| 15-minute SLA | Disable both doctors in a zone, submit CRIT, press "Advance clock 16 min" -> escalated, SLA Breached |
| Complete workflow | Submit -> Handler dashboard (Accept) -> Resolve -> User dashboard and Analytics update |

## Real-time behaviour
* Flask exposes `GET /api/events` (Server-Sent Events). Every successful write (submit, status change, availability, capacity, zone fix, clock advance) publishes an event.
* The React app keeps one `EventSource` open. On each event every visible dashboard refetches immediately, so a report submitted in one browser tab appears in other tabs, the handler desk, the routing view and the charts within a moment, with a toast for new submissions. A 15-second poll is only a safety net.
* The top-right pill shows **Live** / **Reconnecting…**; the browser reconnects on its own if Flask restarts.
* SLA countdowns tick every second using the server's (simulated) clock, turning amber then red, and show **Breached** at zero.
* Pages: **Command center** (live overview), Submit report (pipeline + dispatch preview), Reports (searchable, slide-in timeline), Handler desk, Routing (zone cards with capacity rings), Analytics.

## Design notes
* **DFA**: states `q0..q15` + `q_dead`; `q15` accepting; `delta` implemented in `dfa_transition`. Regex: `^PAT[0-9]{6}-LAB[A-Z]{2}$` with `fullmatch` (so a trailing newline is rejected, matching the DFA). A 6,000-string test confirms both always agree.
* **Zone routing key** is only read after validation succeeds. Routing order: Error code -> Error queue; unknown zone -> escalation; Pending -> Review queue; Critical/Stat/Routine -> primary -> backup -> Waiting queue.
* **Queue order**: priority, then submission time (FIFO), then report ID. Waiting reports are promoted whenever a report resolves or a doctor's availability/capacity changes.
* **No duplicate assignment**: `BEGIN IMMEDIATE` transactions, a guarded `UPDATE ... WHERE assigned_doctor_id IS NULL`, and `UNIQUE(report_id)` on `routing_assignments`. Duplicate submissions (same patient + code + zone, still unresolved) return HTTP 409.
* **Load** = a doctor's reports in status Assigned or In Progress. Resolving frees capacity.
* **SLA**: Critical/Stat get a deadline of submission + 15 min. A simulated clock (`POST /api/simulation/advance`) lets you demonstrate a breach instantly; waiting reports past the deadline move to the escalation queue.
* **Handler authorisation** is simulated (pick a doctor in "Signed in as"; the API checks `handler_id` against the assigned doctor, or `role: "admin"`). There is no real login.

## REST API (all JSON)
| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | server + DB check |
| GET | /api/events | Server-Sent Events stream (real-time push) |
| POST | /api/validate/patient-id, /dfa, /regex | validation (both / DFA only / regex only) |
| POST | /api/classify | classify report code |
| POST | /api/reports | submit (201, 400, 409 duplicate, 422 invalid ID) |
| GET | /api/reports?status=&category=&zone=&q=&doctor_id= | list / search |
| GET | /api/reports/:id | details + history + routing log |
| PUT | /api/reports/:id/status | update status (403, 409 on invalid transition) |
| POST | /api/reports/:id/claim | handler claims an unassigned report |
| PUT | /api/reports/:id/zone | admin fixes unknown zone and re-dispatches |
| DELETE | /api/reports/:id | delete a Resolved report |
| GET | /api/doctors, /api/doctors/:id | doctor details and assigned reports |
| PUT | /api/doctors/:id/availability, /capacity | availability / maximum capacity |
| GET | /api/routing/table | zones, loads, waiting, escalated, overrides, history |
| GET | /api/queues/waiting, escalation, review, error | queues |
| POST | /api/simulation/advance | advance simulated clock (SLA demo) |
| GET | /api/analytics | chart data and summary cards |
