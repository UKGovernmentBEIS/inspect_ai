from copy import copy

from pydantic import JsonValue

from inspect_ai._util.constants import BASE_64_DATA_REMOVED


def image_url_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if key == "image_url" and isinstance(value, dict) and "url" in value:
        url = str(value.get("url"))
        if url.startswith("data:"):
            value = copy(value)
            value.update(url=BASE_64_DATA_REMOVED)
    return value
