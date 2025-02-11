
from pathlib import Path

import yaml

PATH = Path(__file__).parent

with open(PATH / "listing.yml", "r") as f:
    records = next(yaml.safe_load_all(f))

for record in records:
    record["categories"] = [record["group"]]
    if "tags" in record:
        record["categories"].extend(record["tags"])

with open(PATH / "evals.yml", "w") as f:
    yaml.safe_dump(records, f)

