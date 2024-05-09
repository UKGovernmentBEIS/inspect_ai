import path, { join } from "path";
import { AbsolutePath, activeWorkspacePath } from "../../core/path";
import { inspectListTasks } from "../../inspect/list";
import { Event, EventEmitter, ExtensionContext, FileSystemWatcher, workspace } from "vscode";

import { throttle } from "lodash";
import { InspectChangedEvent, InspectManager } from "../inspect/inspect-manager";

// Activates the provider which tracks the currently active task (document and task name)
export function activateWorkspaceTaskProvider(inspectManager: InspectManager, context: ExtensionContext) {

  // The task manager
  const taskManager = new WorkspaceTaskManager();

  // If the interpreter changes, refresh the tasks
  context.subscriptions.push(inspectManager.onInspectChanged((e: InspectChangedEvent) => {
    if (e.available) {
      taskManager.refresh();
    }
  }));

  return taskManager;
}

// Describes the path to a runnable task
export interface TaskPath {
  name: string;
  path: string; // TODO: convert this to properly typed 'AbsolutePath'
  type: "folder" | "file" | "task";
  children?: TaskPath[];
  parent?: TaskPath;
}

// Fired when the active task changes
export interface TasksChangedEvent {
  tasks?: TaskPath[];
}

const kTaskFilePattern = "**/*.{py,ipynb}";

// Tracks what the active task is in the editor
export class WorkspaceTaskManager {
  constructor() {
    this.watcher = workspace.createFileSystemWatcher(
      kTaskFilePattern,
      false,
      false,
      false
    );
    const onChange = throttle(() => {
      this.refresh();
    }, 1000, { leading: true, trailing: true });
    this.watcher.onDidCreate(onChange);
    this.watcher.onDidDelete(onChange);
    this.watcher.onDidChange(onChange);
  }

  private tasks_: TaskPath[] = [];
  private watcher: FileSystemWatcher;

  public refresh() {
    const workspace = activeWorkspacePath();

    try {
      const tasks = inspectTaskData(workspace);
      this.setTasks(tasks);
    } catch (err: unknown) {
      console.log("Unable to read inspect task data.");
      console.error(err);
    }

  }

  public setTasks(tasks?: TaskPath[]) {
    if (tasks) {
      this.tasks_ = tasks;
    } else {
      this.tasks_ = [];
    }
    this.onTasksChanged_.fire({ tasks: this.tasks_ });
  }

  public getTasks() {
    return this.tasks_;
  }

  private readonly onTasksChanged_ =
    new EventEmitter<TasksChangedEvent>();
  public readonly onTasksChanged: Event<TasksChangedEvent> =
    this.onTasksChanged_.event;
}

function inspectTaskData(folder: AbsolutePath) {
  // Read the list of tasks
  const taskDescriptors = inspectListTasks(folder);

  // Keep a map so we can quickly look up parents
  const treeMap: Map<string, TaskPath> = new Map();

  // Got through the task descriptors and
  taskDescriptors.forEach((descriptor) => {
    // track the parent node as we make children
    let parentNode: TaskPath | undefined;

    // Split the file into parts so we can make subfolder
    // items in the tree
    const parts = descriptor.file.split(path.sep);
    let currentPath = folder.path;
    parts.forEach((part, idx) => {
      currentPath = join(currentPath, part);
      const isFolder = idx !== parts.length - 1; // Last part is the file
      // Make sure this path is in the map of nodes (as a folder or file)
      if (!treeMap.has(currentPath)) {
        const node: TaskPath = {
          name: part,
          path: currentPath,
          type: isFolder ? "folder" : "file",
          children: [],
          parent: parentNode,
        };
        treeMap.set(currentPath, node);

        // If we're in a child node, make sure to add the parent
        if (parentNode) {
          parentNode.children!.push(node);
        }
      }
      parentNode = treeMap.get(currentPath)!;
    });

    // Add the task as a child to the file node
    parentNode!.children!.push({
      name: descriptor.name,
      path: currentPath,
      type: "task",
      parent: parentNode,
    });
  });

  // Return the root tree nodes
  const vals = Array.from(treeMap.values()).filter((entry) => {
    return entry.parent === undefined;
  });

  // TODO: Sort Children, etc.
  return vals.sort((a, b) => {
    if (a.path === b.path) {
      return a.name.localeCompare(b.name);
    } else {
      return a.path.localeCompare(b.path);
    }
  });
}

export function deactivate() { }
