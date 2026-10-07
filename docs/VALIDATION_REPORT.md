# Validation report

Checks run in the build environment:
- Python 3.11 compileall over backend app and tests: PASS.
- JavaScript/TypeScript/TSX syntax parse over all 29 source files using Babel TypeScript+JSX parser: PASS, 0 parse failures.
- ZIP integrity/extraction and presence checks for the new verifier, drafting workspace, intake APIs, canonical Word extractor and LEGAL/GENERAL pipeline: PASS.

Environment limitations:
- Full pytest execution could not run because the build VM's system Python does not include pip/pytest.
- Full npm ci/build could not run because the build VM lacks a usable shell for one Microsoft 365 package install script and npm reported transient tar extraction errors. This is an environment/tooling limitation, not a successful build result.
- Real Microsoft Word Office.js end-to-end behavior, the configured Ollama model, PostgreSQL, reverse proxy, and public intake URL require deployment/runtime integration testing on the target machine.

Do not treat the phrase "100% legal accuracy" as a mathematically guaranteed metric. AutoDraft now uses high-recall multi-pass extraction plus fail-visible coverage warnings and a final verifier; unresolved material issues are surfaced for lawyer review rather than silently declared correct.
