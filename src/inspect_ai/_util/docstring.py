from docstring_parser import Docstring, parse


def parse_docstring(
    docstring: str | None,
) -> Docstring:
    if docstring is None:
        return Docstring()
    parsed_docstring = parse(docstring)
    if parsed_docstring.short_description is None:
        raise ValueError("Docstring must have a short description")
    return parsed_docstring
