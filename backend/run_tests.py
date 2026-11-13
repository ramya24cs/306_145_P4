"""Runs the suite and writes docs/TEST_RESULTS.md (inputs, expected outputs, actual results)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
from tests import test_app

suite = unittest.defaultTestLoader.loadTestsFromModule(test_app)
result = unittest.TextTestRunner(verbosity=2).run(suite)

rows = sorted(test_app.RECORDS, key=lambda r: (int("".join(ch for ch in r["case"].split(".")[0] if ch.isdigit()) or 99), r["case"]))
out = ["# Test Results", "", f"{len(rows)} checks recorded - {sum(r['result'] == 'PASS' for r in rows)} PASS, "
       f"{sum(r['result'] == 'FAIL' for r in rows)} FAIL. Unit tests run: {result.testsRun}, failures: {len(result.failures)}, errors: {len(result.errors)}.", "",
       "| Test case | Input | Expected | Actual | Result |", "|---|---|---|---|---|"]
esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
for r in rows:
    out.append(f"| {esc(r['case'])} | {esc(r['input'])} | {esc(r['expected'])} | {esc(r['actual'])} | {r['result']} |")
path = os.path.join(os.path.dirname(__file__), "..", "docs", "TEST_RESULTS.md")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"\nWrote {os.path.abspath(path)}")
sys.exit(0 if result.wasSuccessful() else 1)
