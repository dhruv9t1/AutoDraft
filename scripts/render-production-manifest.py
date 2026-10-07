from __future__ import annotations

import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = root / "word-extension" / "manifest.xml"
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "word-extension" / "manifest.production.xml"

    client_id = required("AUTODRAFT_ENTRA_CLIENT_ID")
    resource = required("AUTODRAFT_ENTRA_RESOURCE_URI")
    origin = required("AUTODRAFT_ADDIN_ORIGIN").rstrip("/")
    if not resource.endswith(client_id):
        raise SystemExit("AUTODRAFT_ENTRA_RESOURCE_URI must end with AUTODRAFT_ENTRA_CLIENT_ID for Office SSO")
    if not origin.startswith("https://"):
        raise SystemExit("AUTODRAFT_ADDIN_ORIGIN must be an https:// origin")

    xml = source.read_text(encoding="utf-8")
    # Production manifests must not point to localhost taskpane/assets.
    xml = xml.replace("https://localhost:3000", origin)
    # Keep SupportUrl/AppDomain aligned with the actual add-in origin.
    xml = xml.replace("https://word-addin.duckdns.org/", origin + "/")
    xml = xml.replace("https://word-addin.duckdns.org", origin)

    if "<WebApplicationInfo>" in xml:
        raise SystemExit("Base manifest unexpectedly already contains WebApplicationInfo")
    marker = "  </VersionOverrides>"
    if marker not in xml:
        raise SystemExit("VersionOverrides closing element not found")
    web_info = f'''  <WebApplicationInfo>\n      <Id>{escape(client_id)}</Id>\n      <Resource>{escape(resource)}</Resource>\n      <Scopes>\n        <Scope>openid</Scope>\n        <Scope>profile</Scope>\n      </Scopes>\n    </WebApplicationInfo>\n'''
    # Microsoft requires WebApplicationInfo to be the last VersionOverrides child.
    xml = xml.replace(marker, web_info + marker, 1)
    output.write_text(xml, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
