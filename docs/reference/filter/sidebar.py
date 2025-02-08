import json
import os
import yaml


# only execute if a reference doc is in the inputs
input_files = os.getenv("QUARTO_PROJECT_INPUT_FILES", "")
if "reference/inspect_ai" not in input_files:
    exit(0)

# register reference docs (this defines their sidebar order)
reference_docs = ["reference/inspect_ai.qmd"] + [
    f"reference/inspect_ai.{doc}"
    for doc in [
        "solver.qmd",
        "tool.qmd",
        "scorer.qmd",
        "model.qmd",
        "dataset.qmd",
        "approval.qmd",
        "log.qmd",
        "util.qmd",
    ]
]

# build sidebar yaml
sidebar = yaml.safe_load("""
website:
  sidebar:
    - title: Reference
      style: docked
      collapse-level: 1
      contents: []
""")
contents_yaml = sidebar["website"]["sidebar"][0]["contents"]

# build index (for cross linking)
index_json: dict[str, str] = {}


# helper to parse reference objects from qmd
def parse_reference_objects(markdown: str) -> list[str]:
    objects: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("### "):
            line = line.removeprefix("### ").removeprefix("beta.")
            objects.append(line.removeprefix("### "))

    return objects


# build for each reference doc
for doc in reference_docs:
    with open(doc, "r") as f:
        objects = parse_reference_objects(f.read())
        refs = [dict(text=o, href=f"{doc}#{o.lower()}") for o in objects]
        for ref in refs:
            index_json[ref["text"]] = ref["href"].removeprefix("reference/")

    # add section to sidebar
    section = doc.removeprefix("reference/").removesuffix(".qmd")
    record = dict(section=section, href=doc, contents=refs)
    contents_yaml.append(record)


# write ref index
index_file = "reference/refs.json"
with open(index_file, "w") as f:
    json.dump(index_json, f, indent=2)

# dump as yaml
sidebar_yaml = yaml.dump(sidebar, sort_keys=False).strip()

# read previous sidebar
sidebar_file = "reference/_sidebar.yml"
if os.path.exists(sidebar_file):
    with open(sidebar_file, "r") as f:
        previous_sidebar_yaml = f.read().strip()
else:
    previous_sidebar_yaml = ""

# only write the file if the sidebar has changed
# (prevents infinite preview render)
if sidebar_yaml != previous_sidebar_yaml:
    with open(sidebar_file, "w") as f:
        f.write(sidebar_yaml)
