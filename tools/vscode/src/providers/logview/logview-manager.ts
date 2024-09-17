import { Uri, ViewColumn, window, workspace } from "vscode";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { activeWorkspaceFolder } from "../../core/workspace";
import { workspacePath } from "../../core/path";
import { kInspectEnvValues } from "../inspect/inspect-constants";
import { join } from "path";

export class InspectLogviewManager {
  constructor(
    private readonly webViewManager_: InspectLogviewWebviewManager,
    private readonly settingsMgr_: InspectSettingsManager,
    private readonly envMgr_: WorkspaceEnvManager
  ) { }

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
    const envVals = this.envMgr_.getValues();
    const env_log = envVals[kInspectEnvValues.logDir];

    // If there is a log dir, try to parse and use it
    let log_uri;
    try {
      log_uri = Uri.parse(env_log, true);
    } catch {
      // This isn't a uri, bud
      const logDir = env_log ? workspacePath(env_log).path : join(workspacePath().path, "logs");
      log_uri = Uri.file(logDir);
    }

    // Show the log view for the log dir (or the workspace)
    const log_dir = log_uri || activeWorkspaceFolder().uri;
    await this.webViewManager_.showLogview({ log_dir }, "activate");
  }

  public viewColumn() {
    return this.webViewManager_.viewColumn();
  }
}
