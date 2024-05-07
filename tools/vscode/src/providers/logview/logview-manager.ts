import { Uri, ViewColumn, window, workspace } from "vscode";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectSettingsManager } from "../settings/inspect-settings";

export class InspectLogviewManager {
  constructor(
    private readonly webViewManager_: InspectLogviewWebviewManager,
    private readonly settingsMgr_: InspectSettingsManager,
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
    this.webViewManager_.showLogview();
  }

  public viewColumn() {
    return this.webViewManager_.viewColumn();
  }
}

