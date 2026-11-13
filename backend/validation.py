"""Patient-ID validation (BCS503 - Automata Theory).

Required format:  PAT[6 digits]-LAB[2 uppercase letters]   e.g. PAT123456-LABHR

Two *independent* recognisers are implemented:
  A. A hand-built deterministic finite automaton (DFA) with an explicit
     transition function, accepting state and dead (trap) state.
  B. A regular expression  ^PAT[0-9]{6}-LAB[A-Z]{2}$

Neither implementation calls the other. `validate_patient_id` runs both,
compares them, and attaches human-readable diagnostics.
"""
import re

# --------------------------------------------------------------------------- #
# A. DFA
# --------------------------------------------------------------------------- #
# Pattern positions (state qN means "N characters of the pattern matched"):
#   q0 -P-> q1 -A-> q2 -T-> q3 -d-> q4 -d-> q5 -d-> q6 -d-> q7 -d-> q8 -d-> q9
#   q9 -'-'-> q10 -L-> q11 -A-> q12 -B-> q13 -[A-Z]-> q14 -[A-Z]-> q15 (ACCEPT)
# Any other input moves to the dead state q_dead, which loops on every symbol.
DEAD = "q_dead"
STATES = [f"q{i}" for i in range(16)] + [DEAD]
START_STATE = "q0"
ACCEPT_STATES = {"q15"}
ALPHABET_CLASSES = ["P", "A", "T", "L", "B", "DIGIT", "UPPER", "HYPHEN", "OTHER"]

# Position -> character class expected to move from q(position) to q(position+1)
_EXPECTED = (
    ["P", "A", "T"] + ["DIGIT"] * 6 + ["HYPHEN", "L", "A", "B"] + ["UPPER"] * 2
)


def _char_matches(symbol: str, expected: str) -> bool:
    if expected == "DIGIT":
        return "0" <= symbol <= "9"          # ASCII only (not str.isdigit)
    if expected == "UPPER":
        return "A" <= symbol <= "Z"          # ASCII only (not str.isupper)
    if expected == "HYPHEN":
        return symbol == "-"
    return symbol == expected                # literal P, A, T, L, A, B


def dfa_transition(state: str, symbol: str) -> str:
    """delta(state, symbol) -> next state. Dead state is absorbing."""
    if state == DEAD or state in ACCEPT_STATES:
        return DEAD                          # nothing may follow a full ID
    position = int(state[1:])
    return f"q{position + 1}" if _char_matches(symbol, _EXPECTED[position]) else DEAD


def dfa_run(text: str):
    """Run the DFA. Returns (accepted, final_state, trace, fail_index)."""
    state = START_STATE
    trace = [{"index": None, "symbol": None, "state": state}]
    fail_index = None
    for i, ch in enumerate(text):
        state = dfa_transition(state, ch)
        trace.append({"index": i, "symbol": ch, "state": state})
        if state == DEAD and fail_index is None:
            fail_index = i
    return state in ACCEPT_STATES, state, trace, fail_index


def dfa_validate(patient_id) -> bool:
    if not isinstance(patient_id, str):
        return False
    return dfa_run(patient_id)[0]


# --------------------------------------------------------------------------- #
# B. Regular expression
# --------------------------------------------------------------------------- #
PATIENT_ID_REGEX = re.compile(r"^PAT[0-9]{6}-LAB[A-Z]{2}$")


def regex_validate(patient_id) -> bool:
    if not isinstance(patient_id, str):
        return False
    # fullmatch: Python's '$' would otherwise accept a trailing "\n".
    return PATIENT_ID_REGEX.fullmatch(patient_id) is not None


# --------------------------------------------------------------------------- #
# Diagnostics (explains *why* an identifier is rejected)
# --------------------------------------------------------------------------- #
def diagnose(patient_id) -> list:
    """Return a list of meaningful error messages ([] when the ID is valid)."""
    if patient_id is None or (isinstance(patient_id, str) and patient_id == ""):
        return ["Patient ID is empty. Expected format PAT123456-LABHR."]
    if not isinstance(patient_id, str):
        return ["Patient ID must be text."]
    if patient_id.strip() == "":
        return ["Patient ID contains only spaces."]

    accepted, final_state, _trace, fail = dfa_run(patient_id)
    if accepted:
        return []

    errors = []
    if fail is None:
        # Ran out of input before reaching the accepting state.
        n = int(final_state[1:])
        errors.append(
            f"Incomplete identifier: only {n} of 15 characters supplied "
            f"(stopped in state {final_state}). Next expected: {_describe(_EXPECTED[n])}."
        )
        return errors

    ch = patient_id[fail]
    pos = fail                                # DFA position == index while alive
    shown = repr(ch) if ch.strip() else "a space/whitespace character"
    if pos >= 15:
        errors.append(f"Identifier too long: unexpected extra characters from position {pos + 1}.")
    elif pos < 3:
        errors.append(f"Incorrect prefix: identifier must start with 'PAT' (found {shown} at position {pos + 1}).")
    elif pos < 9:                              # inside the six digits
        if ch == "-":
            errors.append(f"Incorrect digit count: exactly 6 digits required after 'PAT', found {pos - 3}.")
        elif ch.isalpha():
            errors.append(f"Invalid character {shown} at position {pos + 1}: only digits 0-9 are allowed after 'PAT'.")
        else:
            errors.append(f"Invalid character {shown} at position {pos + 1}: only digits 0-9 are allowed after 'PAT'.")
    elif pos == 9:                             # expected the hyphen
        if "0" <= ch <= "9":
            errors.append("Incorrect digit count: more than 6 digits after 'PAT'.")
        elif ch.isalpha():
            errors.append("Missing hyphen: expected '-' between the 6 digits and 'LAB'.")
        else:
            errors.append(f"Invalid character {shown} at position 10: expected '-'.")
    elif pos < 13:                             # inside 'LAB'
        errors.append(f"Incorrect lab prefix: expected 'LAB' after the hyphen (found {shown} at position {pos + 1}).")
    else:                                      # two-letter suffix
        if ch.isalpha():
            errors.append(f"Incorrect suffix: letters must be uppercase A-Z (found {shown} at position {pos + 1}).")
        elif "0" <= ch <= "9":
            errors.append(f"Incorrect suffix: digits are not allowed; suffix must be 2 uppercase letters (position {pos + 1}).")
        else:
            errors.append(f"Invalid character {shown} at position {pos + 1}: suffix must be 2 uppercase letters.")
    if len(patient_id) < 15 and not errors[0].startswith("Incomplete"):
        errors.append(f"Length is {len(patient_id)}; a valid identifier has exactly 15 characters.")
    return errors


def _describe(expected: str) -> str:
    return {"DIGIT": "a digit (0-9)", "UPPER": "an uppercase letter (A-Z)", "HYPHEN": "a hyphen '-'"}.get(
        expected, f"the letter '{expected}'"
    )


def validate_patient_id(patient_id) -> dict:
    """Run both validators, compare, and explain failures."""
    dfa_ok = dfa_validate(patient_id)
    regex_ok = regex_validate(patient_id)
    dfa_info = dfa_run(patient_id) if isinstance(patient_id, str) else (False, DEAD, [], 0)
    return {
        "patient_id": patient_id,
        "dfa": {
            "valid": dfa_ok,
            "final_state": dfa_info[1],
            "trace": dfa_info[2],
            "accepting_states": sorted(ACCEPT_STATES),
        },
        "regex": {"valid": regex_ok, "pattern": PATIENT_ID_REGEX.pattern},
        "agree": dfa_ok == regex_ok,
        "valid": dfa_ok and regex_ok,
        "errors": [] if (dfa_ok and regex_ok) else (diagnose(patient_id) or ["Patient ID rejected."]),
    }
