"""Run the README's curl examples against a live server and check the results.

Documentation that fails on the first copy-paste is the most expensive bug a
teaching repo can have, so CI executes the README itself.

Every ```bash block that contains ``curl`` is run, in order, with ``bash``.
Each curl call must return 2xx unless the block is preceded by an HTML comment
(invisible when the README renders):

    <!-- smoke-expect: 503 GENERATION_DISABLED -->   expected status + error code
    <!-- smoke-shape -->                              the response's JSON keys must
                                                      match the next ```json block

Usage (server already running with the dev keys and seeded pricing):
    python scripts/readme_smoke.py --base-url http://localhost:8000

Needs only the standard library, bash and curl. Not idempotent: the budget
example fails on a second run against the same database (409).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
DOC_BASE_URL = "http://localhost:8000"
FENCE = re.compile(
    r"(?P<marker>(?:<!--\s*smoke[^>]*-->\s*\n)*)```(?P<lang>\w+)\n(?P<body>.*?)```", re.S
)
EXPECT = re.compile(r"smoke-expect:\s*(\d{3})(?:\s+(\w+))?")

# Replaces `curl` for the duration of a block: records each call's body and
# HTTP status so the checker can read them back.
PRELUDE = r"""
__n=0
curl() {
  __n=$((__n + 1))
  command curl -sS -o "$SMOKE_DIR/$__n.body" -w '%{http_code}' "$@" > "$SMOKE_DIR/$__n.status"
}
"""


@dataclass
class Block:
    script: str
    expect_status: int | None
    expect_code: str | None
    shape: bool
    json_example: dict | None


def extract(readme: str) -> list[Block]:
    fences = list(FENCE.finditer(readme))
    blocks: list[Block] = []
    for i, m in enumerate(fences):
        if m["lang"] != "bash" or "curl" not in m["body"]:
            continue
        marker = m["marker"]
        expect = EXPECT.search(marker)
        shape = "smoke-shape" in marker
        example = None
        if shape:
            nxt = fences[i + 1] if i + 1 < len(fences) else None
            if nxt is None or nxt["lang"] != "json":
                raise SystemExit("smoke-shape block must be followed by a ```json block")
            example = json.loads(nxt["body"])
        blocks.append(
            Block(
                script=m["body"],
                expect_status=int(expect[1]) if expect else None,
                expect_code=expect[2] if expect else None,
                shape=shape,
                json_example=example,
            )
        )
    return blocks


def key_paths(value: object, prefix: str = "") -> set[str]:
    """Dotted paths of every object key, so documented and real shapes compare."""
    if not isinstance(value, dict):
        return set()
    paths: set[str] = set()
    for k, v in value.items():
        paths.add(f"{prefix}{k}")
        paths |= key_paths(v, f"{prefix}{k}.")
    return paths


def run_block(block: Block, base_url: str, index: int) -> list[str]:
    """Run one block; return a list of problems (empty = pass)."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        script = PRELUDE + block.script.replace(DOC_BASE_URL, base_url.rstrip("/"))
        proc = subprocess.run(  # noqa: S603 (README is trusted repo input)
            ["bash", "-c", script],  # noqa: S607 (fixed PATH below)
            env={"SMOKE_DIR": tmp, "PATH": "/usr/local/bin:/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            return [f"block {index}: bash exited {proc.returncode}: {proc.stderr.strip()}"]
        statuses = sorted(Path(tmp).glob("*.status"), key=lambda p: int(p.stem))
        if not statuses:
            return [f"block {index}: no curl call was recorded"]
        for status_file in statuses:
            status = int(status_file.read_text())
            raw = status_file.with_suffix(".body").read_text()
            label = f"block {index} call {status_file.stem}"
            want = block.expect_status
            if want is None and not 200 <= status < 300:
                problems.append(f"{label}: expected 2xx, got {status}: {raw[:300]}")
                continue
            if want is not None and status != want:
                problems.append(f"{label}: expected {want}, got {status}: {raw[:300]}")
                continue
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                problems.append(f"{label}: response is not JSON: {raw[:300]}")
                continue
            if block.expect_code and body.get("error", {}).get("code") != block.expect_code:
                problems.append(f"{label}: expected error code {block.expect_code}, got {body}")
            if block.shape and block.json_example is not None:
                documented, actual = key_paths(block.json_example), key_paths(body)
                if documented != actual:
                    problems.append(
                        f"{label}: README JSON keys differ from the real response "
                        f"(only in README: {sorted(documented - actual)}, "
                        f"only in response: {sorted(actual - documented)})"
                    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=DOC_BASE_URL)
    args = parser.parse_args()

    blocks = extract(README.read_text())
    if not blocks:
        print("FAIL: no curl blocks found in README.md (parser or README broke)")
        return 1

    failures: list[str] = []
    failed_blocks = 0
    for i, block in enumerate(blocks, start=1):
        first = block.script.strip().splitlines()[0][:70]
        problems = run_block(block, args.base_url, i)
        print(f"{'FAIL' if problems else 'ok  '} block {i}: {first}")
        failed_blocks += bool(problems)
        failures += problems

    for problem in failures:
        print(f"  - {problem}")
    print(f"\n{len(blocks) - failed_blocks}/{len(blocks)} README blocks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
