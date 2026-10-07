from __future__ import annotations
import re
from enum import Enum
from .models import Variable
class IdentificationMode(str,Enum): LEGAL="legal"; GENERAL="general"
STRONG_LEGAL=("in the court of","hon'ble court","hon’ble court","plaintiff","defendant","complainant","accused","petitioner","respondent","cause of action","jurisdiction of court","legal demand notice","negotiable instruments act","criminal complaint","civil suit","written statement","affidavit","case no.","case number","memo of parties")
WEAK_LEGAL=("section ","u/s"," r/w ","advocate"," court","petition","notice","cheque no","fir no","statutory","prosecution","decree","injunction","summons","complaint","counsel")
def classify_document(text:str)->IdentificationMode:
 s=" "+re.sub(r"\s+"," ",(text or "").lower())+" "; strong=sum(x in s for x in STRONG_LEGAL); weak=sum(x in s for x in WEAK_LEGAL)
 return IdentificationMode.LEGAL if strong>=2 or (strong>=1 and weak>=2) or weak>=5 else IdentificationMode.GENERAL
LEGAL_SYSTEM_PROMPT=r"""You are AutoDraft's high-recall LEGAL variable detector. Find EVERY matter-specific value that would normally change when this legal document is reused for another client, opponent, transaction, notice, complaint, suit, petition or proceeding. Coverage is more important than conservatism. Inspect every supplied character including table-like rows and headers/footers present in the input. Extract parties/roles, addresses/contact details, case/court/police references, matter-specific advocates, every date/deadline, amounts, cheque/bank/account/IFSC data, invoice/order/challan/LR/e-way/postal identifiers, business identifiers, places, signing data, and unfamiliar labelled values. originalText MUST be an exact character-for-character substring. Never invent or paraphrase. Same textual value at different positions may be different fields. Skip only genuine boilerplate/headings/page markers/fixed letterhead. Use precise variableName labels. Return only the required JSON object."""
GENERAL_SYSTEM_PROMPT=r"""You are AutoDraft's GENERAL reusable-document FIELD CANDIDATE detector. GENERAL means every non-legal document; never assume a CV, invoice, HR form, agreement, application, or any other fixed schema. Read the ENTIRE supplied chunk. For each potential VALUE ask: if this document were reused for a different person, organisation, transaction, project, application, event, period, or recipient, would this exact value normally be replaced while the surrounding document structure stays the same? If yes, return it as a candidate.

Important exclusions:
- Do NOT return section headings, structural headings, labels/captions/keys, boilerplate, instructions, narrative prose, or static descriptive text merely because the words could theoretically vary.
- A name, organisation, location, date, amount, phone, email, URL, qualification, project title, skill, identifier, or number is NOT automatically a field; context must indicate that it is an instance-specific value.
- For label/value layouts return only the VALUE, never the label plus value.
- Prefer complete coherent values over fragments. Never invent, paraphrase, repair, or expand source text.
- originalText MUST be an exact character-for-character substring of the supplied document chunk, and position should identify that occurrence within the chunk whenever possible.
Return only the required JSON object."""
def prompt_for_mode(mode): return LEGAL_SYSTEM_PROMPT if mode==IdentificationMode.LEGAL else GENERAL_SYSTEM_PROMPT
LABEL_VALUE=re.compile(r"(?m)^[ \t]*([A-Za-z][A-Za-z0-9 /&().,_\-]{1,55}?)[ \t]*(?::|[-–—]|\t)[ \t]*([^\n\r]{1,180})$")
GENERIC_PATTERNS=[("Email Address",re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")),("Mobile Number",re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?[6-9](?:[\s\-]?\d){9}(?!\d)")),("URL",re.compile(r"(?i)\bhttps?://[^\s<>]+|\bwww\.[^\s<>]+")),("Date",re.compile(r"(?<!\d)\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}(?!\d)"))]
def _clean_label(label):
 label=re.sub(r"\s+"," ",label).strip(" .:-\t"); return " ".join(w[:1].upper()+w[1:] for w in label.split())[:80] or "Variable"
def extract_label_value_candidates(document):
 out=[];seen=set()
 for m in LABEL_VALUE.finditer(document or ""):
  label,value=m.group(1),m.group(2).strip()
  if not value or re.fullmatch(r"[-_=.:/\s]+",value): continue
  pos=m.start(2)+(len(m.group(2))-len(m.group(2).lstrip()));key=(pos,value.lower())
  if key in seen:continue
  seen.add(key);out.append(Variable(name=_clean_label(label),originalText=value,position=pos,confidenceScore=.86))
 return out
def extract_general_deterministic(document):
 out=extract_label_value_candidates(document);seen={(v.position,v.original_text.lower()) for v in out}
 for name,rx in GENERIC_PATTERNS:
  for m in rx.finditer(document or ""):
   text=m.group(0).strip().rstrip(".,;");key=(m.start(),text.lower())
   if text and key not in seen:seen.add(key);out.append(Variable(name=name,originalText=text,position=m.start(),confidenceScore=.97))
 return out
def coverage_warnings(document,variables,mode):
 if mode!=IdentificationMode.LEGAL:return []
 covered=[(v.position,v.position+len(v.original_text)) for v in variables];warnings=[]
 for m in LABEL_VALUE.finditer(document or ""):
  a,b=m.start(2),m.end(2)
  if not any(a<y and b>x for x,y in covered):warnings.append(f"Uncovered labelled value near: {m.group(1).strip()[:60]}")
 return warnings[:25]
