import * as vscode from 'vscode';

import { Command } from '../../../core/command';
import { LogTreeDataProvider } from './log-listing-data';

import { WorkspaceEnvManager } from "../../workspace/workspace-env-provider";
import { LogListing } from './log-listing';
import { InspectViewServer } from '../../inspect/inspect-view-server';
import { activeWorkspaceFolder } from '../../../core/workspace';
import { getRelativePath, prettyUriPath } from '../../../core/uri';


export function activateLogListing(context: vscode.ExtensionContext, envManager: WorkspaceEnvManager, viewServer: InspectViewServer): [Command[], vscode.Disposable[]] {


  const disposables: vscode.Disposable[] = [];

  // Register refresh command
  disposables.push(vscode.commands.registerCommand('inspect.logListingRefresh', () => {
    treeDataProvider.refresh();
  }));

  // create tree data provider and tree
  const treeDataProvider = new LogTreeDataProvider(context);
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

    // show a workspace relative path if this is in the workspace,
    // otherwise show the protocol then the last two bits of the path
    const relativePath = getRelativePath(activeWorkspaceFolder().uri, logDir);
    if (relativePath) {
      tree.description = `./${relativePath}`;
    } else {
      tree.description = prettyUriPath(logDir);
    }
  };
  disposables.push(envManager.onEnvironmentChanged(updateTree));

  updateTree();

  return [[], disposables];
}

