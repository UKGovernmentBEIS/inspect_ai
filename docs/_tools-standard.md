Inspect has built-in tools for computing and agentic planning. Computing tools include:

-   [Web Search](tools-standard.qmd#sec-web-search), which uses a search provider (either built in to the model or external) to execute and summarize web searches.
-   [Bash and Python](tools-standard.qmd#sec-bash-and-python) for executing arbitrary shell and Python code (requires a [sandbox](sandboxing.qmd)).
-   [Bash Session](tools-standard.qmd#sec-bash-session) for creating a stateful bash shell that retains its state across calls from the model (requires a [sandbox](sandboxing.qmd)).
-   [Text Editor](tools-standard.qmd#sec-text-editor) which enables viewing, creating and editing text files (requires a [sandbox](sandboxing.qmd)).
-   [Computer](tools-standard.qmd#sec-computer), which provides the model with a desktop computer (viewed through screenshots) that supports mouse and keyboard interaction (requires a [sandbox](sandboxing.qmd)).
-   [Code Execution](tools-standard.qmd#sec-code-execution), which gives models a Python code execution environment hosted within the model provider's infrastructure rather than an Inspect sandbox.
-   [Web Browser](tools-standard.qmd#sec-web-browser), which provides the model with a headless Chromium web browser that supports navigation, history, and mouse/keyboard interactions (requires a [sandbox](sandboxing.qmd)).

Agentic tools include:

-   [Skill](tools-standard.qmd#sec-skill) which provides agent skill specifications to the model with specialized knowledge and expertise for specific tasks (requires a [sandbox](sandboxing.qmd)).
-   [Update Plan](tools-standard.qmd#sec-update-plan) which helps the model tracks steps and progress across longer horizon tasks.
-   [Memory](tools-standard.qmd#sec-memory) which enables storing and retrieving information through a memory file directory.
-   [Think](tools-standard.qmd#sec-think), which provides models the ability to include an additional thinking step as part of getting to its final answer.
-   [Intervention](tools-standard.qmd#sec-intervention), which enable the model to ask questions or send notifications to the user.
