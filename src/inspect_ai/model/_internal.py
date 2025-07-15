import base64
import json
import re

from pydantic import JsonValue


def parse_content_with_internal(
    content: str,
) -> tuple[str, JsonValue | None]:
    content_text = content

    internal_pattern = r"<internal>(.*?)</internal>"
    if not (
        internal_match := re.search(
            r"<internal>(.*?)</internal>", content_text, re.DOTALL
        )
    ):
        return content, None

    return re.sub(
        internal_pattern, "", content_text, flags=re.DOTALL
    ).strip(), json.loads(base64.b64decode(internal_match.group(1)).decode("utf-8"))
