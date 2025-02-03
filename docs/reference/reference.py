from dataclasses import dataclass, field
import subprocess
from typing import Any, cast

from griffe import Module
import griffe
import panflute as pf # type: ignore

from parse import DocFunction, DocParseOptions, parse_docs

def main():

    # create options
    module= cast(Module,griffe.load("inspect_ai"))
    sha = subprocess.run(["git", "rev-parse", "HEAD"],capture_output=True).stdout.decode().strip()
    source_url = f"https://github.com/UKGovernmentBEIS/inspect_ai/blob/{sha}/src"
    parse_options = DocParseOptions(
        module=module,
        source_url=source_url
    )

    # render reference elements
    def ref_elements(module: str, elem: pf.Element) -> list[pf.Element]:
        # get target object
        object = f"{module}.{pf.stringify(elem.content)}"

        # render doc header
        elements: list[pf.Element] = []
        docs = parse_docs(object, parse_options)
        elements.append(elem)
        elements.append(pf.RawBlock(docs.description, "markdown"))

        # type specific rendering
        if isinstance(docs, DocFunction):
            elements.append(pf.CodeBlock(docs.declaration, classes = ["python"]))
        
        # return elements
        return elements

    # convert h3 into reference
    def reference(elem: pf.Element, doc: pf.Doc):
        if isinstance(elem, pf.Header) and elem.level == 3:
            title = pf.stringify(doc.metadata["title"])
            if title.startswith("inspect_ai."):
                module = title.removeprefix("inspect_ai.")
                return ref_elements(module, elem)

    return pf.run_filter(reference)

if __name__ == "__main__":
    main()

