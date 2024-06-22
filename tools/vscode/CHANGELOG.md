# Changelog

## 0.3.22

- Improve reliability of opening and viewing log files upon completion of evaluations
- Right click on log files in the Explorer sidebar and select `Open with Inspect View` to view a log file
- Improve reliability of viewing log files when clicking links in the terminal

## 0.3.21

- Properly reactivate log viewer when is has been activated but isn't visible (e.g another tab is visible in its column)

## 0.3.20

- Improve appearance of log view secondary header
- Fix issue where clicking model help could attempt to open more than one window

## 0.3.19

- Fix an issue showing the log viewer when an evaluation completes (specific to Inspect 0.3.10 or later)

## 0.3.18

- Fix issues with task params when type hints are provided
- Improve metric appearance in `inspect view`

## 0.3.17

- Improve `inspect view` title bar treatment

## 0.3.16

- Fix an issue that prevented the extension from loading when the `Pylance` extension was disabled or uninstalled.
- Don't send task params that have been removed from tasks
- Ensure that debugger breakpoints are available outside of user code
- Ensure that evaluations are run from the workspace directory
- Only show the logview in VS Code window that started an eval

## 0.3.14

- Fix issue where the run/debug task option would be disabled for the task configuration pane if a file containing no tasks was being editted.
- Improve Inspect binary detection on Linux platforms

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