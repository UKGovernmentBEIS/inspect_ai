import * as path from 'path';

import { Event, EventEmitter, TreeDataProvider, TreeItem, TreeItemCollapsibleState } from 'vscode';

import * as vscode from 'vscode';
import { LogNode, LogListing } from './log-listing';




export class LogTreeDataProvider implements TreeDataProvider<LogNode>, vscode.Disposable {

  public static readonly viewType = "inspect_ai.logs-view";

  constructor(private context_: vscode.ExtensionContext) {

  }

  dispose() {

  }

  public setLogListing(logListing: LogListing) {
    this.logListing_ = logListing;
    this._onDidChangeTreeData.fire();
  }


  async getTreeItem(element: LogNode): Promise<TreeItem> {
    return Promise.resolve({
      id: element.name,
      iconPath: element.type === "file"
        ? element.name.endsWith(".eval")
          ? this.context_.asAbsolutePath(path.join("assets", "icon", "eval.svg"))
          : new vscode.ThemeIcon("bracket", new vscode.ThemeColor("symbolIcon.classForeground"))
        : undefined,
      label: element.name.split("/").pop(),
      collapsibleState: element.type === "dir"
        ? TreeItemCollapsibleState.Collapsed
        : TreeItemCollapsibleState.None
    });
  }

  async getChildren(element?: LogNode): Promise<LogNode[]> {
    if (!element || element.type === "dir") {
      return await this.logListing_?.ls(element) || [];
    } else {
      return [];
    }
  }

  refresh(): void {
    this.logListing_?.invalidate();
    this._onDidChangeTreeData.fire();
  }

  private _onDidChangeTreeData: EventEmitter<LogNode | undefined | null | void> = new vscode.EventEmitter<LogNode | undefined | null | void>();
  readonly onDidChangeTreeData: Event<LogNode | undefined | null | void> = this._onDidChangeTreeData.event;


  private logListing_?: LogListing;
}

