/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from 'vscode';
import { Uri } from 'vscode';
import { inspectViewPath } from '../../inspect/props';
import { LogviewPanel } from './logview-panel';
import { InspectViewServer } from '../inspect/inspect-view-server';
import { LogviewState } from './logview-state';
import { HostWebviewPanel } from '../../hooks';
import { WorkspaceEnvManager } from '../workspace/workspace-env-provider';

class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {

  static register(
    context: vscode.ExtensionContext,
    envMgr: WorkspaceEnvManager,
    server: InspectViewServer
  ): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context, envMgr, server);
    const providerRegistration = vscode.window.registerCustomEditorProvider(
      InspectLogReadonlyEditor.viewType,
      provider,
      {
        webviewOptions: {
          retainContextWhenHidden: false
        },
        supportsMultipleEditorsPerDocument: false
      }
    );
    return providerRegistration;
  }

  private static readonly viewType = 'inspect-ai.log-editor';

  constructor(
    private readonly context_: vscode.ExtensionContext,
    private readonly envMgr_: WorkspaceEnvManager,
    private readonly server_: InspectViewServer
  ) { }

  // eslint-disable-next-line @typescript-eslint/require-await
  async openCustomDocument(
    uri: vscode.Uri,
    _openContext: vscode.CustomDocumentOpenContext,
    _token: vscode.CancellationToken
  ): Promise<vscode.CustomDocument> {
    return { uri, dispose: () => { } };
  }

  // eslint-disable-next-line @typescript-eslint/require-await
  async resolveCustomEditor(
    document: vscode.CustomDocument,
    webviewPanel: vscode.WebviewPanel,
    _token: vscode.CancellationToken
  ): Promise<void> {

    // local resource roots
    const localResourceRoots: Uri[] = [];
    const viewDir = inspectViewPath();
    if (viewDir) {
      localResourceRoots.push(Uri.file(viewDir.path));
    }
    Uri.joinPath(this.context_.extensionUri, "assets", "www");

    // set webview options
    webviewPanel.webview.options = {
      enableScripts: true,
      enableForms: true,
      localResourceRoots
    };

    // editor panel implementation
    const log_dir = this.envMgr_.getDefaultLogDir();
    const state: LogviewState = {
      log_file: document.uri,
      log_dir: log_dir
    };
    this.logviewPanel_ = new LogviewPanel(
      webviewPanel as HostWebviewPanel,
      this.server_,
      this.context_,
      state.log_dir
    );

    // set html
    webviewPanel.webview.html = this.logviewPanel_.getHtml(state);
  }

  dispose() {
    this.logviewPanel_?.dispose();
  }

  private logviewPanel_?: LogviewPanel;

}

export function activateLogviewEditor(
  context: vscode.ExtensionContext,
  envMgr: WorkspaceEnvManager,
  server: InspectViewServer) {
  context.subscriptions.push(InspectLogReadonlyEditor.register(context, envMgr, server));
}