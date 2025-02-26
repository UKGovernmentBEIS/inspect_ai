from textual.theme import Theme

inspect_dark = Theme(
    name="inspect-dark",
    primary="#3376CD",
    secondary="#004578",
    accent="#ffa62b",
    warning="#ffa62b",
    error="#ba3c5b",
    success="#408558",
    foreground="#e0e0e0",
)


inspect_light = Theme(
    name="inspect-light",
    primary="#4283CA",
    secondary="#0178D4",
    accent="#ffa62b",
    warning="#ffa62b",
    error="#ba3c5b",
    success="#54B98F",
    surface="#D8D8D8",
    panel="#DFDFDF",
    background="#F8F8F8",
    dark=False,
    variables={
        "footer-key-foreground": "#0178D4",
    },
)
