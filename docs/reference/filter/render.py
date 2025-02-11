from textwrap import dedent
import panflute as pf  # type: ignore
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
    elements.append(render_source_link(docs))

    # declaration
    elements.append(
        pf.CodeBlock(docs.declaration, classes=["python", "doc-declaration"])
    )

    # type specific rendering
    if isinstance(docs, DocFunction):
        if docs.parameters:
            elements.append(render_params(docs.parameters))
    elif isinstance(docs, DocClass):
        if docs.attributes:
            elements.append(pf.Header(pf.Str("Attributes"), level=4))
            elements.append(render_attributes(docs.attributes))
        if docs.methods:
            elements.append(
                pf.Header(pf.Str("Methods"), level=4, classes=["class-methods"])
            )
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
    return render_element_list(attribs)


def render_methods(methods: list[DocFunction]) -> pf.DefinitionList:
    return pf.DefinitionList(
        *[render_method_definition_item(method) for method in methods]
    )


def render_source_link(object: DocObject) -> pf.Div:
    return pf.Div(
        pf.Plain(pf.Link(pf.Str("Source"), url=object.source)), classes=["source-link"]
    )


def render_method_definition_item(method: DocFunction) -> pf.DefinitionItem:
    return pf.DefinitionItem(
        [pf.Str(method.name)],
        [
            pf.Definition(
                pf.RawBlock(method.description, format="markdown"),
                render_source_link(method),
                pf.CodeBlock(dedent(method.declaration), classes=["python"]),
                render_params(method.parameters),
            )
        ],
    )


def render_params(params: list[DocParameter]) -> pf.Table | pf.Div:
    if len(params) > 0:
        return render_element_list(params)
    else:
        return pf.Div()


def render_element_list(
    elements: list[DocAttribute] | list[DocParameter],
) -> pf.DefinitionList:
    return pf.DefinitionList(
        *[render_element_definition_item(element) for element in elements]
    )


def render_element_definition_item(
    element: DocAttribute | DocParameter,
) -> pf.DefinitionItem:
    return pf.DefinitionItem(
        [pf.Code(element.name, classes=["ref-definition"]), pf.Space(), render_element_type(element.type)],
        [pf.Definition(pf.RawBlock(element.description, format="markdown"))],
    )


def render_element_type(type: str) -> pf.Span:
    element_type: list[pf.Inline] = []
    for token, token_type in tokenize_type_declaration(type):
        if token_type == "text":
            element_type.append(pf.Str(token))
        else:
            element_type.append(pf.Span(pf.Str(token), classes=["element-type-name"]))

    return pf.Span(*element_type, classes=["element-type"])


def render_params_header() -> pf.TableHead:
    return pf.TableHead(
        pf.TableRow(
            pf.TableCell(pf.Plain(pf.Str("Argument"))),
            pf.TableCell(pf.Plain(pf.Str("Description"))),
        )
    )


def render_header(col1: str, col2: str) -> pf.TableHead:
    return pf.TableHead(
        pf.TableRow(
            pf.TableCell(pf.Plain(pf.Str(col1))), pf.TableCell(pf.Plain(pf.Str(col2)))
        )
    )


def tokenize_type_declaration(type_str: str) -> list[tuple[str, str]]:
    common_types = {
        "Any",
        "Dict",
        "List",
        "Set",
        "Tuple",
        "Optional",
        "Union",
        "Callable",
        "Iterator",
        "Iterable",
        "Generator",
        "Type",
        "TypeVar",
        "Generic",
        "Protocol",
        "NamedTuple",
        "TypedDict",
        "Literal",
        "Final",
        "ClassVar",
        "NoReturn",
        "Never",
        "Self",
        "int",
        "str",
        "float",
        "bool",
        "bytes",
        "object",
        "None",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Awaitable",
        "Coroutine",
        "AsyncIterator",
        "AsyncIterable",
        "ContextManager",
        "AsyncContextManager",
        "Pattern",
        "Match",
    }

    tokens = []
    current_token = ""

    def add_token(token: str, force_type: str | None = None) -> None:
        """Helper function to add a token with its classified type."""
        if not token:
            return

        if force_type:
            token_type = force_type
        elif token in common_types or (token[0].isupper() and token.isalnum()):
            token_type = "type"
        else:
            token_type = "text"

        tokens.append((token, token_type))

    i = 0
    while i < len(type_str):
        char = type_str[i]

        # Handle whitespace
        if char.isspace():
            add_token(current_token)
            add_token(char, "text")
            current_token = ""

        # Handle special characters
        elif char in "[](),|":
            add_token(current_token)
            add_token(char, "text")
            current_token = ""

        # Build up identifier
        else:
            current_token += char

        i += 1

    # Add any remaining token
    add_token(current_token)

    return tokens
