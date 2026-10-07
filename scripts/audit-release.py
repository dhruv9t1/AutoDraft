from __future__ import annotations
import os, re, sys, zipfile
from pathlib import Path
BAD_PARTS={".git",".venv","node_modules","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache"}
BAD_SUFFIXES={".pyc",".pyo"}
# Local-only files that must never reach a distributed archive. Both the source
# audit and the archive audit reject them; scripts/make-release-zip.sh excludes
# them so an archive that was built by the packager can never trip this check.
BAD_NAMES={".env",".env.local",".DS_Store"}
PRIVATE_EXT={".docx",".doc",".pdf"}
SECRET_PATTERNS=[re.compile(rb"(?i)(?:api[_-]?key|secret[_-]?key|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),re.compile(rb"sk-[A-Za-z0-9]{20,}")]

def walk_source(root:Path):
    # The release gate audits the source tree after running `npm ci` and
    # `python -m compileall`, and a developer checkout also has a vcs directory.
    # Those locations are excluded from the release ZIP (scripts/make-release-zip.sh),
    # so the source audit must not descend into them or it can never pass. Files that
    # the ZIP would ship are still audited; the ZIP audit below stays strict and rejects
    # any forbidden entry that actually made it into the archive.
    for dir_path,dir_names,file_names in os.walk(root):
        dir_names[:]=[d for d in dir_names if d not in BAD_PARTS and not d.startswith(".release-venv")]
        for name in file_names:
            if Path(name).suffix.lower() in BAD_SUFFIXES: continue
            # BAD_NAMES are local-only files the packager excludes, so a developer
            # checkout that followed backend/SETUP.md (`cp .env.example .env`) must
            # not fail the source audit. The archive audit below still rejects them,
            # which is what actually guards the shipped artifact.
            if name in BAD_NAMES: continue
            yield Path(dir_path)/name

def names_from(path:Path):
    if path.suffix.lower()==".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist(): yield n, (lambda name=n:z.read(name))
    else:
        for f in walk_source(path):
            yield str(f.relative_to(path)), f.read_bytes

def main():
    target=Path(sys.argv[1]).resolve();errors=[]
    for name,reader in names_from(target):
        p=Path(name);parts=set(p.parts)
        if parts&BAD_PARTS or any(part.startswith(".release-venv") for part in p.parts) or p.name in BAD_NAMES or p.suffix.lower() in BAD_SUFFIXES: errors.append(f"forbidden path: {name}");continue
        if p.suffix.lower() in PRIVATE_EXT and "tests" not in parts and "fixtures" not in parts: errors.append(f"private-document extension outside fixtures: {name}")
        if p.suffix.lower() in {".png",".jpg",".jpeg"} and not ({"assets","fixtures","docs"} & parts): errors.append(f"unexpected image outside assets/fixtures: {name}")
        if p.suffix.lower() in {".py",".ts",".tsx",".js",".json",".md",".env",".txt",".yml",".yaml",".sh"}:
            try:data=reader()
            except Exception:continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(data): errors.append(f"possible secret: {name}");break
            # Word add-in privacy guard: production source must not bypass the
            # privacy logger or reintroduce known document-value diagnostics.
            normalized=name.replace("\\", "/")
            if normalized.startswith("word-extension/src/") and p.suffix.lower() in {".ts", ".tsx"}:
                if not normalized.endswith("services/logger.ts") and re.search(rb"\bconsole\.(?:log|info|warn|error|debug)\s*\(", data):
                    errors.append(f"direct frontend console logging bypasses privacy logger: {name}")
                forbidden_frontend=[
                    b"Existing values: ${JSON.stringify(existingValues)}",
                    b"Filtered values for form: ${JSON.stringify(filteredValues)}",
                    b"Manual add variable: ",
                    b"Replacing \"${placeholderText}\" with \"${replacementText}\"",
                ]
                if any(marker in data for marker in forbidden_frontend):
                    errors.append(f"sensitive frontend diagnostic pattern: {name}")
            # Current documentation must not silently regress to the retired
            # Rust/backend or gpt-oss deployment assumptions. Historical records
            # are permitted only under docs/archive or .planning.
            if p.suffix.lower()==".md" and "docs/archive" not in normalized and ".planning/" not in normalized:
                for marker in (b"### Backend (Rust)", b"gpt-oss:120b", b"cargo run"):
                    if marker in data:
                        errors.append(f"superseded architecture/model guidance outside archive: {name}")
                        break
    if errors:
        print("RELEASE AUDIT FAILED");print("\n".join(errors));return 1
    print("RELEASE AUDIT PASSED");return 0
if __name__=="__main__":raise SystemExit(main())
