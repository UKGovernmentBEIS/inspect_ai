import * as vscode from 'vscode';

import { Command } from '../../../core/command';
import { LogTreeDataProvider } from './log-listing-data';

import { WorkspaceEnvManager } from "../../workspace/workspace-env-provider";
import { LogListing, LogNode } from './log-listing';
import { InspectViewServer } from '../../inspect/inspect-view-server';
import { activeWorkspaceFolder } from '../../../core/workspace';
import { getRelativeUri, prettyUriPath } from '../../../core/uri';
import { InspectLogsWatcher } from '../../inspect/inspect-logs-watcher';
import { selectLogDirectory } from './log-directory-selector';
import { Uri } from 'vscode';
import { hasMinimumInspectVersion } from '../../../inspect/version';
import { kInspectEvalLogFormatVersion } from '../../inspect/inspect-constants';


export async function activateLogListing(
  context: vscode.ExtensionContext,
  envManager: WorkspaceEnvManager,
  viewServer: InspectViewServer,
  logsWatcher: InspectLogsWatcher
): Promise<[Command[], vscode.Disposable[]]> {

  const kLogListingDir = "inspect_ai.logListingDir";
  const disposables: vscode.Disposable[] = [];

  await vscode.commands.executeCommand(
    "setContext",
    "inspect_ai.haveEvalLogFormat",
    hasMinimumInspectVersion(kInspectEvalLogFormatVersion)
  );


  // create tree data provider and tree
  const treeDataProvider = new LogTreeDataProvider(context, viewServer);
  disposables.push(treeDataProvider);
  const tree = vscode.window.createTreeView(LogTreeDataProvider.viewType, {
    treeDataProvider,
    showCollapseAll: false,
    canSelectMany: false,
  });

  // update the tree based on the current preferred log dir
  const updateTree = () => {
    // see what the active log dir is
    const preferredLogDir = context.workspaceState.get<string>(kLogListingDir);
    const logDir = preferredLogDir ? Uri.parse(preferredLogDir) : envManager.getDefaultLogDir();

    // set it
    treeDataProvider.setLogListing(new LogListing(context, logDir, viewServer));

    // show a workspace relative path if this is in the workspace,
    // otherwise show the protocol then the last two bits of the path
    const relativePath = getRelativeUri(activeWorkspaceFolder().uri, logDir);
    if (relativePath) {
      tree.description = `./${relativePath}`;
    } else {
      tree.description = prettyUriPath(logDir);
    }
  };

  // initial tree update
  updateTree();

  // update tree if the environment changes and we are tracking the workspace log dir
  disposables.push(envManager.onEnvironmentChanged(() => {
    if (context.workspaceState.get<string>(kLogListingDir) === undefined) {
      updateTree();
    }
  }));

  // Register select log dir command
  disposables.push(vscode.commands.registerCommand('inspect.logListing', async () => {
    const logLocation = await selectLogDirectory(context, envManager);
    if (logLocation !== undefined) {
      // store state ('null' means use workspace default so pass 'undefined' to clear for that)
      await context.workspaceState.update(
        kLogListingDir,
        logLocation === null
          ? undefined
          : logLocation.toString()
      );

      // trigger update
      updateTree();

      // reveal
      await revealLogListing();
    }
  }));

  // Register reveal command
  disposables.push(vscode.commands.registerCommand('inspect.logListingReveal', async (uri?: Uri) => {
    const treeLogUri = treeDataProvider.getLogListing()?.logDir();
    if (treeLogUri && uri && getRelativeUri(treeLogUri, uri) !== null) {
      const node = treeDataProvider.getLogListing()?.nodeForUri(uri);
      if (node) {
        await tree.reveal(node);
      }
    }
  }));

  // Register refresh command
  disposables.push(vscode.commands.registerCommand('inspect.logListingRefresh', () => {
    treeDataProvider.refresh();
  }));

  // Register Reveal in Explorer command
  disposables.push(vscode.commands.registerCommand('inspect.logListingRevealInExplorer', async (node: LogNode) => {
    const logUri = treeDataProvider.getLogListing()?.uriForNode(node);
    if (logUri) {
      await vscode.commands.executeCommand('revealInExplorer', logUri);
    }
  }));

  // Register Open in JSON Editor... command
  disposables.push(vscode.commands.registerCommand('inspect.logListingOpenInJSONEditor', async (node: LogNode) => {
    const logUri = treeDataProvider.getLogListing()?.uriForNode(node);
    if (logUri) {
      await vscode.commands.executeCommand('vscode.open', logUri, <vscode.TextDocumentShowOptions>{ preview: true });
    }
  }));

  // Register delete log file command
  disposables.push(vscode.commands.registerCommand('inspect.logListingDeleteLogFile', async (node: LogNode) => {
    const logUri = treeDataProvider.getLogListing()?.uriForNode(node);
    if (logUri) {
      const result = await vscode.window.showInformationMessage(
        'Delete Log File',
        {
          modal: true,
          detail: `Are you sure you want to delete the log file at ${prettyUriPath(logUri)}?`
        },
        { title: 'Delete', isCloseAffordance: false },
        { title: 'Cancel', isCloseAffordance: true }
      );

      if (result?.title === 'Delete') {
        await viewServer.evalLogDelete(logUri.toString());
        treeDataProvider.refresh();
      }

    }
  }));

  // refresh when a log in our directory changes
  disposables.push(logsWatcher.onInspectLogCreated((e) => {
    const treeLogDir = treeDataProvider.getLogListing()?.logDir();
    if (treeLogDir && getRelativeUri(treeLogDir, e.log)) {
      treeDataProvider.refresh();
    }
  }));

  // refresh on change visiblity
  disposables.push(tree.onDidChangeVisibility(e => {
    if (e.visible) {
      treeDataProvider.refresh();
    }
  }));

  return [[], disposables];
}

export async function revealLogListing() {
  await vscode.commands.executeCommand('workbench.action.focusSideBar');
  await vscode.commands.executeCommand(`workbench.view.extension.inspect_ai-activity-bar`);
}
