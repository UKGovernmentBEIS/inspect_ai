/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from 'vscode';
import { Uri, window } from 'vscode';
import { inspectViewPath } from '../../inspect/props';
import { LogviewPanel } from './logview-panel';
import { InspectViewServer } from '../inspect/inspect-view-server';
import { HostWebviewPanel } from '../../hooks';
import { InspectSettingsManager } from "../settings/inspect-settings";


class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {

  static register(
    context: vscode.ExtensionContext,
    settings: InspectSettingsManager,
    server: InspectViewServer
  ): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context, settings, server);
    const providerRegistration = vscode.window.registerCustomEditorProvider(
      InspectLogReadonlyEditor.viewType,
      provider,
      {
        webviewOptions: {
          retainContextWhenHidden: false
        },
        supportsMultipleEditorsPerDocument: true
      }
    );
    return providerRegistration;
  }

  private static readonly viewType = 'inspect-ai.log-editor';

  constructor(
    private readonly context_: vscode.ExtensionContext,
    private readonly settings_: InspectSettingsManager,
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
    if (this.settings_.getSettings().jsonLogView) {
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
      this.logviewPanel_ = new LogviewPanel(
        webviewPanel as HostWebviewPanel,
        this.context_,
        this.server_,
        "file",
        document.uri
      );

      // set html
      webviewPanel.webview.html = this.logviewPanel_.getHtml(document.uri);
    } else {
      const viewColumn = webviewPanel.viewColumn;
      await vscode.commands.executeCommand('vscode.openWith', document.uri, 'default', viewColumn);
    }
  }

  dispose() {
    this.logviewPanel_?.dispose();
  }

  private logviewPanel_?: LogviewPanel;

}

export function activateLogviewEditor(
  context: vscode.ExtensionContext,
  settings: InspectSettingsManager,
  server: InspectViewServer) {
  context.subscriptions.push(InspectLogReadonlyEditor.register(context, settings, server));
}