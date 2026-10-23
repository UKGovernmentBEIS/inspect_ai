import re
from pathlib import Path
from typing import Any

WORKFLOW_DIR = Path(__file__).parents[2] / ".github" / "workflows"

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.S)
# The `secrets` context in any form (secrets.X, secrets['X'], toJSON(secrets)),
# but not a property of another context, such as inputs.secrets.
SECRETS_CONTEXT = re.compile(r"(?<![\w.-])secrets(?![\w-])")


def workflow_files(directory: Path = WORKFLOW_DIR) -> list[Path]:
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def references_secrets(node: Any, key: Any = None) -> bool:
    """Whether any expression in a parsed workflow node uses the secrets context."""
    if isinstance(node, dict):
        return any(
            references_secrets(name) or references_secrets(value, name)
            for name, value in node.items()
        )
    if isinstance(node, list):
        return any(references_secrets(item) for item in node)
    if not isinstance(node, str):
        return False
    expressions = EXPRESSION.findall(node)
    # `if:` conditions are expressions without the ${{ }} wrapper.
    if key == "if":
        expressions.append(node)
    return any(SECRETS_CONTEXT.search(expression) for expression in expressions)
