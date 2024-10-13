import { readFileSync } from "fs";

import {
  ExtensionContext,
  MessageItem,
  Uri,
  ViewColumn,
  env,
  window,
} from "vscode";

import {
  InspectWebview,
  InspectWebviewManager,
} from "../../components/webview";
import { getNonce } from "../../core/nonce";
import { workspacePath } from "../../core/path";
import { dirname } from "../../core/uri";
import { inspectViewPath } from "../../inspect/props";
import {
  InspectChangedEvent,
  InspectManager,
} from "../inspect/inspect-manager";
import { LogviewState } from "./commands";
import { ExtensionHost, HostWebviewPanel } from "../../hooks";
import { showError } from "../../components/error";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { jsonRpcPostMessageServer, JsonRpcPostMessageTarget, JsonRpcServerMethod, kMethodEvalLog, kMethodEvalLogBytes, kMethodEvalLogHeaders, kMethodEvalLogs, kMethodEvalLogSize } from "../../core/jsonrpc";

const kLogViewId = "inspect.logview";

export class InspectLogviewWebviewManager extends InspectWebviewManager<
  InspectLogviewWebview,
  LogviewState
> {
  constructor(
    inspectManager: InspectManager,
    viewServer: InspectViewServer,
    context: ExtensionContext,
    host: ExtensionHost
  ) {
    // If the interpreter changes, refresh the tasks
    context.subscriptions.push(
      inspectManager.onInspectChanged((e: InspectChangedEvent) => {
        if (!e.available && this.activeView_) {
          this.activeView_?.dispose();
        }
      })
    );

    // register view dir as local resource root
    const localResourceRoots: Uri[] = [];
    const viewDir = inspectViewPath();
    if (viewDir) {
      localResourceRoots.push(Uri.file(viewDir.path));
    }
    super(
      context,
      kLogViewId,
      "Inspect View",
      localResourceRoots,
      InspectLogviewWebview,
      host
    );

    // ref to view server
    this.viewServer_ = viewServer;

  }
  private activeLogDir_: Uri | null = null;

  public async showLogFile(uri: Uri, activation?: "open" | "activate") {
    // Get the directory name using posix path methods
    const log_dir = dirname(uri);

    await this.showLogview({ log_file: uri, log_dir }, activation);
  }

  public async showLogFileIfOpen(uri: Uri) {
    if (this.isVisible()) {
      // If the viewer is visible / showing, then send a refresh signal

      // Get the directory name using posix path methods
      const log_dir = dirname(uri);
      await this.showLogview({
        log_file: uri,
        log_dir,
        background_refresh: true,
      });
    }
  }

  public async showLogview(
    state: LogviewState,
    activation?: "open" | "activate"
  ) {
    switch (activation) {
      case "open":
        await this.displayLogFile(state, activation);
        break;
      case "activate":
        await this.displayLogFile(state, activation);
        break;
      default:
        // No activation, just refresh this in the background
        if (this.isVisible() && state.log_file) {
          this.updateViewState(state);

          // Signal the viewer to either perform a background refresh
          // or to check whether the view is focused and call us back to
          // display a log file
          await this.activeView_?.backgroundUpdate(
            state.log_file.path,
            state.log_dir.toString()
          );
        }
        return;
    }
  }

  public viewColumn() {
    return this.activeView_?.webviewPanel().viewColumn;
  }

  protected override async onViewStateChanged(): Promise<void> {
    if (this.isActive()) {
      await this.updateVisibleView();
    }
  }

  public async displayLogFile(
    state: LogviewState,
    activation?: "open" | "activate"
  ) {
    // Determine whether we are showing a log viewer for this directory
    // If we aren't close the log viewer so a fresh one can be opened.
    if (
      this.activeLogDir_ !== null &&
      state.log_dir.toString() !== this.activeLogDir_.toString()
    ) {
      // Close it
      this.activeView_?.dispose();
      this.activeView_ = undefined;
    }

    // Note the log directory that we are showing
    this.activeLogDir_ = state.log_dir || null;

    // Update the view state
    this.updateViewState(state);

    // Ensure that we send the state once the view is loaded
    this.setOnShow(() => {
      this.updateVisibleView().catch(() => { });
    });

    // If the view is closed, clear the state
    this.setOnClose(() => {
      this.lastState_ = undefined;
      this.activeLogDir_ = null;
    });

    // Actually reveal or show the webview
    if (this.activeView_) {
      if (activation === "activate") {
        this.revealWebview(activation !== "activate");
      } else if (state.log_file) {
        await this.activeView_?.backgroundUpdate(
          state.log_file.path,
          state.log_dir.toString()
        );
      }
    } else {
      if (activation) {
        this.showWebview(state, {
          preserveFocus: activation !== "activate",
          viewColumn: ViewColumn.Beside,
        });
      }
    }

    // TODO: there is probably a better way to handle this
    this.activeView_?.setManager(this);
  }

  private async updateVisibleView() {
    if (this.activeView_ && this.isVisible() && this.lastState_) {
      await this.activeView_.update(this.lastState_);
    }
  }

  private updateViewState(state: LogviewState) {
    if (!this.lastState_ || !logStateEquals(state, this.lastState_)) {
      this.lastState_ = state;
    }
  }

  protected onViewCreated() {
    this.viewDisconnect_ = webviewPanelJsonRpcServer(this.activeView_!.webviewPanel(), {
      [kMethodEvalLogs]: async () => this.viewServer_.evalLogs(this.lastState_!.log_dir),
      [kMethodEvalLog]: (params: unknown[]) => this.viewServer_.evalLog(params[0] as string, params[1] as number | boolean),
      [kMethodEvalLogSize]: (params: unknown[]) => this.viewServer_.evalLogSize(params[0] as string),
      [kMethodEvalLogBytes]: (params: unknown[]) => this.viewServer_.evalLogBytes(params[0] as string, params[1] as number, params[2] as number),
      [kMethodEvalLogHeaders]: (params: unknown[]) => this.viewServer_.evalLogHeaders(params[0] as string[])
    });
  }

  protected onViewDestroyed() {
    // disconnect previous view if we had one
    if (this.viewDisconnect_) {
      this.viewDisconnect_();
      this.viewDisconnect_ = undefined;
    }
  }

  private viewServer_: InspectViewServer;
  private lastState_?: LogviewState = undefined;
  private viewDisconnect_?: VoidFunction = undefined;
}

const logStateEquals = (a: LogviewState, b: LogviewState) => {
  if (a.log_dir.toString() !== b.log_dir.toString()) {
    return false;
  }

  if (!a.log_file && b.log_file) {
    return false;
  } else if (a.log_file && !b.log_file) {
    return false;
  } else if (a.log_file && b.log_file) {
    return a.log_file.toString() === b.log_file.toString();
  }
  return true;
};

class InspectLogviewWebview extends InspectWebview<LogviewState> {
  public constructor(
    context: ExtensionContext,
    state: LogviewState,
    webviewPanel: HostWebviewPanel
  ) {
    super(context, state, webviewPanel);
    this._register(
      this._webviewPanel.webview.onDidReceiveMessage(
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
            case "displayLogFile":
              {
                if (e.log_dir && this._manager) {
                  const state: LogviewState = {
                    log_file: Uri.parse(e.url),
                    log_dir: Uri.parse(e.log_dir as string),
                  };
                  await this._manager.displayLogFile(state, "open");
                } else {
                  await showError(
                    "Unable to display log file because of a missing log_dir or manager. This is an unexpected error, please report it."
                  );
                }
              }
              break;
          }
        }
      )
    );


  }

  public setManager(manager: InspectLogviewWebviewManager) {
    if (this._manager !== manager) {
      this._manager = manager;
    }
  }
  _manager: InspectLogviewWebviewManager | undefined;

  public async update(state: LogviewState) {
    await this._webviewPanel.webview.postMessage({
      type: "updateState",
      url: state.log_file?.toString(),
    });
  }

  public async backgroundUpdate(file: string, log_dir: string) {
    await this._webviewPanel.webview.postMessage({
      type: "backgroundUpdate",
      url: file,
      log_dir,
    });
  }

  protected getHtml(state: LogviewState): string {
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
        url: state?.log_file?.toString(),
      };
      const stateScript =
        state && state.log_file
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
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this._webviewPanel.webview.cspSource
        } data:; font-src ${this._webviewPanel.webview.cspSource
        } data:; style-src ${this._webviewPanel.webview.cspSource
        } 'unsafe-inline'; worker-src 'self' ${this._webviewPanel.webview.cspSource
        } blob:; script-src 'nonce-${nonce}' 'unsafe-eval'; connect-src ${this._webviewPanel.webview.cspSource
        };">
    ${stateScript}
    ${overrideCssHtml}

    `
      );

      // function to resolve resource uri
      const resourceUri = (path: string) =>
        this._webviewPanel.webview
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



