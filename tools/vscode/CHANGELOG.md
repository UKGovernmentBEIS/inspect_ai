# Changelog

## 0.3.40

- When running and debuggin Inspect evals, the extension will by default use any environments present in the task folder or parent folders (up to the workspace). To always use the workspace environment, change the 'Use Subdirectory Environments` setting.

## 0.3.39

- Fix an issue that would cause view to be unable to display when using VSCode extension with Inpsect version 0.3.42

## 0.3.38

- Improved behavior when previewing json files using the Inspect viewer.

## 0.3.37

This version includes a signficant rework of the overall workflow for interacting with Inspect. Changes include:

- The Inspect sidebar now includes a section which allows you to browse and open log files in the viewer. 
- The Inspect Viewer is no longer opened automatically when an evaluation is completed. Instead a notification is available to open the viewer. 
- New open log directory command allows you to select a log directory and open the Inspect Viewer for that directory
- Support for the new Inspect `eval` log format. More information [here](https://inspect.ai-safety-institute.org.uk/eval-logs.html#sec-log-format).

## 0.3.36

- Show Inspect version in status bar
- Release with internal changes to support future log viewing features.

## 0.3.33

- Fix bug that prevented run, debug buttons from appearing for tasks whose function declarations spanned more than single line.

## 0.3.32

- Properly resolve log directory when showing log view using `cmd+L`
- Fix an error when reading notebook selection

## 0.3.31

- Don't restrict the availability of the `Open with Inspect View` command based upon the filename.

## 0.3.30

- Further refinement to Inspect View behavior when a task is complete. We will now refresh the viewer without bringing it the foreground when it is already displaying and a task completes. This will ensure that focus is handled correctly in the editor. Use `cmd+shift+L` to bring the viewer to the foreground (or show it if it isn't showing).
- Rename 'Log View Auto' to 'Open Log View' since this better reflects the setting behavior (as it now controls whether the view is initially opened when a task is completed).

## 0.3.29

- Improve behavior of log viewer when a task completes and the view is already displaying
- Evaluation log files which exceed 100MB will be displayed without sample data (since the viewer becomes difficult to work with when files exceed this size).

## 0.3.28

- Fix incorrect environment variable when setting model base url (thx @hanbyul-kim)
- Fix extraneous error that might appear in console output

## 0.3.27

- Minor fix to view rendering across differing versions of Inspect.

## 0.3.26

- Properly preserve focus When showing the log viewer upon task completion.

## 0.3.25

- Poll more frequently to show new log files
- Add support for showing the log viewer in the Positron Viewer

## 0.3.24

- Properly deal with URI encoded characters in log directories when opening a log file

## 0.3.23

- Ensure the log view only opens in the correct window when debugging a task
- Changes to improve performance and usability of large log files

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