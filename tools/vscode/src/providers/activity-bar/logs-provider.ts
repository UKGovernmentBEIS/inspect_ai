

import * as vscode from 'vscode';
import { Command } from '../../core/command';

export function activateLogs(): [Command[], vscode.Disposable] {


  const treeDataProvider = new LogProvider();

  vscode.window.createTreeView(LogProvider.viewType, {
    treeDataProvider,
    showCollapseAll: true,
    canSelectMany: false,
  });


  return [[], treeDataProvider];
}


class Log {
  constructor(public readonly name: string) { }
}

export class LogProvider implements vscode.TreeDataProvider<Log>, vscode.Disposable {

  public static readonly viewType = "inspect_ai.logs-view";

  dispose() {
    throw new Error('Method not implemented.');
  }
  private _onDidChangeTreeData: vscode.EventEmitter<Log | undefined | null | void> = new vscode.EventEmitter<Log | undefined | null | void>();
  readonly onDidChangeTreeData: vscode.Event<Log | undefined | null | void> = this._onDidChangeTreeData.event;

  private logs: Log[] = [
    new Log('log1.json'),
    new Log('log2.json'),
    new Log('log3.json')
  ];

  getTreeItem(element: Log): vscode.TreeItem {
    return {
      label: element.name,
      collapsibleState: vscode.TreeItemCollapsibleState.Collapsed
    };
  }

  getChildren(element?: Log): Thenable<Log[]> {
    if (element) {
      return Promise.resolve([]);
    } else {
      return Promise.resolve(this.logs);
    }
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }
}

