/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from 'vscode';
import { Uri, commands } from 'vscode';
import { inspectViewPath } from '../../inspect/props';
import { LogviewPanel } from './logview-panel';
import { InspectViewServer } from '../inspect/inspect-view-server';
import { HostWebviewPanel } from '../../hooks';
import { InspectSettingsManager } from "../settings/inspect-settings";
import { log } from '../../core/log';
import { LogviewState } from './logview-state';
import { dirname } from '../../core/uri';


import { hasMinimumInspectVersion } from '../../inspect/version';
import { kInspectEvalLogFormatVersion } from '../inspect/inspect-constants';

export const kInspectLogViewType = 'inspect-ai.log-editor';


class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {

  static register(
    context: vscode.ExtensionContext,
    server: InspectViewServer
  ): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context, server);
    const providerRegistration = vscode.window.registerCustomEditorProvider(
      kInspectLogViewType,
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


  constructor(
    private readonly context_: vscode.ExtensionContext,
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

    // check if we should use the log viewer (version check + size threshold)
    let useLogViewer = hasMinimumInspectVersion(kInspectEvalLogFormatVersion);
    if (useLogViewer) {
      const docUri = document.uri.toString();
      if (docUri.endsWith(".json")) {
        const fileSize = await this.server_.evalLogSize(docUri);
        if (fileSize > (1024 * 1000 * 100)) {
          log.info(`JSON log file ${document.uri.path} is to large for Inspect View, opening in text editor.`);
          useLogViewer = false;
        }
      }
    }

    if (useLogViewer) {
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
      const logViewState: LogviewState = {
        log_file: document.uri,
        log_dir: dirname(document.uri)
      };
      webviewPanel.webview.html = this.logviewPanel_.getHtml(logViewState);
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
  server: InspectViewServer) {
  context.subscriptions.push(InspectLogReadonlyEditor.register(context, server));
}