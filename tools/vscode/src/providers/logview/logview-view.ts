
import {
  ExtensionContext,
  Uri,
  ViewColumn,
  window,
  workspace,
} from "vscode";

import {
  InspectWebview,
  InspectWebviewManager,
} from "../../components/webview";
import { dirname } from "../../core/uri";
import { inspectViewPath } from "../../inspect/props";
import {
  InspectChangedEvent,
  InspectManager,
} from "../inspect/inspect-manager";
import { LogviewState } from "./logview-state";
import { ExtensionHost, HostWebviewPanel } from "../../hooks";
import { showError } from "../../components/error";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { LogviewPanel } from "./logview-panel";
import { InspectLogsWatcher } from "../inspect/inspect-logs-watcher";

const kLogViewId = "inspect.logview";


export class InspectViewManager {
  constructor(
    context: ExtensionContext,
    logsWatcher: InspectLogsWatcher,
    private readonly webViewManager_: InspectViewWebviewManager,
    private readonly settingsMgr_: InspectSettingsManager,
    private readonly envMgr_: WorkspaceEnvManager,
  ) {

    context.subscriptions.push(logsWatcher.onInspectLogCreated((e) => {

      // don't show the log if this was an external workspace
      if (e.externalWorkspace) {
        return;
      }

      const openAction = settingsMgr_.getSettings().openLogView
        ? "open"
        : undefined;
      this
        .showLogFile(e.log, openAction)
        .catch(async (err: Error) => {
          await showError(
            "Unable to preview log file - failed to start Inspect View",
            err
          );
        });

    }));

  }

  public async showLogFile(logFile: Uri, activation?: "open" | "activate") {
    const settings = this.settingsMgr_.getSettings();
    if (settings.logViewType === "text" && logFile.scheme === "file") {
      await workspace.openTextDocument(logFile).then(async (doc) => {
        await window.showTextDocument(doc, {
          preserveFocus: true,
          viewColumn: ViewColumn.Two,
        });
      });
    } else {
      await this.webViewManager_.showLogFile(logFile, activation);
    }
  }

  public async showInspectView() {
    // See if there is a log dir
    const log_dir = this.envMgr_.getDefaultLogDir();

    // Show the log view for the log dir (or the workspace)
    await this.webViewManager_.showLogview({ log_dir }, "activate");
  }

  public viewColumn() {
    return this.webViewManager_.viewColumn();
  }
}



export class InspectViewWebviewManager extends InspectWebviewManager<
  InspectViewWebview,
  LogviewState
> {
  constructor(
    inspectManager: InspectManager,
    server: InspectViewServer,
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
      server,
      kLogViewId,
      "Inspect View",
      localResourceRoots,
      InspectViewWebview,
      host
    );
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

    // update state for restoring the workspace
    this.setWorkspaceState(state);

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

  protected override getWorkspaceState(): LogviewState | undefined {
    const data: Record<string, string> = this.context_.workspaceState.get(this.kInspectViewState, {});
    if (data) {
      return {
        log_dir: Uri.parse(data["log_dir"]),
        log_file: data["log_file"] ? Uri.parse(data["log_file"]) : undefined,
        background_refresh: !!data["background_refresh"]
      };
    } else {
      return this.lastState_;
    }
  }

  protected setWorkspaceState(state: LogviewState) {
    void this.context_.workspaceState.update(this.kInspectViewState, {
      log_dir: state.log_dir.toString(),
      log_file: state.log_file?.toString(),
      background_refresh: state.background_refresh
    });
  }

  private kInspectViewState = 'inspectViewState';

  private lastState_?: LogviewState = undefined;
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

class InspectViewWebview extends InspectWebview<LogviewState> {

  private readonly logviewPanel_: LogviewPanel;

  public constructor(
    context: ExtensionContext,
    server: InspectViewServer,
    state: LogviewState,
    webviewPanel: HostWebviewPanel
  ) {
    super(context, server, state, webviewPanel);

    this.logviewPanel_ = new LogviewPanel(
      webviewPanel,
      context,
      server,
      "dir",
      state.log_dir
    );
    this._register(this.logviewPanel_);

    this._register(
      this._webviewPanel.webview.onDidReceiveMessage(
        async (e: { type: string; url: string;[key: string]: unknown }) => {
          switch (e.type) {
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

    this.show(state);
  }

  public setManager(manager: InspectViewWebviewManager) {
    if (this._manager !== manager) {
      this._manager = manager;
    }
  }
  _manager: InspectViewWebviewManager | undefined;

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
    return this.logviewPanel_.getHtml(state);
  }
}

