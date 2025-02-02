from dataclasses import dataclass
import subprocess
from typing import Any, cast

from griffe import Module
import griffe
import panflute as pf # type: ignore

from parse import DocParseOptions, parse_docs

@dataclass
class Reference:
    object: str


def main():

    # create DocOptions
    module= cast(Module,griffe.load("inspect_ai"))
    sha = subprocess.run(["git", "rev-parse", "HEAD"],capture_output=True).stdout.decode().strip()
    source_url = f"https://github.com/UKGovernmentBEIS/inspect_ai/blob/{sha}/src"


    parse_options = DocParseOptions(
        module=module,
        source_url=source_url
    )

    def reference(options: list[str | dict[str,Any]], data: str, element: pf.Element, doc: pf.Doc) -> pf.Element:
        refs = [Reference(**option) if isinstance(option, dict) else Reference(object=option) for option in options]


        div = pf.Div()
        for ref in refs:
            docs = parse_docs(ref.object, parse_options)
            div.content.append(pf.CodeBlock(f"{docs.name}\n\n{docs.description}"))
        return div

    return pf.run_filter(pf.yaml_filter, tag='reference', function=reference)

if __name__ == "__main__":
    main()

