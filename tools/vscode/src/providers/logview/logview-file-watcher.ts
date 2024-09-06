import { Uri, Disposable } from "vscode";
import { InspectLogviewManager } from "./logview-manager";

import { showError } from "../../components/error";
import { inspectLastEvalPath } from "../../inspect/props";
import { existsSync, readFileSync, statSync } from "fs";
import { log } from "../../core/log";
import { toAbsolutePath, workspaceRelativePath } from "../../core/path";
import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { withMinimumInspectVersion } from "../../inspect/version";
import { kInspectChangeEvalSignalVersion } from "../inspect/inspect-constants";
import { InspectSettingsManager } from "../settings/inspect-settings";

export class LogViewFileWatcher implements Disposable {
  constructor(
    private readonly logviewManager_: InspectLogviewManager,
    private readonly workspaceStateManager_: WorkspaceStateManager,
    private readonly settingsMgr_: InspectSettingsManager
  ) {
    log.appendLine("Watching for evaluation logs");
    this.lastEval_ = Date.now();

    const evalSignalFile = inspectLastEvalPath()?.path;

    this.watchInterval_ = setInterval(() => {
      if (evalSignalFile && existsSync(evalSignalFile)) {
        const updated = statSync(evalSignalFile).mtime.getTime();
        if (updated > this.lastEval_) {
          this.lastEval_ = updated;

          let evalLogPath;
          let workspaceId;
          const contents = readFileSync(evalSignalFile, { encoding: "utf-8" });

          // Parse the eval signal file result
          withMinimumInspectVersion(
            kInspectChangeEvalSignalVersion,
            () => {
              // 0.3.10- or later
              const contentsObj = JSON.parse(contents) as {
                location: string;
                workspace_id?: string;
              };
              evalLogPath = contentsObj.location;
              workspaceId = contentsObj.workspace_id;
            },
            () => {
              // 0.3.8 or earlier
              evalLogPath = contents;
            }
          );

          if (evalLogPath) {
            if (
              !workspaceId ||
              workspaceId === this.workspaceStateManager_.getWorkspaceInstance()
            ) {
              log.appendLine(
                `New log: ${workspaceRelativePath(toAbsolutePath(evalLogPath))}`
              );
              // Show the log file
              const openAction = settingsMgr_.getSettings().openLogView
                ? "open"
                : undefined;
              this.logviewManager_
                .showLogFile(Uri.parse(evalLogPath), openAction)
                .catch(async (err: Error) => {
                  await showError(
                    "Unable to preview log file - failed to start Inspect View",
                    err
                  );
                });
            }
          }
        }
      }
    }, 500);
  }
  private lastEval_: number;
  private watchInterval_: NodeJS.Timeout;

  dispose() {
    if (this.watchInterval_) {
      log.appendLine("Stopping watching for new evaluations logs");
      clearTimeout(this.watchInterval_);
    }
  }
}
