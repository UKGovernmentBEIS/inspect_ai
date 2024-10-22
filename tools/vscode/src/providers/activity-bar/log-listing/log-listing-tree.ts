import * as vscode from 'vscode';
import { Command } from '../../../core/command';
import { LogTreeDataProvider } from './log-listing-data';

import { WorkspaceEnvManager } from "../../workspace/workspace-env-provider";
import { LogListing } from './log-listing';
import { InspectViewServer } from '../../inspect/inspect-view-server';

export function activateLogs(envManager: WorkspaceEnvManager, viewServer: InspectViewServer): [Command[], vscode.Disposable[]] {

  const disposables: vscode.Disposable[] = [];


  // create tree data provider and tree
  const treeDataProvider = new LogTreeDataProvider();
  disposables.push(treeDataProvider);


  const tree = vscode.window.createTreeView(LogTreeDataProvider.viewType, {
    treeDataProvider,
    showCollapseAll: false,
    canSelectMany: false,
  });

  // sync to updates to the .env
  const updateTree = () => {
    const logDir = envManager.getDefaultLogDir();
    treeDataProvider.setLogListing(new LogListing(logDir, viewServer));
    tree.description = envManager.getDefaultLogDir().toString(true);
    tree.message = tree.description;
    tree.title = "Logs";
  };
  disposables.push(envManager.onEnvironmentChanged(updateTree));

  updateTree();

  return [[], disposables];
}

