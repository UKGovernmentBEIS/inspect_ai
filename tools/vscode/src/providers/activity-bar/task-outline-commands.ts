import {
  TreeView,
  Uri,
  window,
  workspace,
  ConfigurationTarget,
  ExtensionContext,
  ViewColumn,
  commands,
} from "vscode";

import { Command } from "../../core/command";
import {
  TaskOutLineTreeDataProvider,
  TaskTreeItem,
} from "./task-outline-provider";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { pathExists, toAbsolutePath, workspacePath } from "../../core/path";
import { writeFileSync } from "fs";

import { readTemplate, templates } from "../../components/templates";
import { isValidPythonFnName } from "../../core/python";
import {
  documentHasTasks,
  firstTaskRangeForDocument,
  taskRangeForDocument,
} from "../../components/document";
import {
  firstTaskRangeForNotebook,
  isNotebook,
  taskRangeForNotebook,
} from "../../components/notebook";
import { scheduleReturnFocus } from "../../components/focus";
import { InspectViewManager } from "../logview/logview-view";
import { ActiveTaskManager } from "../active-task/active-task-provider";

export class ShowTaskTree implements Command {
  constructor(private readonly provider_: TaskOutLineTreeDataProvider) { }
  async execute(): Promise<void> {
    await workspace
      .getConfiguration("inspect_ai")
      .update("taskListView", "tree", ConfigurationTarget.Global);
    return this.provider_.refresh();
  }
  private static readonly id = "inspect.taskOutlineTree";
  public readonly id = ShowTaskTree.id;
}

export class ShowTaskList implements Command {
  constructor(private readonly provider_: TaskOutLineTreeDataProvider) { }
  async execute(): Promise<void> {
    await workspace
      .getConfiguration("inspect_ai")
      .update("taskListView", "list", ConfigurationTarget.Global);
    return this.provider_.refresh();
  }
  private static readonly id = "inspect.taskOutlineList";
  public readonly id = ShowTaskList.id;
}

export class RunSelectedEvalCommand implements Command {
  constructor(private readonly inspectEvalMgr_: InspectEvalManager) { }
  async execute(treeItem: TaskTreeItem): Promise<void> {
    const path = treeItem.taskPath.path;
    const task =
      treeItem.taskPath.type === "task" ? treeItem.taskPath.name : undefined;

    const evalPromise = this.inspectEvalMgr_.startEval(
      toAbsolutePath(path),
      task,
      false
    );
    const resumeFocusCommand = "inspect_ai.task-outline-view.focus";
    scheduleReturnFocus(resumeFocusCommand);
    await evalPromise;
  }
  private static readonly id = "inspect.runSelectedTask";
  public readonly id = RunSelectedEvalCommand.id;
}

export class DebugSelectedEvalCommand implements Command {
  constructor(private readonly inspectEvalMgr_: InspectEvalManager) { }
  async execute(treeItem: TaskTreeItem): Promise<void> {
    const path = treeItem.taskPath.path;
    const task =
      treeItem.taskPath.type === "task" ? treeItem.taskPath.name : undefined;
    await this.inspectEvalMgr_.startEval(toAbsolutePath(path), task, true);
  }
  private static readonly id = "inspect.debugSelectedTask";
  public readonly id = DebugSelectedEvalCommand.id;
}

export class EditSelectedTaskCommand implements Command {
  constructor(
    private readonly tree_: TreeView<TaskTreeItem>,
    private inspectLogviewManager_: InspectViewManager,
    private activeTaskManager_: ActiveTaskManager
  ) { }
  async execute() {
    if (this.tree_.selection.length > 1) {
      throw new Error("Expected only a single selector for the task tree");
    }

    if (this.tree_.selection.length === 1) {
      const treeItem = this.tree_.selection[0];
      const fileUri = Uri.file(treeItem.taskPath.path);

      // If this is a folder, there is no edit action
      if (treeItem.taskPath.type === "folder") {
        return;
      }

      // If this is a specific task, go right to that
      const task =
        treeItem.taskPath.type === "task" ? treeItem.taskPath.name : treeItem.taskPath.children?.[0].name;

      // Note if/where the logview is showing
      const logViewColumn = this.inspectLogviewManager_.viewColumn();

      // Update the active task
      if (task) {
        await this.activeTaskManager_.updateActiveTask(fileUri, task);
      }

      if (isNotebook(fileUri)) {
        // Compute the cell and position of the task
        const notebookDocument = await workspace.openNotebookDocument(fileUri);

        const findTaskSelection = (task: string | undefined) => {
          if (task) {
            return taskRangeForNotebook(task, notebookDocument);
          } else {
            return firstTaskRangeForNotebook(notebookDocument);
          }
        };
        const taskSelection = findTaskSelection(task);

        // Open the notebook to the specified cell, if any
        const selections = taskSelection?.cell
          ? [taskSelection?.cell]
          : undefined;
        await window.showNotebookDocument(notebookDocument, {
          selections,
          preview: false,
          viewColumn: findTargetViewColumn(logViewColumn),
        });
        if (selections) {
          await commands.executeCommand("notebook.cell.edit");
        }
      } else {
        // Find the task selection for the document (if any)
        const findTaskSelection = async (task: string | undefined) => {
          if (task) {
            return taskRangeForDocument(task, fileUri);
          } else {
            return await firstTaskRangeForDocument(fileUri);
          }
        };
        const selection = await findTaskSelection(task);

        // Show the document
        await window.showTextDocument(fileUri, {
          selection,
          viewColumn: findTargetViewColumn(logViewColumn),
          preview: false,
        });
      }
    }
  }

  public static readonly id = "inspect.editSelectedTask";
  public readonly id = EditSelectedTaskCommand.id;
}

export const findTargetViewColumn = (logViewColumn?: ViewColumn) => {
  if (window.activeTextEditor) {
    // Since there is an active text editor, use its
    // view column
    return window.activeTextEditor.viewColumn;
  } else {
    // Try to find a source editor which contains a task
    const visibleEditors = window.visibleTextEditors;
    const targetEditor = visibleEditors.find((editor) => {
      return documentHasTasks(editor.document);
    });
    if (targetEditor) {
      return targetEditor.viewColumn;
    }

    // There are no editors with tasks, but if there is any active
    // editor, let's use that
    if (visibleEditors.length > 0) {
      return visibleEditors[0].viewColumn;
    }
  }

  // If we get here, there are no editors open at all
  // so as a last ditch, just open next to the logview
  // (if it showing) or in the first column
  // (who knows what it showing in this case)
  if (logViewColumn) {
    // The log view is open, but not any editors
    return ViewColumn.Beside;
  } else {
    // No idea, just go into the first column
    return ViewColumn.One;
  }
};

export class CreateTaskCommand implements Command {
  constructor(private readonly context_: ExtensionContext) { }
  async execute(): Promise<void> {
    // Gather the task name
    const taskName = await window.showInputBox({
      placeHolder: "Name of the task to create",
      prompt: "Task name",
      validateInput: (input) => {
        if (!isValidPythonFnName(input)) {
          return "The task name contains invalid characters.";
        }
        if (pathExists(`${input}.py`)) {
          return `There is already a file in this workspace named '${input}'`;
        }
        return null;
      },
    });

    if (taskName) {
      // force the task name to lower case
      const taskNameLower = taskName.toLowerCase();

      // Read the new task template
      const content = await readTemplate(templates.python_task, this.context_, {
        taskName: taskNameLower,
      });

      // Create ${task}.py, populate it, and open it
      const absPath = workspacePath(`${taskNameLower}.py`);

      writeFileSync(absPath.path, content, { encoding: "utf-8" });

      // Create empty document
      const document = await workspace.openTextDocument(absPath.path);
      await window.showTextDocument(document);
    }
  }

  private static readonly id = "inspect.createTask";
  public readonly id = CreateTaskCommand.id;
}
