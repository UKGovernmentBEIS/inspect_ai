# Changelog

## 0.3.13

-   Ensure that inspect CLI is in the path for terminals using a global Python environment
-   Add 'Show Logs' command to the environment panel.
-   Improve models in the environment panel
    -   Display literal provider names (rather than pretty names)
    -   Remember the last used model for each provider
    -   Allow free-form provide in model
    -   Add autocomplete for Ollama
-   Fix 'Restart' when debugging to properly restart the Inspect debugging session
-   Improve performance loading task tree, selecting tasks within outline, and navigating to tasks
-   Improve task selection behavior when the activity bar is first shown