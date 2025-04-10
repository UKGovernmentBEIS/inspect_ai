import path, { join, relative } from "path";
import { AbsolutePath, activeWorkspacePath } from "../../core/path";
import {
  Event,
  EventEmitter,
  ExtensionContext,
  FileStat,
  FileSystemWatcher,
  Uri,
  workspace,
} from "vscode";

import { throttle } from "lodash";
import {
  InspectChangedEvent,
  InspectManager,
} from "../inspect/inspect-manager";
import { startup } from "../../core/log";

// Activates the provider which tracks the currently active task (document and task name)
export function activateWorkspaceTaskProvider(
  inspectManager: InspectManager,
  context: ExtensionContext,
) {
  // The task manager
  const taskManager = new WorkspaceTaskManager(context);

  // If the interpreter changes, refresh the tasks
  context.subscriptions.push(
    inspectManager.onInspectChanged(async (e: InspectChangedEvent) => {
      if (e.available) {
        await taskManager.refresh();
      }
    }),
  );

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
  constructor(context: ExtensionContext) {
    this.watcher = workspace.createFileSystemWatcher(
      kTaskFilePattern,
      false,
      false,
      false,
    );
    this.context = context;
    const onChange = throttle(
      async () => {
        await this.refresh();
      },
      5000,
      { leading: true, trailing: true },
    );
    this.watcher.onDidCreate(onChange);
    this.watcher.onDidDelete(onChange);
    this.watcher.onDidChange(onChange);
  }

  private tasks_: TaskPath[] = [];
  private watcher: FileSystemWatcher;
  private context: ExtensionContext;

  public async refresh() {
    const workspace = activeWorkspacePath();

    try {
      const tasks = await inspectTaskData(this.context, workspace);
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

  private readonly onTasksChanged_ = new EventEmitter<TasksChangedEvent>();
  public readonly onTasksChanged: Event<TasksChangedEvent> =
    this.onTasksChanged_.event;
}

interface TaskDescriptor {
  file: string;
  name: string;
}

// Regexes to identify tasks
const kTaskRegex = /@task/;
const kTaskNameRegex =
  /^[ \t]*@task(?:\([^)]*\))?[ \t]*\r?\n[ \t]*def\s+([A-Za-z_]\w*)\s*\(/gm;
const kExcludeGlob =
  "**/{.venv,venv,__pycache__,.git,node_modules,env,envs,conda-env,.tox,.pytest_cache,.mypy_cache,.idea,.vscode,build,dist,.eggs,*.egg-info,.ipynb_checkpoints}/**";

interface TaskCache {
  [filePath: string]: { updated: number; descriptors: TaskDescriptor[] };
}

async function workspaceTasks(
  context: ExtensionContext,
  workspacePath: AbsolutePath,
): Promise<TaskDescriptor[]> {
  const start = Date.now();
  const files = await workspace.findFiles("**/*.py", kExcludeGlob);

  // Filter files with skip prefixed
  const validFiles = files.filter((file) => {
    const relativePath = relative(workspacePath.path, file.fsPath);
    return !relativePath.startsWith("_") && !relativePath.startsWith(".");
  });

  // Load the cache
  const taskFileCache = context.workspaceState.get<TaskCache>(
    "taskFileCache2",
    {},
  );

  const tasks: TaskDescriptor[] = [];

  // Try to cached file data, if possible
  const fileStatPromises = validFiles.map(async (file) => {
    const filePath = file.toString();
    const stat = await workspace.fs.stat(file);
    const cached = taskFileCache[filePath];

    if (cached && cached.updated === stat.mtime) {
      tasks.push(...cached.descriptors);
      return null;
    } else {
      return { file, filePath, stat };
    }
  });

  startup.info(`Filtering ${validFiles.length} files (using cache)`);

  // Resolve file stats and filter out cached results
  const filesToProcess = (await Promise.all(fileStatPromises)).filter(
    (file) => file !== null,
  ) as { file: Uri; filePath: string; stat: FileStat }[];

  startup.info(`Inspecting ${filesToProcess.length} files for tasks`);

  // Read files and process tasks concurrently
  const fileTasksPromises = filesToProcess.map(
    async ({ file, filePath, stat }) => {
      const fileData = await workspace.fs.readFile(file);
      const fileContent = new TextDecoder().decode(fileData);

      const fileTasks: TaskDescriptor[] = [];
      const taskFile = relative(workspacePath.path, file.fsPath);
      if (kTaskRegex.test(fileContent)) {
        for (const match of fileContent.matchAll(kTaskNameRegex)) {
          if (match[1]) {
            fileTasks.push({ file: taskFile, name: match[1] });
          }
        }
      }

      // Update cache in memory
      taskFileCache[filePath] = { updated: stat.mtime, descriptors: fileTasks };
      return fileTasks;
    },
  );

  // Await all task collection and add to the tasks array
  const newTasks = (await Promise.all(fileTasksPromises)).flat();
  tasks.push(...newTasks);

  startup.info(`Found ${tasks.length} tasks in ${Date.now() - start}ms`);

  // Batch update the cache once at the end
  await context.workspaceState.update("taskFileCache2", taskFileCache);

  return tasks;
}

async function inspectTaskData(
  context: ExtensionContext,
  folder: AbsolutePath,
) {
  // Read the list of tasks
  const taskDescriptors = await workspaceTasks(context, folder);

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

export function deactivate() {}
