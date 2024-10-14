/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from 'vscode';
import { Uri } from 'vscode';
import { inspectViewPath } from '../../inspect/props';

class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {

  static register(context: vscode.ExtensionContext): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context);
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

  constructor(private readonly _context: vscode.ExtensionContext) { }

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
    Uri.joinPath(this._context.extensionUri, "assets", "www");

    // set webview  options
    webviewPanel.webview.options = {
      enableScripts: true,
      enableForms: true,
      localResourceRoots
    };

    webviewPanel.webview.html = this.getHtmlForWebview(webviewPanel.webview, document.uri);
  }

  private getHtmlForWebview(webview: vscode.Webview, uri: vscode.Uri): string {
    const content = 'File content goes here'; // In a real scenario, you'd read the file content

    return `
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Custom Readonly Editor</title>
            </head>
            <body>
                <h1>Custom Readonly View</h1>
                <pre>${content}</pre>
            </body>
            </html>
        `;
  }
}

export function activateLogviewEditor(context: vscode.ExtensionContext) {
  context.subscriptions.push(InspectLogReadonlyEditor.register(context));
}