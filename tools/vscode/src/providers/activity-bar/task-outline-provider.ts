import {
  Event,
  EventEmitter,
  TreeDataProvider,
  TreeItem,
  TreeItemCollapsibleState,
  window,
  Command as VsCodeCommand,
  workspace,
  ThemeIcon,
  commands,
  ExtensionContext,
  Disposable,
  TreeView,
  TreeViewVisibilityChangeEvent,
  Uri,
} from "vscode";
import {
  RunSelectedEvalCommand,
  DebugSelectedEvalCommand,
  EditSelectedTaskCommand,
  ShowTaskList,
  ShowTaskTree,
  CreateTaskCommand,
} from "./task-outline-commands";
import { AbsolutePath, activeWorkspacePath } from "../../core/path";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { Command } from "../../core/command";
import {
  TaskPath,
  TasksChangedEvent,
  WorkspaceTaskManager,
} from "../workspace/workspace-task-provider";
import { basename, relative, sep } from "path";
import {
  ActiveTaskManager,
} from "../active-task/active-task-provider";
import { throttle } from "lodash";
import { inspectVersion } from "../../inspect";
import { InspectManager } from "../inspect/inspect-manager";
import { InspectViewManager } from "../logview/logview-view";
import { DocumentTaskInfo } from "../../components/task";

// Activation function for the task outline
export async function activateTaskOutline(
  context: ExtensionContext,
  inspectEvalMgr: InspectEvalManager,
  workspaceTaskMgr: WorkspaceTaskManager,
  activeTaskManager: ActiveTaskManager,
  inspectManager: InspectManager,
  inspectLogviewManager: InspectViewManager
): Promise<[Command[], Disposable]> {
  // Command when item is clicked
  const treeDataProvider = new TaskOutLineTreeDataProvider(workspaceTaskMgr, {
    title: "Edit Item",
    command: EditSelectedTaskCommand.id,
  });

  const checkInspect = async () => {
    const inspectAvailable = inspectVersion() !== null;
    await commands.executeCommand(
      "setContext",
      "inspect_ai.task-outline-view.noInspect",
      !inspectAvailable
    );
    if (inspectAvailable) {
      treeDataProvider.refresh();
    } else {
      treeDataProvider.clear();
    }
  };

  // If the interpreter changes, refresh the tasks
  context.subscriptions.push(
    inspectManager.onInspectChanged(async () => {
      await checkInspect();
    })
  );
  await checkInspect();

  const tree = window.createTreeView(TaskOutLineTreeDataProvider.viewType, {
    treeDataProvider,
    showCollapseAll: true,
    canSelectMany: false,
  });

  context.subscriptions.push(
    tree.onDidChangeVisibility(async (e: TreeViewVisibilityChangeEvent) => {
      // If the tree becomes visible with nothing selected, try selecting
      if (e.visible && tree.selection.length === 0) {
        const activeTask = activeTaskManager.getActiveTaskInfo();
        if (activeTask) {
          await showTreeItem(treeDataProvider, tree, activeTask);
        } else {
          const first = await findFirstTask(treeDataProvider);
          if (first) {
            await activeTaskManager.updateActiveTask(Uri.file(first.taskPath.path), first.taskPath.name);
          }
        }
      } else if (e.visible) {
        // Tree just became visible, be sure selection matches the active task
        await showTreeItem(
          treeDataProvider,
          tree,
          activeTaskManager.getActiveTaskInfo()
        );
      }
    })
  );

  // Activate task tracking
  context.subscriptions.push(
    ...(await activateTaskTracking(treeDataProvider, tree, activeTaskManager))
  );

  return [
    [
      new ShowTaskList(treeDataProvider),
      new ShowTaskTree(treeDataProvider),
      new RunSelectedEvalCommand(inspectEvalMgr),
      new DebugSelectedEvalCommand(inspectEvalMgr),
      new EditSelectedTaskCommand(tree, inspectLogviewManager, activeTaskManager),
      new CreateTaskCommand(context),
    ],
    treeDataProvider,
  ];
}

const activateTaskTracking = async (
  treeDataProvider: TaskOutLineTreeDataProvider,
  tree: TreeView<TaskTreeItem>,
  activeTaskManager: ActiveTaskManager
) => {
  // Listen for changes to the active task and drive the tree to the item
  const activeTaskChanged = activeTaskManager.onActiveTaskChanged(async (e) => {
    await showTreeItem(treeDataProvider, tree, e.activeTaskInfo);
  });

  const currentlyActive = activeTaskManager.getActiveTaskInfo();
  await showTreeItem(treeDataProvider, tree, currentlyActive);
  return [activeTaskChanged];
};

const showTreeItem = async (
  treeDataProvider: TaskOutLineTreeDataProvider,
  tree: TreeView<TaskTreeItem>,
  activeTask?: DocumentTaskInfo
) => {
  if (!activeTask) {
    return;
  }

  const treeItem = await findTreeItem(activeTask, treeDataProvider);
  if (treeItem && treeItem.taskPath.type === "task") {
    // Don't reveal the item if the tree isn't visible (this will force the
    // activity bar containing the tree to become visible, which is very jarring)
    if (tree.visible) {
      await tree.reveal(treeItem, { select: true, focus: false });
    }
  }
};

const findFirstTask = async (
  treeDataProvider: TaskOutLineTreeDataProvider,
  element?: TaskTreeItem
): Promise<TaskTreeItem | undefined> => {
  const children = await treeDataProvider.getChildren(element);
  for (const child of children) {
    if (child.taskPath.type === "task") {
      return child;
    } else {
      return await findFirstTask(treeDataProvider, child);
    }
  }
};


// A tree item for a task, file, or folder
export class TaskTreeItem extends TreeItem {
  constructor(
    public readonly taskPath: TaskPath,
    command?: VsCodeCommand,
    public readonly parent?: TaskTreeItem
  ) {
    super(
      taskPath.name,
      taskPath.type === "task"
        ? TreeItemCollapsibleState.None
        : taskPath.type === "folder"
          ? TreeItemCollapsibleState.Expanded
          : taskPath.children && taskPath.children.length < 2
            ? TreeItemCollapsibleState.Collapsed
            : TreeItemCollapsibleState.Expanded
    );

    if (taskPath.type === "file") {
      this.iconPath = new ThemeIcon("file-code");
    } else if (taskPath.type === "task") {
      this.iconPath = new ThemeIcon("record-small");
    }

    const label =
      typeof this.label === "string" ? this.label : this.label?.label;
    this.tooltip = `${taskPath.type}: ${label}`;
    this.contextValue =
      taskPath.type !== "folder" ? "runnable" : "not-runnable";
    this.command = command;
  }
}

export class TaskListItem extends TaskTreeItem {
  constructor(
    taskPath: TaskPath,
    description: string,
    command?: VsCodeCommand,
    parent?: TaskTreeItem
  ) {
    super(taskPath, command, parent);
    const label =
      typeof this.label === "string" ? this.label : this.label?.label;
    this.tooltip = `${taskPath.type}: ${label}`;
    this.description = description;
    this.contextValue =
      taskPath.type !== "folder" ? "runnable" : "not-runnable";
    this.command = command;
  }
}

// Data provider for the task outline
export class TaskOutLineTreeDataProvider
  implements TreeDataProvider<TaskTreeItem>, Disposable {
  public static readonly viewType = "inspect_ai.task-outline-view";
  constructor(
    private readonly workspaceMgr: WorkspaceTaskManager,
    private readonly command_?: VsCodeCommand
  ) {
    this.disposables_.push(
      this.workspaceMgr.onTasksChanged(
        throttle(
          async (e: TasksChangedEvent) => {
            this.setTasks(e.tasks || []);
            await commands.executeCommand(
              "setContext",
              "inspect_ai.task-outline-view.tasksLoaded",
              true
            );
            await commands.executeCommand(
              "setContext",
              "inspect_ai.task-outline-view.noTasks",
              e.tasks?.length === 0
            );
          },
          500,
          { leading: true, trailing: true }
        )
      )
    );
    this.workspaceMgr.refresh();
  }
  private disposables_: Disposable[] = [];
  dispose() {
    this.disposables_.forEach((disposable) => {
      disposable.dispose();
    });
  }

  private taskNodes: TaskPath[] = [];

  private onDidChangeTreeData_: EventEmitter<
    TaskTreeItem | undefined | null | void
  > = new EventEmitter<TaskTreeItem | undefined | null | void>();
  readonly onDidChangeTreeData: Event<TaskTreeItem | undefined | null | void> =
    this.onDidChangeTreeData_.event;

  refresh() {
    this.workspaceMgr.refresh();
  }

  clear() {
    this.setTasks([]);
  }

  private setTasks(taskNodes: TaskPath[]) {
    this.taskNodes = taskNodes;
    this.onDidChangeTreeData_.fire();
  }

  getTreeItem(element: TaskTreeItem): TreeItem {
    return element;
  }

  getChildren(element?: TaskTreeItem): Thenable<TaskTreeItem[]> {
    if (element) {
      const nodes = element.taskPath.children
        ? this.getNodes(element.taskPath.children, element)
        : [];
      return Promise.resolve(nodes);
    } else {
      return Promise.resolve(this.getNodes(this.taskNodes));
    }
  }

  getParent(element: TaskTreeItem): TaskTreeItem | null {
    return element.parent || null;
  }

  private getNodes(tree: TaskPath[], parent?: TaskTreeItem): TaskTreeItem[] {
    const mode =
      workspace.getConfiguration("inspect_ai").get("taskListView") || "tree";

    if (mode === "tree") {
      return tree.map((node) => new TaskTreeItem(node, this.command_, parent));
    } else {
      const getTasks = (node: TaskPath): TaskPath[] => {
        if (node.type === "task") {
          return [node];
        } else {
          return (
            node.children?.flatMap((node) => {
              return getTasks(node);
            }) || []
          );
        }
      };

      const workspacePath = activeWorkspacePath();

      return tree
        .flatMap((node) => getTasks(node))
        .sort((a, b) => {
          return a.name.localeCompare(b.name);
        })
        .map((taskPath) => {
          return new TaskListItem(
            taskPath,
            describeRelativePath(taskPath.path, workspacePath),
            this.command_,
            parent
          );
        });
    }
  }
}

function describeRelativePath(path: string, workspacePath?: AbsolutePath) {
  if (!workspacePath) {
    return basename(path);
  } else {
    const relPath = relative(workspacePath.path, path);
    const parts = relPath.split(sep);
    return parts.join(" > ");
  }
}

// Find a task in the tree based upon its
// path (e.g. document path and task name)
async function findTreeItem(
  activeTask: DocumentTaskInfo,
  treeDataProvider: TaskOutLineTreeDataProvider
) {
  const filePath = activeTask.document.fsPath;
  const taskName = activeTask.activeTask?.name;
  const taskTreeItem = await findTask(filePath, treeDataProvider, taskName);
  if (taskTreeItem) {
    return taskTreeItem;
  } else {
    return undefined;
  }
}

async function findTask(
  filePath: string,
  treeDataProvider: TaskOutLineTreeDataProvider,
  taskName?: string,
  parentEl?: TaskTreeItem
): Promise<TaskTreeItem | undefined> {
  const els = await treeDataProvider.getChildren(parentEl);
  let taskEl: TaskTreeItem | undefined = undefined;
  for (const el of els) {
    if (el.taskPath.type === "task" && el.taskPath.name === taskName) {
      taskEl = el;
    } else if (el.taskPath.type === "file" && filePath === el.taskPath.path) {
      if (taskName) {
        taskEl = await findTask(filePath, treeDataProvider, taskName, el);
      } else {
        taskEl = el;
      }
    } else if (el.taskPath.type === "folder") {
      taskEl = await findTask(filePath, treeDataProvider, taskName, el);
    }
    if (taskEl) {
      return taskEl;
    }
  }
  return taskEl;
}
