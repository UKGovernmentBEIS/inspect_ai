from typing import Any

import panflute as pf # type: ignore
from pydantic import BaseModel

class Reference(BaseModel):
    object: str


def main():

    def reference(options: list[str | dict[str,Any]], data: str, element: pf.Element, doc: pf.Doc) -> pf.Element:
        refs = [Reference(**option) if isinstance(option, dict) else Reference(object=option) for option in options]

        div = pf.Div()
        for ref in refs:
            div.content.append(pf.CodeBlock(ref.object))
        return div

    return pf.run_filter(pf.yaml_filter, tag='yaml', function=reference)

if __name__ == "__main__":
    main()

