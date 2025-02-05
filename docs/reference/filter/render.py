

import panflute as pf # type: ignore
from parse import DocAttribute, DocClass, DocFunction, DocObject, DocParameter

# render reference elements
def render_docs(elem: pf.Element, docs: DocObject) -> list[pf.Element]:
   
    elements: list[pf.Element] = [elem]
    elements.append(pf.RawBlock(docs.description, "markdown"))

    # source link
    elements.append(pf.Div(pf.Plain(pf.Link(pf.Str("Source"), url=docs.source)), classes=["source-link"]))

    # declaration
    elements.append(pf.CodeBlock(docs.declaration, classes = ["python", "doc-declaration"]))

    # type specific rendering
    if isinstance(docs, DocFunction):
        elements.append(render_params(docs.parameters))
    elif isinstance(docs, DocClass) and docs.attributes:
        elements.append(pf.Header(pf.Str("Attributes"), level=4))
        elements.append(render_attributes(docs.attributes))
    
    
    # other sections
    for section in docs.text_sections:
        elements.append(pf.RawBlock(section, "markdown"))
        
    # examples
    if docs.examples is not None:
        elements.append(pf.Header(pf.Str("Examples"), level=4))
        elements.append(pf.RawBlock(docs.examples, "markdown"))
    
    # return elements
    return elements

def render_attributes(attribs: list[DocAttribute]) -> pf.Table:
    return render_table(render_header("Attribute", "Description"), attribs)


def render_params(params: list[DocParameter]) -> pf.Table:
    return render_table(render_header("Argument", "Description"), params)
   
def render_table(head: pf.TableHead, elements: list[DocAttribute] | list[DocParameter]) -> pf.Table:
    return pf.Table(
        pf.TableBody(*[render_table_row(el) for el in elements]),
        head=head,
        colspec=[("AlignLeft", 0.25), ("AlignLeft", 0.75)]
    )

def render_params_header() -> pf.TableHead:
    return pf.TableHead(
        pf.TableRow(
            pf.TableCell(pf.Plain(pf.Str("Argument"))),
            pf.TableCell(pf.Plain(pf.Str("Description")))
        )
    )

def render_header(col1: str, col2: str) -> pf.TableHead:
    return pf.TableHead(
        pf.TableRow(
            pf.TableCell(pf.Plain(pf.Str(col1))),
            pf.TableCell(pf.Plain(pf.Str(col2)))
        )
    )

def render_table_row(param: DocParameter | DocAttribute) -> pf.TableRow:
    return pf.TableRow(
        pf.TableCell(pf.Plain(pf.Code(param.name), pf.LineBreak(), pf.Span(pf.Str(param.type), classes=["argument-type"]))),
        pf.TableCell(pf.RawBlock(param.description, format="markdown"))
    )
