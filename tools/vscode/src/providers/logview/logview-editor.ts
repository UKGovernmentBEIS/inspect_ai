/* eslint-disable @typescript-eslint/no-unused-vars */
import * as vscode from 'vscode';

class InspectLogReadonlyEditor implements vscode.CustomReadonlyEditorProvider {

  static register(context: vscode.ExtensionContext): vscode.Disposable {
    const provider = new InspectLogReadonlyEditor(context);
    const providerRegistration = vscode.window.registerCustomEditorProvider(
      InspectLogReadonlyEditor.viewType,
      provider,
      {
        webviewOptions: { retainContextWhenHidden: false },
        supportsMultipleEditorsPerDocument: false
      }
    );
    return providerRegistration;
  }

  private static readonly viewType = 'inspect-ai.log-editor';

  constructor(private readonly context: vscode.ExtensionContext) { }

  // eslint-disable-next-line @typescript-eslint/require-await
  async openCustomDocument(
    uri: vscode.Uri,
    openContext: vscode.CustomDocumentOpenContext,
    token: vscode.CancellationToken
  ): Promise<vscode.CustomDocument> {
    return { uri, dispose: () => { } };
  }

  // eslint-disable-next-line @typescript-eslint/require-await
  async resolveCustomEditor(
    document: vscode.CustomDocument,
    webviewPanel: vscode.WebviewPanel,
    token: vscode.CancellationToken
  ): Promise<void> {
    webviewPanel.webview.options = {
      enableScripts: true,
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