from __future__ import annotations
import re
from collections import Counter
from .models import Variable, VariableBlock

LIST_MARKER = re.compile(r"^(?:\[\d+\]|\(\d+\)|::\s*\d+\s*::)$")
GENERIC_NAMES = {"date", "amount", "pin code", "mobile number", "gstin", "ifsc code", "email address", "account number"}
TRAILING_COUNTER = re.compile(r"\s+\d+$")


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()

def is_list_marker(s: str) -> bool:
    t=s.strip()
    if not t: return True
    if LIST_MARKER.match(t): return True
    # Bare page/list integers are only short tokens. Six-digit cheque numbers must survive.
    stripped=t.lstrip("….").rstrip(".")
    return len(t) <= 5 and stripped.isdigit()

def exact_or_whitespace_match(document: str, text: str) -> tuple[int, str] | None:
    if not text.strip(): return None
    idx = document.find(text)
    if idx >= 0: return idx, text
    idx = document.lower().find(text.lower())
    if idx >= 0: return idx, document[idx:idx+len(text)]
    # Whitespace-tolerant match while retaining the actual document substring.
    tokens = [re.escape(x) for x in re.split(r"\s+", text.strip()) if x]
    if not tokens: return None
    m = re.search(r"[\s\u00a0]+".join(tokens), document, flags=re.I)
    if m: return m.start(), m.group(0)
    return None

def validate_variables(vars: list[Variable], document: str) -> list[Variable]:
    out: list[Variable] = []
    for v in vars:
        ot=v.original_text.strip(); nm=v.name.strip()
        structural = bool(LIST_MARKER.match(ot))
        numeric_placeholder = is_list_marker(ot) and is_list_marker(nm)
        if structural or numeric_placeholder or is_list_marker(nm):
            continue
        # Preserve exact deterministic positions when valid. This is critical for same-valued semantic fields.
        if 0 <= v.position < len(document) and document[v.position:v.position+len(v.original_text)] == v.original_text:
            out.append(v)
            continue
        found = exact_or_whitespace_match(document, v.original_text)
        if found:
            pos, actual = found
            v.position = pos
            v.original_text = actual
            out.append(v)
    return out

def semantic_family(name: str) -> str:
    """Return a conservative semantic family for exact-span duplicate collapse.

    Numbered UI labels ("Cheque Date 2") are the same family as their base
    label. A small alias set handles obvious spelling variants without merging
    legitimately different fields that happen to share the same text.
    """
    value = TRAILING_COUNTER.sub("", normalize(name))
    aliases = {
        "cheque no": "cheque number",
        "check no": "cheque number",
        "check number": "cheque number",
        "cheque date": "cheque date",
        "check date": "cheque date",
        "cheque amount": "cheque amount",
        "check amount": "cheque amount",
        "plaintiff name": "plaintiff name",
        "defendant name": "defendant name",
        "complainant name": "complainant name",
        "accused name": "accused name",
    }
    return aliases.get(value, value)


def dedup(vars: list[Variable]) -> list[Variable]:
    """Collapse only same-span/same-family duplicates.

    The same value at another source position must survive, and the same span may
    legitimately represent two distinct semantic fields. Among true duplicates
    keep the higher-confidence representative.
    """
    best: dict[tuple[str, int, str], Variable] = {}
    for v in vars:
        key = (normalize(v.original_text), v.position, semantic_family(v.name))
        current = best.get(key)
        if current is None or (v.confidence_score or 0.0) > (current.confidence_score or 0.0):
            best[key] = v
    return sorted(best.values(), key=lambda x: (x.position, len(x.original_text)))

def enrich_generic_names(vars: list[Variable], document: str) -> None:
    for v in vars:
        if normalize(v.name) not in GENERIC_NAMES:
            continue
        ctx = document[max(0, v.position-140): min(len(document), v.position+len(v.original_text)+100)]
        lc = ctx.lower()
        base = normalize(v.name)
        if base == "date":
            if "cheque" in lc: v.name = "Cheque Date"
            elif "notice" in lc: v.name = "Notice Date"
            elif "invoice" in lc: v.name = "Invoice Date"
            elif "challan" in lc: v.name = "Delivery Challan Date"
            elif "e-way" in lc or "eway" in lc: v.name = "E-Way Bill Date"
            elif "dishon" in lc or "return memo" in lc: v.name = "Date of Dishonour"
            elif "filed" in lc: v.name = "Filing Date"
        elif base == "amount":
            if "cheque" in lc: v.name = "Cheque Amount"
            elif "court fee" in lc: v.name = "Court Fee Amount"
            elif "suit" in lc: v.name = "Suit Amount"
            elif "invoice" in lc: v.name = "Invoice Amount"
        elif base in {"pin code", "gstin", "mobile number", "email address"}:
            # Prefer the nearest explicit party-role label BEFORE the field instead of
            # whichever role happens to occur somewhere in a broad context window.
            before = document[max(0, v.position-500):v.position].lower()
            candidates=[]
            for r in ["Complainant","Accused","Plaintiff","Defendant"]:
                idx=max(before.rfind(r.lower()+":"), before.rfind(r.lower()+" :-"), before.rfind(r.lower()+" -"))
                if idx >= 0: candidates.append((idx,r))
            if candidates:
                role=max(candidates)[1]
                v.name=f"{role} {v.name}"

def filter_false_positives(vars: list[Variable], document: str) -> list[Variable]:
    out = []
    for v in vars:
        ctx = document[max(0,v.position-180):min(len(document),v.position+len(v.original_text)+180)].lower()
        if any(k in ctx for k in ["advocate", "enrollment no", "enrll.no", "welfare no"]):
            # Keep court/case/legal references, but drop fixed letterhead personal contact data.
            if any(k in normalize(v.name) for k in ["mobile", "email", "enrollment", "advocate"]):
                continue
        out.append(v)
    return out

def disambiguate_names(vars: list[Variable]) -> None:
    counts: Counter[str] = Counter()
    for v in vars:
        key = normalize(v.name)
        counts[key] += 1
        if counts[key] > 1:
            v.name = f"{v.name} {counts[key]}"

def group_into_blocks(vars: list[Variable]) -> list[VariableBlock]:
    groups: dict[str, list[Variable]] = {}
    atomics: list[VariableBlock] = []
    roles = ("Complainant", "Accused", "Plaintiff", "Defendant")
    for v in vars:
        role = next((r for r in roles if v.name.lower().startswith(r.lower()+" ")), None)
        if role:
            groups.setdefault(role, []).append(v)
        else:
            atomics.append(VariableBlock(type="atomic", variable=v))
    blocks = [VariableBlock(type="parent", label=role, children=children) for role, children in groups.items()]
    return blocks + atomics

def finalize(vars: list[Variable], document: str) -> list[Variable]:
    vars = validate_variables(vars, document)
    # Generic names need local semantic enrichment before same-span dedup, or a
    # generic "Date" and a model-produced "Cheque Date" can survive as fake
    # duplicates and only be renamed afterwards.
    enrich_generic_names(vars, document)
    vars = filter_false_positives(vars, document)
    vars = dedup(vars)
    vars.sort(key=lambda x: (x.position, len(x.original_text)))
    disambiguate_names(vars)
    return vars
