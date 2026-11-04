"""The README smoke runner must keep finding the README's curl examples.

The live run happens in CI (scripts/readme_smoke.py); this guards the parser so
it can never "pass" by silently finding nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "readme_smoke", Path(__file__).resolve().parents[2] / "scripts" / "readme_smoke.py"
)
assert _SPEC and _SPEC.loader
readme_smoke = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = readme_smoke  # dataclasses resolves annotations via sys.modules
_SPEC.loader.exec_module(readme_smoke)


def test_finds_the_documented_curl_blocks():
    blocks = readme_smoke.extract(readme_smoke.README.read_text())
    scripts = "\n".join(b.script for b in blocks)
    for path in ("/v1/budgets", "/v1/cost/estimate", "/v1/generate", "/v1/usage/summary"):
        assert path in scripts, f"README no longer documents curl for {path}"


def test_markers_are_parsed():
    blocks = readme_smoke.extract(readme_smoke.README.read_text())
    assert any(b.shape and b.json_example for b in blocks), "estimate shape check missing"
    assert any(b.expect_status == 503 and b.expect_code == "GENERATION_DISABLED" for b in blocks)


def test_key_paths_compare_nested_keys():
    assert readme_smoke.key_paths({"a": {"b": 1}, "c": 2}) == {"a", "a.b", "c"}
