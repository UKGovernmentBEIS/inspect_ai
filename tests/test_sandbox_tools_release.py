"""Contracts shared between the sandbox-tools CI gate and the release wizard.

`slow-tool-tests-release` in build.yml and `scripts/release-sandbox-tools.sh`
each carry a `BUILD_INPUTS` array. The gate uses it to reject published bytes
whose source differs from the PR; the wizard uses the same comparison to decide
when an earlier build can be reused instead of rebuilt. If the two drift, the
wizard could reuse bytes the gate then rejects, burning a version. They must be
identical.
"""

import re
from pathlib import Path

REPO = Path(__file__).parents[1]


def _build_inputs(text: str) -> list[str]:
    matches = re.findall(r"BUILD_INPUTS=\(\n(.*?)\n[ \t]*\)", text, re.S)
    assert len(matches) == 1, f"expected one BUILD_INPUTS array, found {len(matches)}"
    items = []
    for line in matches[0].splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            items.append(line.strip('"').strip("'"))
    return items


def test_build_inputs_match_between_gate_and_wizard() -> None:
    gate = _build_inputs((REPO / ".github" / "workflows" / "build.yml").read_text())
    wizard = _build_inputs((REPO / "scripts" / "release-sandbox-tools.sh").read_text())
    assert gate, "no BUILD_INPUTS entries parsed"
    assert gate == wizard
