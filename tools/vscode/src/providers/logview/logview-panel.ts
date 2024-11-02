import vscode from "vscode";
import { env, ExtensionContext, MessageItem, Uri, window } from "vscode";
import { getNonce } from "../../core/nonce";
import { HostWebviewPanel } from "../../hooks";
import { inspectViewPath } from "../../inspect/props";
import { readFileSync } from "fs";
import { Disposable } from "../../core/dispose";
import { jsonRpcPostMessageServer, JsonRpcPostMessageTarget, JsonRpcServerMethod, kMethodEvalLog, kMethodEvalLogBytes, kMethodEvalLogHeaders, kMethodEvalLogs, kMethodEvalLogSize } from "../../core/jsonrpc";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { workspacePath } from "../../core/path";
import { LogviewState } from "./logview-state";



export class LogviewPanel extends Disposable {
  constructor(
    private panel_: HostWebviewPanel,
    private context_: ExtensionContext,
    server: InspectViewServer,
    type: "file" | "dir",
    uri: Uri,
  ) {
    super();

    // serve eval log api to webview
    this._rpcDisconnect = webviewPanelJsonRpcServer(panel_, {
      [kMethodEvalLogs]: async () => type === "dir"
        ? server.evalLogs(uri)
        : server.evalLogsSolo(uri),
      [kMethodEvalLog]: (params: unknown[]) => server.evalLog(params[0] as string, params[1] as number | boolean),
      [kMethodEvalLogSize]: (params: unknown[]) => server.evalLogSize(params[0] as string),
      [kMethodEvalLogBytes]: (params: unknown[]) => server.evalLogBytes(params[0] as string, params[1] as number, params[2] as number),
      [kMethodEvalLogHeaders]: (params: unknown[]) => server.evalLogHeaders(params[0] as string[])
    });

    // serve post message api to webview
    this._pmUnsubcribe = panel_.webview.onDidReceiveMessage(
      async (e: { type: string; url: string;[key: string]: unknown }) => {
        switch (e.type) {
          case "openExternal":
            try {
              const url = Uri.parse(e.url);
              await env.openExternal(url);
            } catch {
              // Noop
            }
            break;
          case "openWorkspaceFile":
            {
              if (e.url) {
                const file = workspacePath(e.url);
                try {
                  await window.showTextDocument(Uri.file(file.path));
                } catch (err) {
                  if (
                    err instanceof Error &&
                    err.name === "CodeExpectedError"
                  ) {
                    const close: MessageItem = { title: "Close" };
                    await window.showInformationMessage<MessageItem>(
                      "This file is too large to be opened by the viewer.",
                      close
                    );
                  } else {
                    throw err;
                  }
                }
              }
            }
            break;
        }
      }
    );
  }

  public dispose() {
    this._rpcDisconnect();
    this._pmUnsubcribe.dispose();
  }

  public getHtml(state: LogviewState): string {
    // read the index.html from the log view directory
    const viewDir = inspectViewPath();
    if (viewDir) {
      // get nonce
      const nonce = getNonce();

      // file uri for view dir
      const viewDirUri = Uri.file(viewDir.path);

      // get base html
      let indexHtml = readFileSync(viewDir.child("index.html").path, "utf-8");

      // Determine whether this is the old unbundled version of the html or the new
      // bundled version
      const isUnbundled = indexHtml.match(/"\.(\/App\.mjs)"/g);

      // Add a stylesheet to further customize the view appearance
      const overrideCssPath = this.extensionResourceUrl([
        "assets",
        "www",
        "view",
        "view-overrides.css",
      ]);
      const overrideCssHtml = isUnbundled
        ? `<link rel="stylesheet" type ="text/css" href="${overrideCssPath.toString()}" >`
        : "";

      // If there is a log file selected in state, embed the startup message
      // within the view itself. This will allow the log to be set immediately
      // which avoids timing issues when first opening the view (e.g. the updateState
      // message being sent before the view itself is configured to receive messages)
      const stateMsg = {
        type: "updateState",
        url: state.log_file?.toString(),
      };
      const stateScript =
        state.log_file
          ? `<script id="logview-state" type="application/json">${JSON.stringify(
            stateMsg
          )}</script>`
          : "";

      // decorate the html tag
      indexHtml = indexHtml.replace("<html ", '<html class="vscode" ');

      // add content security policy
      indexHtml = indexHtml.replace(
        "<head>\n",
        `<head>
          <meta name="inspect-extension:version" content="${this.getExtensionVersion()}">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this.panel_.webview.cspSource
        } data:; font-src ${this.panel_.webview.cspSource
        } data:; style-src ${this.panel_.webview.cspSource
        } 'unsafe-inline'; worker-src 'self' ${this.panel_.webview.cspSource
        } blob:; script-src 'nonce-${nonce}' 'unsafe-eval'; connect-src ${this.panel_.webview.cspSource
        };">
    ${stateScript}
    ${overrideCssHtml}

    `
      );

      // function to resolve resource uri
      const resourceUri = (path: string) =>
        this.panel_.webview
          .asWebviewUri(Uri.joinPath(viewDirUri, path))
          .toString();

      // nonces for scripts
      indexHtml = indexHtml.replace(
        /<script([ >])/g,
        `<script nonce="${nonce}"$1`
      );

      // Determine whether this is the old index.html format (before bundling),
      // or the newer one. Fix up the html properly in each case

      if (isUnbundled) {
        // Old unbundle html
        // fixup css references
        indexHtml = indexHtml.replace(/href="\.([^"]+)"/g, (_, p1: string) => {
          return `href="${resourceUri(p1)}"`;
        });

        // fixup js references
        indexHtml = indexHtml.replace(/src="\.([^"]+)"/g, (_, p1: string) => {
          return `src="${resourceUri(p1)}"`;
        });

        // fixup import maps
        indexHtml = indexHtml.replace(
          /": "\.([^?"]+)(["?])/g,
          (_, p1: string, p2: string) => {
            return `": "${resourceUri(p1)}${p2}`;
          }
        );

        // fixup App.mjs
        indexHtml = indexHtml.replace(/"\.(\/App\.mjs)"/g, (_, p1: string) => {
          return `"${resourceUri(p1)}"`;
        });
      } else {
        // New bundled html
        // fixup css references
        indexHtml = indexHtml.replace(/href="([^"]+)"/g, (_, p1: string) => {
          return `href="${resourceUri(p1)}"`;
        });

        // fixup js references
        indexHtml = indexHtml.replace(/src="([^"]+)"/g, (_, p1: string) => {
          return `src="${resourceUri(p1)}"`;
        });
      }

      return indexHtml;
    } else {
      return `
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-type" content="text/html;charset=UTF-8">
</head>
<body>
Inspect not available.
</body>
</html>
`;
    }
  }

  protected getExtensionVersion(): string {
    return (this.context_.extension.packageJSON as Record<string, unknown>)
      .version as string;
  }


  private extensionResourceUrl(parts: string[]): Uri {
    return this.panel_.webview.asWebviewUri(
      Uri.joinPath(this.context_.extensionUri, ...parts)
    );
  }

  private _rpcDisconnect: VoidFunction;
  private _pmUnsubcribe: vscode.Disposable;
}



function webviewPanelJsonRpcServer(
  webviewPanel: HostWebviewPanel,
  methods:
    | Record<string, JsonRpcServerMethod>
    | ((name: string) => JsonRpcServerMethod | undefined)
): () => void {
  const target: JsonRpcPostMessageTarget = {
    postMessage: (data: unknown) => {
      void webviewPanel.webview.postMessage(data);
    },
    onMessage: (handler: (data: unknown) => void) => {
      const disposable = webviewPanel.webview.onDidReceiveMessage((ev) => {
        handler(ev);
      });
      return () => {
        disposable.dispose();
      };
    },
  };
  return jsonRpcPostMessageServer(target, methods);
}

