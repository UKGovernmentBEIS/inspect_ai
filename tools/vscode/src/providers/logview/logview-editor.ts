/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from "vscode";
import { Uri } from "vscode";
import { inspectViewPath } from "../../inspect/props";
import { LogviewPanel } from "./logview-panel";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { HostWebviewPanel } from "../../hooks";
import { log } from "../../core/log";
import { LogviewState } from "./logview-state";
import { dirname } from "../../core/uri";

import { hasMinimumInspectVersion } from "../../inspect/version";
import { kInspectEvalLogFormatVersion } from "../inspect/inspect-constants";

export const kInspectLogViewType = "inspect-ai.log-editor";

class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {
  static register(
    context: vscode.ExtensionContext,
    server: InspectViewServer,
  ): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context, server);
    const providerRegistration = vscode.window.registerCustomEditorProvider(
      kInspectLogViewType,
      provider,
      {
        webviewOptions: {
          retainContextWhenHidden: false,
        },
        supportsMultipleEditorsPerDocument: false,
      },
    );
    return providerRegistration;
  }

  constructor(
    private readonly context_: vscode.ExtensionContext,
    private readonly server_: InspectViewServer,
  ) {}

  // eslint-disable-next-line @typescript-eslint/require-await
  async openCustomDocument(
    uri: vscode.Uri,
    _openContext: vscode.CustomDocumentOpenContext,
    _token: vscode.CancellationToken,
  ): Promise<vscode.CustomDocument> {

    // Parse any params from the Uri
    const queryParams = new URLSearchParams(uri.query);
    const sample_id = queryParams.get("sample_id");
    const epoch = queryParams.get("epoch");
  
    // Return the document with additional info attached to payload
    return {
      uri: uri,
      dispose: () => {},
      sample_id,
      epoch,
    } as vscode.CustomDocument & { sample_id?: string; epoch?: string };
  }

  async resolveCustomEditor(
    document: vscode.CustomDocument,
    webviewPanel: vscode.WebviewPanel,
    _token: vscode.CancellationToken,
  ): Promise<void> {

    const doc = document as vscode.CustomDocument & { sample_id?: string; epoch?: string };
    const sample_id = doc.sample_id;
    const epoch = doc.epoch;

    const docUriNoParams = document.uri.with({ query: "", fragment: "" });
    const docUriStr = docUriNoParams.toString();

    // check if we should use the log viewer (version check + size threshold)
    let useLogViewer = hasMinimumInspectVersion(kInspectEvalLogFormatVersion);
    if (useLogViewer) {
      if (docUriStr.endsWith(".json")) {
        const fileSize = await this.server_.evalLogSize(docUriStr);
        if (fileSize > 1024 * 1000 * 100) {
          log.info(
            `JSON log file ${document.uri.path} is to large for Inspect View, opening in text editor.`,
          );
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
        localResourceRoots,
      };

      // editor panel implementation
      this.logviewPanel_ = new LogviewPanel(
        webviewPanel as HostWebviewPanel,
        this.context_,
        this.server_,
        "file",
        docUriNoParams,
      );

    // set html
      const logViewState: LogviewState = {
        log_file: docUriNoParams,
        log_dir: dirname(docUriNoParams),
        sample: (sample_id && epoch) ? {
          id: sample_id,
          epoch: epoch,
        } : undefined,
      };
      webviewPanel.webview.html = this.logviewPanel_.getHtml(logViewState);
    } else {
      const viewColumn = webviewPanel.viewColumn;
      await vscode.commands.executeCommand(
        "vscode.openWith",
        document.uri,
        "default",
        viewColumn,
      );
    }
  }

  dispose() {
    this.logviewPanel_?.dispose();
  }

  private logviewPanel_?: LogviewPanel;
}

export function activateLogviewEditor(
  context: vscode.ExtensionContext,
  server: InspectViewServer,
) {
  context.subscriptions.push(
    InspectLogReadonlyEditor.register(context, server),
  );
}
