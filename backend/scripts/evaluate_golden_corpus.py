from __future__ import annotations
import json
from pathlib import Path
from app.extractors import extract_all

ROOT=Path(__file__).resolve().parents[1]/"tests"/"golden"
NAME_TO_KEY={
 "Cheque Number":"cheque.number","Cheque Date":"cheque.date","Invoice Number":"invoice.number",
 "Delivery Challan Number":"delivery_challan.number","Reference Number":"reference.number","Email Address":"email",
 "GSTIN":"gstin","Amount":"amount","Plaintiff Name":"party.plaintiff","Defendant Name":"party.defendant",
 "Complainant Name":"party.complainant","Case Number":"case.number","Account Number":"account.number","IFSC Code":"ifsc",
 "HSN Code":"hsn","E-Way Bill Number":"eway.number","Court Number":"court.number","Date":"date",
}
def evaluate():
    tp=fp=fn=0; duplicates=0; total_detected=0; details=[]
    for spec_path in sorted(ROOT.glob("*.json")):
        spec=json.loads(spec_path.read_text(encoding="utf-8"))
        if not spec.get("metric"): continue
        text=spec_path.with_suffix('.txt').read_text(encoding='utf-8')
        expected={(x['semanticKey'],x['sourceText']) for x in spec['fields']}
        raw=extract_all(text)
        detected={(NAME_TO_KEY.get(v.name,v.name.lower().replace(' ','_')),v.original_text) for v in raw}
        # Metrics focus on annotated semantic fields. Any detector output in the fixture
        # that is not annotated is a false positive; missing annotation is a false negative.
        common=expected&detected; tp+=len(common);fp+=len(detected-expected);fn+=len(expected-detected)
        total_detected+=len(raw);duplicates+=len(raw)-len({(v.name,v.original_text,v.position) for v in raw})
        details.append({"fixture":spec_path.stem,"expected":len(expected),"detected":len(detected),"matched":len(common)})
    precision=tp/(tp+fp) if tp+fp else 1.0;recall=tp/(tp+fn) if tp+fn else 1.0;f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    return {"semanticPrecision":precision,"semanticRecall":recall,"semanticF1":f1,"duplicateRate":duplicates/max(1,total_detected),"fixtures":details}
if __name__=='__main__': print(json.dumps(evaluate(),indent=2))
