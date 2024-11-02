import json
import os
from pathlib import Path
from urllib.parse import urlparse

from inspect_ai._util.appdirs import inspect_data_dir

# lightweight tracking of when the last eval task completed
# this enables the view client to poll for changes frequently
# (e.g. every 1 second) with very minimal overhead.


def view_notify_eval(location: str) -> None:
    # do not do this when running under pytest
    if os.environ.get("PYTEST_VERSION", None) is not None:
        return

    file = view_last_eval_file()
    with open(file, "w", encoding="utf-8") as f:
        if not urlparse(location).scheme:
            location = Path(location).absolute().as_posix()

        # Construct a payload with context for the last eval
        payload = {
            "location": location,
        }
        workspace_id = os.environ.get("INSPECT_WORKSPACE_ID")
        if workspace_id:
            payload["workspace_id"] = workspace_id

        # Serialize the payload and write it to the signal file
        payload_json = json.dumps(payload, indent=2)
        f.write(payload_json)


def view_last_eval_time() -> int:
    file = view_last_eval_file()
    if file.exists():
        return int(file.stat().st_mtime * 1000)
    else:
        return 0


def view_data_dir() -> Path:
    return inspect_data_dir("view")


def view_last_eval_file() -> Path:
    return view_data_dir() / "last-eval-result"
