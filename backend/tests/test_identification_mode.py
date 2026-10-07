from app.identification_mode import IdentificationMode,classify_document,extract_label_value_candidates
def test_cv_is_general_even_with_legal_interest(): assert classify_document('M.Sc AI. Interested in legal/domain-specific AI applications.')==IdentificationMode.GENERAL
def test_legal_is_legal(): assert classify_document('IN THE COURT OF CJM\nComplainant: A\nAccused: B\nComplaint under Section 138 of Negotiable Instruments Act')==IdentificationMode.LEGAL
def test_label_value_recall():
 vals=extract_label_value_candidates('Cheque Number : 000135\nCustom Field: ABC-123')
 assert any(v.original_text=='000135' for v in vals) and any(v.original_text=='ABC-123' for v in vals)
