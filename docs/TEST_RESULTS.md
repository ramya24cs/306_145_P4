# Test Results

28 checks recorded - 28 PASS, 0 FAIL. Unit tests run: 23, failures: 0, errors: 0.

| Test case | Input | Expected | Actual | Result |
|---|---|---|---|---|
| 1. Valid patient identifier | PAT123456-LABHR | DFA=True, Regex=True, agree | DFA=True, Regex=True, agree | PASS |
| 2. Invalid patient identifiers (empty, digits, hyphen, prefix, chars, suffix) | 10 malformed IDs | {'': "rejected + message mentions 'empty'", 'PAT12345-LABHR': "rejected + message mentions 'digit count'", 'PAT1234567-LABHR': "rejected + message mentions 'digit count'", 'PAT123456LABHR': "rejected + message mentions 'hyphen'", 'XYZ123456-LABHR': "rejected + message mentions 'prefix'", 'PAT12A456-LABHR': "rejected + message mentions 'Invalid character'", 'PAT123456-LABhr': "rejected + message mentions 'suffix'", 'PAT123456-LAB12': "rejected + message mentions 'suffix'", 'PAT123456-LABHRX': "rejected + message mentions 'too long'", 'PAT123456-ABCHR': "rejected + message mentions 'lab prefix'"} | {'': "rejected + message mentions 'empty'", 'PAT12345-LABHR': "rejected + message mentions 'digit count'", 'PAT1234567-LABHR': "rejected + message mentions 'digit count'", 'PAT123456LABHR': "rejected + message mentions 'hyphen'", 'XYZ123456-LABHR': "rejected + message mentions 'prefix'", 'PAT12A456-LABHR': "rejected + message mentions 'Invalid character'", 'PAT123456-LABhr': "rejected + message mentions 'suffix'", 'PAT123456-LAB12': "rejected + message mentions 'suffix'", 'PAT123456-LABHRX': "rejected + message mentions 'too long'", 'PAT123456-ABCHR': "rejected + message mentions 'lab prefix'"} | PASS |
| 3. Incomplete identifier | PAT1234 | invalid, 'Incomplete identifier' error | invalid, 'Incomplete identifier' error | PASS |
| 4. DFA and regex agreement | 6005 random/mutated strings incl. trailing newline & Unicode digits | 0 mismatches | 0 mismatches | PASS |
| 5. Classification of CRIT | CRIT | Critical (priority 1) | Critical (priority 1) | PASS |
| 6. Classification of STAT | STAT | Stat (priority 2) | Stat (priority 2) | PASS |
| 7. Classification of ROUT | ROUT | Routine (priority 3) | Routine (priority 3) | PASS |
| 8. Classification of PEND | PEND | Pending (priority 4) | Pending (priority 4) | PASS |
| 9. Classification of XYZ9 | XYZ9 | Error (priority 5) | Error (priority 5) | PASS |
| 10. Unknown ward zone | STAT, zone Z | Escalated + reason recorded | Escalated + reason recorded | PASS |
| 11. Primary doctor available | CRIT, zone B | Assigned to Dr. B (Primary) | Assigned to Dr. B (Primary) | PASS |
| 12. Primary doctor unavailable | Dr. C unavailable; STAT zone C | Assigned to Dr. C1 | Assigned to Dr. C1 | PASS |
| 13. Backup doctor assignment | Dr. D capacity=1; two ROUT in zone D | Dr. D, then Dr. D1 | Dr. D, then Dr. D1 | PASS |
| 14. Capacity exceeded -> waiting queue | A=1, A1=1; 3 STAT in zone A | Assigned, Assigned, Waiting | Assigned, Assigned, Waiting | PASS |
| 15. Priority override | A cap=1; ROUT(assigned), ROUT, STAT, CRIT waiting; resolve first | queue order CRIT,STAT,ROUT; CRIT assigned first | queue order CRIT,STAT,ROUT; CRIT assigned first | PASS |
| 15b. Equal priority is FIFO, report ID breaks timestamp ties | same priority, same timestamp, IDs RPT-000002 / RPT-000001 | ['RPT-000001', 'RPT-000002'] | ['RPT-000001', 'RPT-000002'] | PASS |
| Extra: 15-minute SLA breach escalates a waiting Critical report | CRIT zone B, both doctors off, clock +16 min | Waiting -> Escalated, SLA Breached | Waiting -> Escalated, SLA Breached | PASS |
| 16. Duplicate report / duplicate assignment | same patient+code+zone twice; raw 2nd assignment INSERT | HTTP 409; DB UNIQUE blocks 2nd assignment | HTTP 409; DB UNIQUE blocks 2nd assignment | PASS |
| 17. Multiple simultaneous reports | 12 concurrent ROUT in zone A (capacity 3 + 2) | 12x201; loads A=3, A1=2; 5 unique assignments (5 rows); 7 waiting | 12x201; loads A=3, A1=2; 5 unique assignments (5 rows); 7 waiting | PASS |
| 18. Report status update | other doctor; backwards move; Assigned->In Progress->Resolved | 403; 409; In Progress; Resolved; history Pending>Assigned>In Progress>Resolved | 403; 409; In Progress; Resolved; history Pending>Assigned>In Progress>Resolved | PASS |
| 19. Database persistence | create report, restart app on same SQLite file | RPT-000001 still present, Assigned to Dr. C | RPT-000001 still present, Assigned to Dr. C | PASS |
| 20. Complete end-to-end workflow | validate -> classify -> submit -> handler sees -> In Progress -> Resolved -> analytics | valid; Critical; Dr. D; in handler list; analytics resolved=1 unresolved=0 workload 0 | valid; Critical; Dr. D; in handler list; analytics resolved=1 unresolved=0 workload 0 | PASS |
| Extra: API input validation and HTTP status codes | bad JSON, no name, bad urgency, unknown report, bad capacity, bad flag | [400, 400, 400, 404, 400, 400] | [400, 400, 400, 404, 400, 400] | PASS |
| Extra: Pending -> Review queue -> claim; unknown zone corrected by admin | PEND zone A; ROUT zone Q then fixed to B | Review -> Assigned Dr. A; Escalated -> Assigned Dr. B | Review -> Assigned Dr. A; Escalated -> Assigned Dr. B | PASS |
| Extra: malformed ID rejected before dispatch | PAT12-LABHR | HTTP 422, 0 reports stored | HTTP 422, 0 reports stored | PASS |
| Extra: multiple matching codes use priority Critical>Stat>Routine>Pending>Error | ROUT,CRIT,STAT | Critical | Critical | PASS |
| Extra: real-time push (Server-Sent Events) announces a new report | open /api/events, then submit a CRIT report | 'hello' event then 'change' event with kind=submitted | 'hello' event then 'change' event with kind=submitted | PASS |
| Extra: unknown code goes to Error queue (never silently valid) | ZZZZ | Error / Error / unassigned | Error / Error / unassigned | PASS |
