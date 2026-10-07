import base64
import io
import zipfile
import pytest
from app.auth import create_hmac_token, verify_hmac_token, ROLE_ORDER
from app.storage import safe_filename, decode_private_docx

def test_hmac_token_preserves_tenant_user_and_role():
    org="00000000-0000-0000-0000-000000000001";user="00000000-0000-0000-0000-000000000002"
    token=create_hmac_token(secret="secret",organization_id=org,user_id=user,role="lawyer",ttl_seconds=120)
    ctx=verify_hmac_token(token,"secret")
    assert ctx.organization_id==org and ctx.user_id==user and ctx.role=="lawyer"
    assert ROLE_ORDER[ctx.role] >= ROLE_ORDER["staff"]

def test_private_filename_never_preserves_path_components():
    assert safe_filename("../../client/secret.docx")=="secret.docx"
    assert safe_filename("..") == "document"

def test_private_docx_requires_zip_signature_and_size_limit():
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml","<Types/>")
        z.writestr("word/document.xml","<w:document/>")
    raw=buf.getvalue(); good=base64.b64encode(raw).decode()
    assert decode_private_docx(good,max_bytes=len(raw)+10).size_bytes==len(raw)
    with pytest.raises(ValueError): decode_private_docx(base64.b64encode(b"notzip").decode(),max_bytes=100)
    with pytest.raises(OverflowError): decode_private_docx(good,max_bytes=4)
