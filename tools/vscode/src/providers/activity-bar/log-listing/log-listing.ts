import { Uri } from "vscode";
import { InspectViewServer } from "../../inspect/inspect-view-server";
import { log } from "../../../core/log";

export type LogNode =
  | { type: "dir" } & LogDirectory
  | { type: "file" } & LogFile;

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
        return this.buildLogNodes(logs.files);
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

  private buildLogNodes(logs: LogFile[]): LogNode[] {
    const root: LogDirectory = { name: "root", children: [] };

    logs.forEach((log) => {
      const parts = log.name.split("/");
      let currentDir = root;

      parts.forEach((part, index) => {
        if (index === parts.length - 1) {
          // It's a file
          currentDir.children.push({ type: "file", ...log, name: part });
        } else {
          // It's a directory
          const dir = currentDir.children.find(
            (child) => child.type === "dir" && child.name === part
          ) as LogDirectory;

          if (!dir) {
            const dir_node: LogNode = { type: "dir", name: part, children: [] };
            currentDir.children.push(dir_node);
          }

          currentDir = dir;
        }
      });
    });

    return root.children;
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