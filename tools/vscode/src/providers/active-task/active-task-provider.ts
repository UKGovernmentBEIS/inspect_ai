import {
  Event,
  EventEmitter,
  ExtensionContext,
  NotebookEditor,
  Position,
  Selection,
  TextDocument,
  TextEditorSelectionChangeEvent,
  Uri,
  commands,
  window,
  workspace,
} from "vscode";
import {
  DebugActiveTaskCommand,
  RunActiveTaskCommand,
} from "./active-task-command";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { Command } from "../../core/command";
import { DocumentTaskInfo, readTaskData } from "../../components/task";
import { cellTasks, isNotebook } from "../../components/notebook";
import { debounce } from "lodash";

// Activates the provider which tracks the currently active task (document and task name)
export function activateActiveTaskProvider(
  inspectEvalManager: InspectEvalManager,
  context: ExtensionContext
): [Command[], ActiveTaskManager] {
  const activeTaskManager = new ActiveTaskManager(context);

  const commands = [
    new RunActiveTaskCommand(activeTaskManager, inspectEvalManager),
    new DebugActiveTaskCommand(activeTaskManager, inspectEvalManager),
  ];
  return [commands, activeTaskManager];
}

// Fired when the active task changes
export interface ActiveTaskChangedEvent {
  activeTaskInfo?: DocumentTaskInfo;
}

// Tracks task information for the current editor
export class ActiveTaskManager {
  constructor(context: ExtensionContext) {
    // Listen for the editor changing and update task state
    // when there is a new selection
    context.subscriptions.push(
      window.onDidChangeTextEditorSelection(
        debounce(
          async (event: TextEditorSelectionChangeEvent) => {
            await this.updateActiveTaskWithDocument(
              event.textEditor.document,
              event.selections[0]
            );
          },
          300,
          { trailing: true }
        )
      )
    );

    context.subscriptions.push(
      window.onDidChangeActiveNotebookEditor(
        debounce(async (event: NotebookEditor | undefined) => {
          if (window.activeNotebookEditor && window.activeNotebookEditor.selection) {
            const cell = event?.notebook.cellAt(
              window.activeNotebookEditor.selection.start
            );
            await this.updateActiveTaskWithDocument(
              cell?.document,
              new Selection(new Position(0, 0), new Position(0, 0))
            );
          }
        }, 300, { trailing: true })
      ));

    context.subscriptions.push(
      window.onDidChangeActiveTextEditor(async (event) => {
        if (event) {
          await this.updateActiveTaskWithDocument(event.document);
        }
      })
    );
  }
  private activeTaskInfo_: DocumentTaskInfo | undefined;
  private readonly onActiveTaskChanged_ =
    new EventEmitter<ActiveTaskChangedEvent>();

  // Event to be notified when task information changes
  public readonly onActiveTaskChanged: Event<ActiveTaskChangedEvent> =
    this.onActiveTaskChanged_.event;

  // Get the task information for the current selection
  public getActiveTaskInfo(): DocumentTaskInfo | undefined {
    return this.activeTaskInfo_;
  }

  // Refresh the task information for the current editor
  public async refresh() {
    const currentSelection = window.activeTextEditor?.selection;
    const currentDocument = window.activeTextEditor?.document;
    await this.updateActiveTaskWithDocument(currentDocument, currentSelection);
  }

  private async updateTask(activeTaskInfo?: DocumentTaskInfo) {
    let taskActive = false;
    if (activeTaskInfo) {
      this.setActiveTaskInfo(activeTaskInfo);
      taskActive = activeTaskInfo !== undefined;
      await commands.executeCommand(
        "setContext",
        "inspect_ai.activeTask",
        taskActive
      );
    }
  }

  async updateActiveTaskWithDocument(
    document?: TextDocument,
    selection?: Selection
  ) {
    if (document && selection) {
      const activeTaskInfo =
        document.languageId === "python"
          ? getTaskInfoFromDocument(document, selection)
          : undefined;
      await this.updateTask(activeTaskInfo);
    }
  }

  async updateActiveTask(documentUri: Uri, task: string) {
    if (isNotebook(documentUri)) {
      // Compute the cell and position of the task
      const notebookDocument = await workspace.openNotebookDocument(
        documentUri
      );
      const cells = cellTasks(notebookDocument);
      const cellTask = cells.find((c) => {
        return c.tasks.find((t) => {
          return t.name === task;
        });
      });
      if (cellTask) {
        const cell = notebookDocument.cellAt(cellTask?.cellIndex);
        const taskInfo = getTaskInfo(cell.document, task);
        await this.updateTask(taskInfo);
      }
    } else {
      const document = await workspace.openTextDocument(documentUri);
      const taskInfo = getTaskInfo(document, task);
      await this.updateTask(taskInfo);
    }
  }

  // Set the task information
  setActiveTaskInfo(task?: DocumentTaskInfo) {
    if (this.activeTaskInfo_ !== task) {
      this.activeTaskInfo_ = task;
      this.onActiveTaskChanged_.fire({ activeTaskInfo: this.activeTaskInfo_ });
    }
  }
}

function getTaskInfoFromDocument(
  document: TextDocument,
  selection?: Selection
): DocumentTaskInfo | undefined {
  // Try to get symbols to read task info for this document
  // Note that the retry is here since the symbol provider
  // has latency in loading and there wasn't a way to wait
  // on it specifically (waiting on the Python extension didn't work)
  const tasks = readTaskData(document);

  // If there are no tasks in this document, return undefined
  if (tasks.length === 0) {
    return undefined;
  }

  const selectionLine = selection?.start.line || 0;

  // Find the first task that appears before the selection
  // or otherwise the first task

  const activeTask = [...tasks].reverse().find((task) => {
    return task.line <= selectionLine;
  });
  return {
    document: document.uri,
    tasks,
    activeTask: activeTask || (tasks.length > 0 ? tasks[0] : undefined),
  };
}

function getTaskInfo(
  document: TextDocument,
  task: string
): DocumentTaskInfo | undefined {
  // Try to get symbols to read task info for this document
  // Note that the retry is here since the symbol provider
  // has latency in loading and there wasn't a way to wait
  // on it specifically (waiting on the Python extension didn't work)
  const tasks = readTaskData(document);

  // Find the first task that appears before the selection
  // or otherwise the first task

  const activeTask = [...tasks].reverse().find((t) => {
    return t.name === task;
  });
  return {
    document: document.uri,
    tasks,
    activeTask: activeTask || (tasks.length > 0 ? tasks[0] : undefined),
  };
}
