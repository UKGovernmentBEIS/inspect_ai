Inspect has built-in tools for computing and agentic planning. Computing tools include:

-   [Web Search](tools-standard.qmd#sec-web-search), which uses a search provider (either built in to the model or external) to execute and summarize web searches.
-   [Bash and Python](tools-standard.qmd#sec-bash-and-python) for executing arbitrary shell and Python code.
-   [Bash Session](tools-standard.qmd#sec-bash-session) for creating a stateful bash shell that retains its state across calls from the model.
-   [Text Editor](tools-standard.qmd#sec-text-editor) which enables viewing, creating and editing text files.
-   [Computer](tools-standard.qmd#sec-computer), which provides the model with a desktop computer (viewed through screenshots) that supports mouse and keyboard interaction.
-   [Code Execution](tools-standard.qmd#sec-code-execution), which gives models a sandboxed Python code execution environment running within the model provider's infrastructure.
-   [Web Browser](tools-standard.qmd#sec-web-browser), which provides the model with a headless Chromium web browser that supports navigation, history, and mouse/keyboard interactions.

Agentic tools include:

-   [Skill](tools-standard.qmd#sec-skill) which provides agent skill specifications to the model with specialized knowledge and expertise for specific tasks.
-   [Update Plan](tools-standard.qmd#sec-update-plan) which helps the model tracks steps and progress across longer horizon tasks.
-   [Memory](tools-standard.qmd#sec-memory) which enables storing and retrieving information through a memory file directory.
-   [Think](tools-standard.qmd#sec-think), which provides models the ability to include an additional thinking step as part of getting to its final answer.

