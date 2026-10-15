"""Mitigations for Gemini's MALFORMED_FUNCTION_CALL.

Shared by the native Google provider and the LiteLLM proxy provider.

Gemini sometimes writes a function call as code (`print(default_api.bash(...))`
or `call:default_api:bash{...}`) instead of function-call JSON, and the API
finishes the candidate with MALFORMED_FUNCTION_CALL (see
https://github.com/googleapis/python-genai/issues/430#issuecomment-3592369131).
A system hint makes this less likely; a bounded retry with a corrective
exchange recovers most of the rest.
"""

from textwrap import dedent

# Total request budget (initial attempt + retries) for the internal
# MALFORMED_FUNCTION_CALL retry loop. The stream-restart boundary inside the
# loop must use the same bound: it only fires when another request will run.
MAX_TOOL_CALLING_ATTEMPTS = 3

FUNCTION_CALLING_HINT = dedent("""
    ## Function Calling
    - Do not generate code. Always generate the function call json
    When calling functions, output the function name exactly as defined. Do not prepend 'default_api.' or any other namespace to the function name
    """)
"""System instruction sent alongside function declarations."""

DEFAULT_MALFORMED_FUNCTION_MESSAGE = (
    "a malformed function call (possibly Python code instead of JSON)"
)
"""Stands in for the API's `finishMessage` when it is not available."""

MALFORMED_FUNCTION_RETRY_PROMPT = (
    "Please try again and generate valid function call JSON, not Python code."
)
"""User-role text that follows the model's acknowledgement on a retry."""


def malformed_function_attempt(message: str) -> str:
    """Model-role text acknowledging the malformed call before a retry."""
    return f"I attempted to call a function but produced: {message}"


def malformed_function_apology(message: str) -> str:
    """Text put in the model's mouth once the retries are exhausted."""
    return dedent(f"""
        I seem to have had trouble calling a function and replied with {message}.
        I need to fix this by generating the function call JSON instead.
        """)
