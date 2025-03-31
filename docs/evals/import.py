
from pathlib import Path

import yaml

PATH = Path(__file__).parent

with open(PATH / "listing.yml", "r") as f:
    records = next(yaml.safe_load_all(f))
  
group_order = {
    "Coding": 1,
    "Assistants": 2,
    "Cybersecurity": 3,
    "Safeguards": 4,
    "Mathematics": 5,
    "Reasoning": 6,
    "Knowledge": 7,
    "Multimodal": 8
}
    
records = sorted(records, key=lambda x: group_order.get(x["group"], float('inf')))    

for record in records:
    record["categories"] = [record["group"]]
    if "tags" in record:
        record["categories"].extend(record["tags"])
    record["tasks"] = [task["name"] for task in record["tasks"]]
  

with open(PATH / "evals.yml", "w") as f:
    yaml.safe_dump(records, f)

