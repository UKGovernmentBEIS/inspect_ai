

from textwrap import dedent
import panflute as pf # type: ignore
from parse import DocAttribute, DocClass, DocFunction, DocObject, DocParameter

# render reference elements
def render_docs(elem: pf.Header, docs: DocObject) -> list[pf.Element]:
   
    # remove 'beta'
    title = pf.stringify(elem)
    if title.startswith("beta."):
        title = title.removeprefix("beta.")
        elem.content = [pf.Str(title)]

    elements: list[pf.Element] = [elem]
    elements.append(pf.RawBlock(docs.description, "markdown"))

    # source link
    elements.append(pf.Div(pf.Plain(pf.Link(pf.Str("Source"), url=docs.source)), classes=["source-link"]))

    # declaration
    elements.append(pf.CodeBlock(docs.declaration, classes = ["python", "doc-declaration"]))

    # type specific rendering
    if isinstance(docs, DocFunction):
        if docs.parameters:
            elements.append(render_params(docs.parameters))
    elif isinstance(docs, DocClass):
        if docs.attributes:
            elements.append(pf.Header(pf.Str("Attributes"), level=4))
            elements.append(render_attributes(docs.attributes))
        if docs.methods:
            elements.append(pf.Header(pf.Str("Methods"), level=4))
            elements.append(render_methods(docs.methods))
    


    
    
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
    return render_element_table(render_header("Attribute", "Description"), attribs)

def render_methods(methods: list[DocFunction]) -> pf.Table:
    return pf.DefinitionList(
        *[render_method_definition_item(method) for method in methods]
    )

def render_method_definition_item(method: DocFunction) -> pf.DefinitionItem:
    
    return pf.DefinitionItem(
        [pf.Code(method.name)], 
        [pf.Definition(
            pf.RawBlock(method.description, format="markdown"), 
            pf.CodeBlock(dedent(method.declaration), classes=["python"]),
            render_params(method.parameters)
        )]
    ) 



def render_params(params: list[DocParameter]) -> pf.Table | pf.Div:
    if len(params) > 0:
        return render_element_table(render_header("Argument", "Description"), params)
    else:
        return pf.Div()
  
   
def render_element_table(head: pf.TableHead, elements: list[DocAttribute] | list[DocParameter]) -> pf.Table:
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
