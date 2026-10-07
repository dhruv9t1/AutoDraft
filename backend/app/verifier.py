from __future__ import annotations
import re
from collections import defaultdict

PLACEHOLDER_RX=re.compile(r"\{\{[^{}]{1,100}\}\}|\{[A-Za-z][^{}]{0,100}\}|\b(?:TBD|TBC|TO BE FILLED|XXX+)\b|\[TO CONFIRM:[^\]]+\]",re.I)
SAFE_UNCHANGED=re.compile(r"(?i)\b(year|jurisdiction|court|state|country|act|section|statute|law|interest rate|pin code)\b")
AMOUNT_RX=re.compile(r"(?:₹|Rs\.?\s*)\s*[\d,]+(?:\.\d{1,2})?",re.I)
DATE_RX=re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})\b",re.I)

def verify_document(document,variables,submitted_values=None):
 values=submitted_values or {};issues=[]
 def add(severity,code,message,variable=None,evidence=None):
  if severity=="blocker":severity="warning"
  issues.append({"severity":severity,"code":code,"message":message,"variableName":variable,"evidence":evidence})

 for v in variables:
  current=values.get(v.name,v.current_value if v.current_value is not None else "");current="" if current is None else str(current)
  if not current.strip():
   add("warning","EMPTY_OR_UNBOUND_FIELD",f'"{v.name}" is empty or not linked to the document. Review before completion.',v.name);continue
  if current.strip()==(v.original_text or "").strip():
   safe=bool(SAFE_UNCHANGED.search(v.name or ""));add("info" if safe else "warning","UNCHANGED_ALLOWED" if safe else "UNCHANGED_TEMPLATE_VALUE",f'"{v.name}" is unchanged; confirm this is intentional.',v.name,current[:120])
  if current.strip() not in (document or ""):add("warning","VALUE_NOT_IN_DOCUMENT",f'The current value for "{v.name}" is not present in the final document. It may be unbound or stale.',v.name,current[:120])

 for m in PLACEHOLDER_RX.finditer(document or ""):
  add("warning","UNRESOLVED_PLACEHOLDER","Unresolved drafting marker remains in the document.",None,m.group(0)[:160])

 reverse=defaultdict(list)
 for name,value in values.items():
  n=re.sub(r"\s+"," ",str(value)).strip().lower()
  if len(n)>=4 and not re.fullmatch(r"\d{4}",n):reverse[n].append(name)
 for value,names in reverse.items():
  if len(set(names))>=2:add("warning","DUPLICATE_VALUE",f'The same value is used for multiple fields: {", ".join(names[:5])}. Confirm this is intended.',None,value[:120])

 # Advisory consistency signals. They do not decide legal correctness.
 amounts=AMOUNT_RX.findall(document or "")
 normalized_amounts=sorted(set(re.sub(r"\s+","",a.lower()) for a in amounts))
 if len(normalized_amounts)>8:
  add("info","MANY_DISTINCT_AMOUNTS",f"The document contains {len(normalized_amounts)} distinct monetary values; review cross-references for consistency.")
 dates=DATE_RX.findall(document or "")
 if len(set(d.lower() for d in dates))>12:
  add("info","MANY_DISTINCT_DATES",f"The document contains {len(set(d.lower() for d in dates))} distinct dates; review chronology and cross-references.")

 warnings=sum(i["severity"]=="warning" for i in issues)
 return {"status":"review" if warnings else "pass","issues":issues,"blockers":0,"warnings":warnings,"checkedVariables":len(variables)}
