import { readFileSync } from "fs";

import {
  ExtensionContext,
  WebviewPanel,
  ViewColumn,
  Uri,
  env,
  Disposable
} from "vscode";

import {
  InspectWebview,
  InspectWebviewManager,
} from "../../components/webview";
import { LogviewState } from "./commands";
import { inspectViewPath } from "../../inspect/props";
import { InspectChangedEvent, InspectManager } from "../inspect/inspect-manager";
import { getNonce } from "../../core/nonce";
import { JsonRpcPostMessageTarget, JsonRpcServerMethod, jsonRpcPostMessageServer, kMethodEvalLog, kMethodEvalLogHeaders, kMethodEvalLogs } from "../../core/jsonrpc";
import { inspectEvalLog, inspectEvalLogHeaders, inspectEvalLogs } from "../../inspect/logs";
import { activeWorkspacePath } from "../../core/path";

const kLogViewId = "inspect.logview";

export class InspectLogviewWebviewManager extends InspectWebviewManager<
  InspectLogviewWebview,
  LogviewState
> {
  constructor(inspectManager: InspectManager, context: ExtensionContext) {

    // If the interpreter changes, refresh the tasks
    context.subscriptions.push(inspectManager.onInspectChanged((e: InspectChangedEvent) => {
      if (!e.available && this.activeView_) {
        this.activeView_?.dispose();
      }
    }));

    // register view dir as local resource root
    const localResourceRoots: Uri[] = [];
    const viewDir = inspectViewPath();
    if (viewDir) {
      localResourceRoots.push(Uri.file(viewDir.path));
    }
    super(context, kLogViewId, "Inspect View", localResourceRoots, InspectLogviewWebview);
  }

  public showLogFile(uri: Uri, onClose?: () => void) {
    this.showLogview({ url: uri.toString() }, onClose, true);
  }

  public showLogview(state: LogviewState = {}, onClose?: () => void, activate = true) {
    if (!this.activeView_ && !activate) {
      return;
    }

    this.setOnShow(() => {
      this.updatePreview(state).catch(() => { });
    });
    if (onClose) {
      this.setOnClose(onClose);
    }


    if (this.activeView_) {
      this.revealWebview();
    } else {
      this.lastState_ = undefined;
      this.showWebview(state, {
        preserveFocus: true,
        viewColumn: ViewColumn.Beside,
      });
    }
  }

  public viewColumn() {
    return this.activeView_?.webviewPanel().viewColumn;
  }

  protected override onViewStateChanged(): void {
    this.updatePreview(this.lastState_).catch(() => { });
  }

  private async updatePreview(state?: LogviewState) {
    if (this.isVisible()) {
      // see if there is an explcit state update (otherwise inspect hte active editor)
      if (state) {
        await this.updateViewState(state);
      } else {
        await this.updateViewState({});
      }
    }
  }

  private async updateViewState(state: LogviewState) {
    if (this.lastState_ !== state) {
      this.lastState_ = state;
      await this.activeView_?.update(state);
    }
  }

  private lastState_: LogviewState | undefined;
}

class InspectLogviewWebview extends InspectWebview<LogviewState> {
  public constructor(
    context: ExtensionContext,
    state: LogviewState,
    webviewPanel: WebviewPanel
  ) {
    super(context, state, webviewPanel);

    // this isn't currently used by we might want to in the future we leave it in
    this._register(
      this._webviewPanel.webview.onDidReceiveMessage(async (e: { type: string, url: string }) => {
        switch (e.type) {
          case "openExternal":
            try {
              const url = Uri.parse(e.url);
              await env.openExternal(url);
            } catch {
              // Noop
            }
            break;
        }
      })
    );


    const disconnecct = webviewPanelJsonRpcServer(this._webviewPanel, {
      [kMethodEvalLogs]: evalLogs,
      [kMethodEvalLog]: (params: unknown[]) => evalLog(params[0] as string, params[1] as boolean),
      [kMethodEvalLogHeaders]: (params: unknown[]) => evalLogHeaders(params[0] as string[])
    });
    this._register(new Disposable(disconnecct));

  }



  public async update(state: LogviewState) {
    await this._webviewPanel.webview.postMessage({
      type: "updateState",
      ...state,
    });
  }

  protected getHtml(): string {

    // read the index.html from the log view directory
    const viewDir = inspectViewPath();
    if (viewDir) {

      // get nonce
      const nonce = getNonce();

      // file uri for view dir
      const viewDirUri = Uri.file(viewDir.path);

      // get base html
      let indexHtml = readFileSync(viewDir.child("index.html").path, "utf-8");

      // add content security policy
      indexHtml = indexHtml.replace("<head>\n", `<head>
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this._webviewPanel.webview.cspSource} data:; font-src ${this._webviewPanel.webview.cspSource}; style-src ${this._webviewPanel.webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  `);

      // funtion to resolve resource uri
      const resourceUri = (path: string) => this._webviewPanel.webview.asWebviewUri(
        Uri.joinPath(viewDirUri, path)
      ).toString();

      // fixup css references
      indexHtml = indexHtml.replace(/href="\.([^"]+)"/g, (_, p1: string) => {
        return `href="${resourceUri(p1)}"`;
      });

      // fixup js references 
      indexHtml = indexHtml.replace(/src="\.([^"]+)"/g, (_, p1: string) => {
        return `src="${resourceUri(p1)}"`;
      });

      // nonces for scripts
      indexHtml = indexHtml.replace(/<script([ >])/g, `<script nonce="${nonce}"$1`);

      // fixup import maps
      indexHtml = indexHtml.replace(/": "\.([^?"]+)(["?])/g, (_, p1: string, p2: string) => {
        return `": "${resourceUri(p1)}${p2}`;
      });

      // fixup App.mjs
      indexHtml = indexHtml.replace(/"\.(\/App\.mjs)"/g, (_, p1: string) => {
        return `"${resourceUri(p1)}"`;
      });

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
}


function evalLogs(): Promise<string | undefined> {
  const workspacePath = activeWorkspacePath();
  return Promise.resolve(inspectEvalLogs(workspacePath));
}

function evalLog(file: string, headerOnly: boolean): Promise<string | undefined> {
  const workspacePath = activeWorkspacePath();
  return Promise.resolve(inspectEvalLog(workspacePath, file, headerOnly));
}

function evalLogHeaders(files: string[]) {
  const workspacePath = activeWorkspacePath();
  return Promise.resolve(inspectEvalLogHeaders(workspacePath, files));
}


export function webviewPanelJsonRpcServer(
  webviewPanel: WebviewPanel,
  methods: Record<string, JsonRpcServerMethod> | ((name: string) => JsonRpcServerMethod | undefined)): () => void {
  const target: JsonRpcPostMessageTarget = {
    postMessage: (data: unknown) => {
      void webviewPanel.webview.postMessage(data);
    },
    onMessage: (handler: (data: unknown) => void) => {
      const disposable = webviewPanel.webview.onDidReceiveMessage(ev => {
        handler(ev);
      });
      return () => {
        disposable.dispose();
      };
    }
  };
  return jsonRpcPostMessageServer(target, methods);
}
