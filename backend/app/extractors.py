from __future__ import annotations
import re
from dataclasses import dataclass
from .models import Variable

@dataclass(frozen=True)
class Hit:
    category: str
    name: str
    text: str
    position: int
    confidence: float = 1.0

# Generic strict-format fields. Keep these conservative; ambiguous fields are left to the LLM.
PATTERNS: list[tuple[str, str, re.Pattern[str], int]] = [
    ("email", "Email Address", re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"), 0),
    ("ifsc", "IFSC Code", re.compile(r"(?i)\b[A-Z]{4}\s*0(?:\s*[A-Z0-9]){6}\b"), 0),
    ("gstin", "GSTIN", re.compile(r"(?i)(?<![A-Z0-9])([0-9]{2}\s*[A-Z]{5}\s*[0-9]{4}\s*[A-Z]\s*[1-9A-Z]\s*Z\s*[0-9A-Z])(?![A-Z0-9])"), 1),
    ("mobile", "Mobile Number", re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?[6-9](?:[\s\-]?\d){9}(?!\d)"), 0),
    ("pin", "PIN Code", re.compile(r"(?<!\d)([1-9](?:\s*\d){5})(?!\d)"), 1),
    ("date", "Date", re.compile(r"(?<!\d)(\d{1,2}[\-/]\d{1,2}[\-/]\d{4})(?!\d)"), 1),
    ("amount", "Amount", re.compile(r"(?i)(?<!\d)(?:Rs\.?\s*[:\-]?\s*)?([0-9]{1,3}(?:,[0-9]{2,3})+(?:[=.][0-9]{1,2})?)(?!\d)"), 1),
    ("section_act", "Legal Section", re.compile(r"(?i)\b(?:Section|Sec\.?|U/s\.?)\s*[:.\-]?\s*\d+[A-Z]?(?:\s*(?:r/w\.?|read\s+with)\s*(?:Sec(?:tion)?\.?)?\s*\d+[A-Z]?)?\s+of\s+the\s+[A-Z][A-Za-z .()\-]{3,80}?(?:Act|Code|Sanhita)\s*(?:,?\s*\d{4})?"), 0),
]

LABEL_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("cheque", "Cheque Number", re.compile(r"(?i)\bCheque\s*(?:No\.?|Number)\s*[:\-]?\s*([0-9][0-9\s]{4,17})")),
    ("account", "Account Number", re.compile(r"(?i)\b(?:Bank\s+)?Account\s*(?:No\.?|Number)\s*[:\-]?\s*([0-9][0-9\s]{7,24})")),
    ("reference", "Reference Number", re.compile(r"(?i)\b(?:Ref(?:erence)?\.?)\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{2,})")),
    ("invoice", "Invoice Number", re.compile(r"(?i)\bInvoice(?:/s)?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{0,})")),
    ("challan", "Delivery Challan Number", re.compile(r"(?i)\bDelivery\s+Chall?an(?:/s)?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{0,})")),
    ("lr", "LR Number", re.compile(r"(?i)\bL\.?\s*R\.?/?s?\.?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/._\-]{2,})")),
    ("eway", "E-Way Bill Number", re.compile(r"(?i)\bE\s*-?\s*Way\s+Bill(?:/s)?\s+No\.?\s*[:\-]?\s*([0-9][0-9\s]{7,20})")),
    ("hsn", "HSN Code", re.compile(r"(?i)\bHSN\s*[:\-]?\s*([0-9]{4,10})\b")),
    ("case", "Case Number", re.compile(r"(?i)\b(?:Criminal\s+Case|Summary\s+Civil\s+Suit|SMST\s*-?\s*R\s+Summary\s+Civil\s+Suit|Complaint)\s*No\.?\s*[:\-]?\s*([A-Z0-9/~._\-]*\d[A-Z0-9/~._\-]*)")),
    ("court", "Court Number", re.compile(r"(?i)\bCourt\s+No\.?\s*[:\-]?\s*(\d{1,4})\b")),
    ("suit_amount", "Suit Amount", re.compile(r"(?i)\b(?:Suit\s+(?:Amount|Valued\s+at)|Suit\s+Value)\s+Rs\.?\s*[:\-]?\s*([0-9][0-9,]*(?:[=.][0-9]{1,2})?)")),
    ("court_fee", "Court Fee Amount", re.compile(r"(?i)\bCourt\s+Fee(?:s)?\s+Stamp\s+Rs\.?\s*[:\-]?\s*([0-9][0-9,]*(?:[=.][0-9]{1,2})?)")),
    ("interest", "Interest Rate", re.compile(r"(?i)\b(?:interest\s*@?\s*|rate\s+of\s+)(\d{1,2}(?:\.\d+)?)\s*%")),
    ("age", "Age", re.compile(r"(?i)\bAge\s*:\s*(\d{1,3})\s*(?:Yrs?|Years?|Adult)\b")),
    ("cheque_date", "Cheque Date", re.compile(r"(?i)\b(?:Cheque\s+Date|Date\s+of\s+Cheque)\s*:\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})")),
    ("return_date", "Cheque Return Date", re.compile(r"(?i)\b(?:Return\s*Date|Return\s*Date/Dishonou?r\s*Memo|Dishonou?r\s+Date)\s*[:\-]?\s*(?:[\"“][^\"”]{2,80}[\"”]\s*)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})")),
    ("notice_date", "Notice Date", re.compile(r"(?i)\b(?:Notice\s+Date|Date\s+of\s+Notice)\s*[:\-]?\s*(?:Ref\.?\s*No\.?\s*:\s*[A-Z0-9/._\-]+\s*)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})")),
    ("dispatch_date", "Notice Dispatch Date", re.compile(r"(?i)\b(?:Date\s+of\s+Dispatch|Post\s+Date)\s*[:\-]?.{0,100}?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})")),
    ("service_date", "Notice Service Date", re.compile(r"(?i)\b(?:Service\s+Date|Date\s+of\s+(?:Delivery|Service))\s*[:\-]?\s*(?:[\"“][^\"”]{2,80}[\"”]\s*)?(\d{1,2}(?:\s*[-/]\s*\d{1,2})?[/\-]\d{1,2}[/\-]\d{2,4})")),
    ("filed_on", "Filed On", re.compile(r"(?i)\bFiled\s+On\s*:\s*([^\n\r.]{4,30}\d{4})")),
    ("dishonour_reason", "Dishonour Reason", re.compile(r"(?i)\b(?:Reason\s+for\s+Dishonou?r|endorsement)\s*[:\-]?\s*[“\"]?([A-Z][A-Z /&\-]{3,60})[”\"]?")),
]

TRACKING = re.compile(r"\b[A-Z]{2}\s*\d{3}\s*\d{3}\s*\d{3}\s*IN\b")

PARTY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Complainant", re.compile(r"(?im)^\s*Complainant\s*[:\-]+\s*(?:\[?\d+\]?\s*)?[“\"]?([^\n\r,;]{2,100})")),
    ("Accused", re.compile(r"(?im)^\s*Accused\s*[:\-]+\s*(?:\[?\d+\]?\s*)?[“\"]?([^\n\r,;]{2,100})")),
    ("Plaintiff", re.compile(r"(?im)^\s*Plaintiff\s*[:\-]+\s*[“\"]?([^\n\r,;]{2,100})")),
    ("Defendant", re.compile(r"(?im)^\s*Defendants?\s*[:\-]+\s*(?:\[?\d+\]?\s*)?[“\"]?([^\n\r,;]{2,100})")),
]

ADVOCATE_CONTEXT = re.compile(r"(?i)advocate|enrol+l?ment|welfare\s+no|high\s+court")

def _clean_value(text: str) -> str:
    return text.strip().rstrip(".,;:")

def _is_advocate_context(document: str, pos: int) -> bool:
    ctx = document[max(0, pos - 180): min(len(document), pos + 180)]
    return bool(ADVOCATE_CONTEXT.search(ctx))

def extract_all(document: str) -> list[Variable]:
    hits: list[Hit] = []
    occupied: set[tuple[int, int, str]] = set()
    tracking_ranges = [(m.start(), m.end()) for m in TRACKING.finditer(document)]
    account_ranges = [(m.start(1), m.end(1)) for _, name, rx in LABEL_PATTERNS if name == "Account Number" for m in rx.finditer(document)]
    def overlaps(ranges, start, end):
        return any(start < b and end > a for a,b in ranges)
    for category, name, regex, group in PATTERNS:
        for m in regex.finditer(document):
            g = m.group(group) if group else m.group(0)
            pos = m.start(group) if group else m.start()
            value = _clean_value(g)
            if not value:
                continue
            # Avoid treating cheque/account identifiers as PINs and fixed advocate contacts as case fields.
            if category == "pin":
                compact = re.sub(r"\s", "", value)
                ctx = document[max(0, pos-35):min(len(document), pos+len(value)+20)].lower()
                if len(compact) != 6 or compact.startswith("0") or overlaps(tracking_ranges, pos, pos+len(value)) or overlaps(account_ranges, pos, pos+len(value)) or any(k in ctx for k in ["account", "cheque", "tracking", "e-way"]):
                    continue
            if category == "mobile" and overlaps(account_ranges, pos, pos+len(value)):
                continue
            if category in {"mobile", "email"} and _is_advocate_context(document, pos):
                continue
            key = (pos, len(value), name)
            if key not in occupied:
                hits.append(Hit(category, name, value, pos))
                occupied.add(key)

    for category, name, regex in LABEL_PATTERNS:
        for m in regex.finditer(document):
            value = _clean_value(m.group(1))
            pos = m.start(1)
            if value:
                hits.append(Hit(category, name, value, pos))

    for m in TRACKING.finditer(document):
        hits.append(Hit("postal_tracking", "Postal Tracking Number", m.group(0).strip(), m.start()))

    # Party role anchors. Extract quoted firm and titled person separately when present.
    person_rx = re.compile(r"(?i)\b(?:Mr|Mrs|Ms)\.?\s+[A-Z][A-Z .\'\-]{3,}")
    for role, regex in PARTY_PATTERNS:
        for m in regex.finditer(document):
            raw = m.group(1).strip()
            base = m.start(1) + (len(m.group(1)) - len(m.group(1).lstrip()))
            quote = re.match(r"[“\"]([^”\"]{2,100})[”\"]", raw)
            if quote:
                firm = quote.group(1).strip()
                hits.append(Hit("party", f"{role} Firm Name", firm, base + quote.start(1)))
            else:
                candidate = re.split(r"\s+(?:Named|Regd\.?|A\s+Regd|Firm|Prop(?:rietor)?\b|Autho\.?\b)", raw, maxsplit=1, flags=re.I)[0].strip(" “”\"")
                if 2 <= len(candidate) <= 100 and not ADVOCATE_CONTEXT.search(candidate):
                    hits.append(Hit("party", f"{role} Name", candidate, document.find(candidate, base, base+len(raw)+2)))
            for pm in person_rx.finditer(raw):
                person = pm.group(0).strip().rstrip(" -")
                if not ADVOCATE_CONTEXT.search(person):
                    hits.append(Hit("party", f"{role} Person Name", person, base + pm.start()))

    # Prefer label-specific hits over generic Date/Amount/PIN/etc at the exact same span.
    generic = {"Date", "Amount", "PIN Code", "Mobile Number", "GSTIN", "IFSC Code", "Account Number"}
    span_specific = {(h.position, h.text.lower()) for h in hits if h.name not in generic}
    hits = [h for h in hits if h.name not in generic or (h.position, h.text.lower()) not in span_specific]

    hits.sort(key=lambda h: h.position)
    variables = [Variable(name=h.name, originalText=h.text, position=h.position, confidenceScore=h.confidence) for h in hits]
    return variables
