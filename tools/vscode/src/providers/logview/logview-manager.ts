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
    // Show the log view for the default log dir (or the workspace)
    await this.webViewManager_.showLogview({ log_dir: this.envMgr_.getDefaultLogDir() }, "activate");
  }

  public viewColumn() {
    return this.webViewManager_.viewColumn();
  }
}
