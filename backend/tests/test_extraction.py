from app.extractors import extract_all
from app.post_processing import finalize

DOC = '''
Complainant: “NAVKAR FABRICS”, Named Regd. Firm
Accused: [1] “GREENLINE GARMENTS” [2] Mr. RAHUL PATEL Proprietor
GSTIN / UIN No.: 24 AAAAA 1234 A1Z5
SHOP / OFFICE: 21 Market Road, Ahmedabad, PIN: 38 00 15.
Mobile No.: +91 98765 43210
Cheque Number : 000052
Cheque Date: 13/11/2025
Amount Rs.: 1,80,199=00
IFSC CODE: HDFC0000890
Account No.: 50 2000 711 54 987
Invoice No.: 192, Delivery Challan No.: 192, E-Way Bill No.: 6517 2477 3042, HSN: 48109900
Tracking No.: EG 459 625 047 IN
'''

def test_corpus_fields_are_detected():
    vars_ = finalize(extract_all(DOC), DOC)
    names = [v.name for v in vars_]
    values = [v.original_text for v in vars_]
    assert "Cheque Number" in names
    assert "000052" in values
    assert any("Invoice Number" in n for n in names)
    assert any("Delivery Challan Number" in n for n in names)
    assert values.count("192") >= 2, "same value in distinct semantic fields must survive"
    assert "EG 459 625 047 IN" in values

def test_pin_with_leading_zero_is_not_pin():
    vars_ = extract_all("Cheque No.: 000129")
    assert not any(v.name == "PIN Code" and v.original_text == "000129" for v in vars_)
