import * as vscode from 'vscode';
import { Command } from '../../../core/command';
import { LogTreeDataProvider } from './log-listing-data';

import { WorkspaceEnvManager } from "../../workspace/workspace-env-provider";

export function activateLogs(envManager: WorkspaceEnvManager): [Command[], vscode.Disposable[]] {

  const disposables: vscode.Disposable[] = [];


  // create tree data provider and tree
  const treeDataProvider = new LogTreeDataProvider();
  disposables.push(treeDataProvider);

  const tree = vscode.window.createTreeView(LogTreeDataProvider.viewType, {
    treeDataProvider,
    showCollapseAll: true,
    canSelectMany: false,
  });

  // sync to updates to the .env
  const updateTree = () => {
    tree.description = envManager.getDefaultLogDir().toString(true);
    tree.message = tree.description;
    tree.title = "Logs";
  };
  disposables.push(envManager.onEnvironmentChanged(updateTree));

  updateTree();

  return [[], disposables];
}

