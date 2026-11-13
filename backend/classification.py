"""Report classification: exactly five categories, deterministic priority.

Critical > Stat > Routine > Pending > Error
"""
import re

CATEGORIES = ["Critical", "Stat", "Routine", "Pending", "Error"]
PRIORITY = {"Critical": 1, "Stat": 2, "Routine": 3, "Pending": 4, "Error": 5}
PRIORITY_LABEL = {1: "Highest", 2: "High", 3: "Normal", 4: "Low", 5: "None (error)"}
SLA_CATEGORIES = {"Critical", "Stat"}

# Ordered by priority: the first matching entry wins when several patterns match.
PATTERNS = [
    ("Critical", re.compile(r"^CRIT$")),
    ("Stat", re.compile(r"^STAT$")),
    ("Routine", re.compile(r"^ROUT$")),
    ("Pending", re.compile(r"^PEND$")),
]

LANE = {  # routing rule per category
    "Critical": "Ward Duty Doctor (highest priority)",
    "Stat": "Ward Duty Doctor (high priority)",
    "Routine": "Standard Queue",
    "Pending": "Review Queue",
    "Error": "Error Queue",
}


def classify(report_code) -> dict:
    """Classify a report code. Several tokens (e.g. 'STAT,CRIT') are allowed;
    when more than one pattern matches the highest priority wins."""
    raw = report_code if isinstance(report_code, str) else ""
    tokens = [t for t in re.split(r"[\s,;/|+]+", raw.strip().upper()) if t]
    matched, unknown = set(), []
    for tok in tokens:
        hit = next((cat for cat, pat in PATTERNS if pat.match(tok)), None)
        if hit:
            matched.add(hit)
        else:
            unknown.append(tok)

    if matched:
        category = min(matched, key=lambda c: PRIORITY[c])   # deterministic tie-break
        note = None
        if len(matched) > 1:
            note = f"Multiple patterns matched {sorted(matched, key=lambda c: PRIORITY[c])}; highest priority '{category}' applied."
        if unknown:
            note = (note + " " if note else "") + f"Unrecognised token(s) ignored: {', '.join(unknown)}."
        reason = note or f"Code '{tokens[0]}' recognised."
    else:
        category = "Error"
        if not tokens:
            reason = "Report code is empty - classified as Error."
        else:
            reason = f"Unknown or unsupported report code '{raw.strip()}' - classified as Error (not a valid report)."
    return {
        "report_code": raw.strip().upper(),
        "category": category,
        "priority": PRIORITY[category],
        "priority_label": PRIORITY_LABEL[PRIORITY[category]],
        "route": LANE[category],
        "sla_applies": category in SLA_CATEGORIES,
        "recognised": category != "Error",
        "reason": reason,
    }
