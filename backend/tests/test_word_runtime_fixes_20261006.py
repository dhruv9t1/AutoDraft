from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORD = ROOT / "word-extension"


def test_es5_word_build_enables_downlevel_iteration():
    tsconfig = json.loads((WORD / "tsconfig.json").read_text())
    assert tsconfig["compilerOptions"]["target"] == "es5"
    assert tsconfig["compilerOptions"]["downlevelIteration"] is True


def test_existing_word_context_is_reused_without_invalid_word_run_overload():
    source = (WORD / "src/services/word/operationQueue.ts").read_text()
    assert "Word.run(context, callback)" not in source
    assert "wordOperationQueue.run(() => callback(context))" in source


def test_word_search_options_use_officejs_compatible_cast():
    source = (WORD / "src/services/word/bindingService.ts").read_text()
    assert "const EXACT_SEARCH_OPTIONS = {" in source
    assert "} as Word.SearchOptions;" in source


def test_taskpane_runtime_diagnostics_and_hmr_render_are_safe():
    source = (WORD / "src/taskpane/index.tsx").read_text()
    assert 'window.addEventListener("error"' in source
    assert 'window.addEventListener("unhandledrejection"' in source
    assert 'error as logError' in source
    assert 'console.error' not in source
    assert "root?.render(NextApp)" not in source
    assert "<NextApp />" in source


def test_word_dev_server_avoids_opaque_office_runtime_overlay():
    source = (WORD / "webpack.config.js").read_text()
    assert "hot: false" in source
    assert "runtimeErrors: false" in source
    assert "errors: true" in source


def test_debug_start_performs_best_effort_previous_session_cleanup():
    package = json.loads((WORD / "package.json").read_text())
    source = (WORD / "scripts/prepare-debug-start.js").read_text()
    assert package["scripts"]["prestart"] == "node scripts/prepare-debug-start.js"
    assert '["stop", "manifest.xml"]' in source
    assert "process.exit(0)" in source
    assert "com.microsoft.Word" in source
    assert "candidateStat.ino === manifestStat.ino" in source


def test_debug_tool_versions_match_the_mac_build_verified_versions():
    package = json.loads((WORD / "package.json").read_text())
    dev = package["devDependencies"]
    assert dev["office-addin-debugging"] == "7.0.1"
    assert dev["office-addin-manifest"] == "3.0.1"
    assert dev["webpack-dev-server"] == "5.2.6"
    assert dev["copy-webpack-plugin"] == "14.0.0"
