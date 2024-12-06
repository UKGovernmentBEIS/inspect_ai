def as_html_id(prefix: str, text: str) -> str:
    id = "".join(c if c.isalnum() else "-" for c in text.lower())
    return f"{prefix}-{id}" if id[0].isdigit() else id
