import { Uri } from "vscode";
import { InspectViewServer } from "../../inspect/inspect-view-server";
import { log } from "../../../core/log";

export type LogNode =
  | { type: "dir", parent?: LogDirectory } & LogDirectory
  | { type: "file", parent?: LogDirectory } & LogFile;

export interface LogDirectory {
  name: string
  children: LogNode[]
}

export interface LogFile {
  name: string
  size: number
  mtime: number
  task: string
  task_id: string
  suffix: string | null
}


export class LogListing {
  constructor(
    private readonly logDir_: Uri,
    private readonly viewServer_: InspectViewServer) {

  }

  public async ls(parent?: LogDirectory): Promise<LogNode[]> {

    // fetch the nodes if we don't have them yet
    if (this.nodes_ === undefined) {
      this.nodes_ = await this.listLogs();
    }

    // if there is no parent, return the root nodes
    if (parent === undefined) {
      return this.nodes_;
    } else {
      // look for the parent and return its children
      const parentNode = this.findParentNode(this.nodes_, parent.name);
      if (parentNode) {
        return parentNode.children;
      }
    }


    return [];
  }

  public invalidate() {
    this.nodes_ = undefined;
  }

  private async listLogs(): Promise<LogNode[]> {
    try {
      const logsJSON = await this.viewServer_.evalLogs(this.logDir_);
      if (logsJSON) {
        const logs = JSON.parse(logsJSON) as { log_dir: string; files: LogFile[] };
        const log_dir = logs.log_dir.endsWith("/") ? logs.log_dir : `${logs.log_dir}/`;
        for (const file of logs.files) {
          file.name = file.name.replace(`${log_dir}`, "");
        }
        const tree = buildLogTree(logs.files);
        return tree;
      } else {
        log.error(`No response retreiving logs from ${this.logDir_.toString(false)}`);
        return [];
      }
    } catch (error) {
      log.error(`Unexpected error retreiving logs from ${this.logDir_.toString(false)}`);
      log.error(error instanceof Error ? error : String(error));
      return [];
    }
  }

  private findParentNode(nodes: LogNode[], parentName: string): LogDirectory | undefined {
    for (const node of nodes) {
      if (node.type === "dir") {
        if (node.name === parentName) {
          return node;
        } else {
          const found = this.findParentNode(node.children, parentName);
          if (found) {
            return found;
          }
        }
      }
    }
    return undefined;
  }

  private nodes_: LogNode[] | undefined;

}



function buildLogTree(logs: LogFile[]): LogNode[] {

  // Keep a map so we can quickly look up parents
  const treeMap: Map<string, LogNode> = new Map();

  logs.forEach(log => {
    // track the parent node as we make children
    let parentNode: LogDirectory | undefined;

    // Split the file into parts so we can make subfolder items in the tree
    const parts = log.name.split("/");
    let currentPath = "";
    parts.forEach((part, idx) => {
      currentPath = currentPath ? `${currentPath}${part}` : part;
      const isFolder = idx !== parts.length - 1; // Last part is the file
      if (isFolder && !treeMap.has(currentPath)) {
        const node: LogNode = {
          type: "dir",
          name: part,
          children: [],
          parent: parentNode,
        };
        treeMap.set(currentPath, node);

        // If we're in a child node, make sure to add the parent
        if (parentNode) {
          parentNode.children.push(node);
        }

        parentNode = treeMap.get(currentPath) as LogDirectory;
      }
    });

    // Add the file as a child to the parent node
    const file: LogNode = { type: "file", parent: parentNode, ...log };
    if (parentNode) {
      parentNode.children.push(file);
    } else {
      treeMap.set(currentPath, file);
    }

  });

  // Return the root tree nodes
  const vals = Array.from(treeMap.values()).filter((entry) => {
    return entry.parent === undefined;
  });

  return vals.sort((a, b) => {
    if (a.name === b.name) {
      return a.name.localeCompare(b.name);
    } else {
      return a.name.localeCompare(b.name);
    }
  });
}