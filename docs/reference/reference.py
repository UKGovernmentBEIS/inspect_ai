from dataclasses import dataclass, field
import subprocess
from typing import Any, cast

from griffe import Module
import griffe
import panflute as pf # type: ignore

from parse import DocFunction, DocParseOptions, parse_docs

@dataclass
class Reference:
    object: str
    description: str | None = field(default=None)


def main():

    # create DocOptions
    module= cast(Module,griffe.load("inspect_ai"))
    sha = subprocess.run(["git", "rev-parse", "HEAD"],capture_output=True).stdout.decode().strip()
    source_url = f"https://github.com/UKGovernmentBEIS/inspect_ai/blob/{sha}/src"


    parse_options = DocParseOptions(
        module=module,
        source_url=source_url
    )

    def reference(elem: pf.Element, doc: pf.Doc):
        if isinstance(elem, pf.Header) and elem.level == 3:
            title = pf.stringify(doc.metadata["title"])
            if title.startswith("inspect_ai."):
                # get target object
                module = title.removeprefix("inspect_ai.")
                object = f"{module}.{pf.stringify(elem.content)}"

                # render docs
                elements: list[pf.Element] = []
                docs = parse_docs(object, parse_options)
                elements.append(elem)
                elements.append(pf.RawBlock(docs.description, "markdown"))
                if isinstance(docs, DocFunction):
                    elements.append(pf.CodeBlock(docs.declaration, classes = ["python"]))
                return elements

    return pf.run_filter(reference)

if __name__ == "__main__":
    main()

