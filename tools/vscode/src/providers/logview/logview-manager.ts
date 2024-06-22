import { Uri, ViewColumn, window, workspace } from "vscode";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { activeWorkspaceFolder } from "../../core/workspace";
import { workspacePath } from "../../core/path";
import { kInspectEnvValues } from "../inspect/inspect-constants";


export class InspectLogviewManager {
  constructor(
    private readonly webViewManager_: InspectLogviewWebviewManager,
    private readonly settingsMgr_: InspectSettingsManager,
    private readonly envMgr_: WorkspaceEnvManager
  ) { }

  public async showLogFile(logFile: Uri) {
    if (this.settingsMgr_.getSettings().logViewType === "text" && logFile.scheme === "file") {
      await workspace.openTextDocument(logFile).then(async (doc) => {
        await window.showTextDocument(doc, {
          preserveFocus: true,
          viewColumn: ViewColumn.Two,
        });
      });
    } else {

      // Show the log file
      this.webViewManager_.showLogFile(logFile);
    }
  }

  public showInspectView() {

    // See if there is a log dir
    const envVals = this.envMgr_.getValues();
    const env_log = envVals[kInspectEnvValues.logDir];

    // If there is a log dir, try to parse and use it
    let log_uri;
    try {
      log_uri = Uri.parse(env_log, true);
    } catch {
      // This isn't a uri, bud
      log_uri = Uri.file(workspacePath(env_log).path);
    }

    // Show the log view for the log dir (or the workspace)
    const log_dir = log_uri || activeWorkspaceFolder().uri;
    this.webViewManager_.showLogview({ log_dir });
  }

  public viewColumn() {
    return this.webViewManager_.viewColumn();
  }
}

