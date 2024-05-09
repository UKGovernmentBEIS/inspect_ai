import { Uri, Disposable } from "vscode";
import { InspectLogviewManager } from "./logview-manager";

import { showError } from "../../components/error";
import { inspectLastEvalPath } from "../../inspect/props";
import { existsSync, readFileSync, statSync } from "fs";
import { log } from "../../core/log";
import { toAbsolutePath, workspaceRelativePath } from "../../core/path";

export class LogViewFileWatcher implements Disposable {
  constructor(
    private readonly logviewManager_: InspectLogviewManager,
  ) {
    log.appendLine("Watching for evaluation logs");
    this.lastEval_ = Date.now();

    const lastEvalPath = inspectLastEvalPath();
    const lastEvalFile = lastEvalPath?.path;

    this.watchInterval_ = setInterval(() => {
      if (lastEvalFile && existsSync(lastEvalFile)) {
        const updated = statSync(lastEvalFile).mtime.getTime();
        if (updated > this.lastEval_) {
          this.lastEval_ = updated;
          const evalLogPath = readFileSync(lastEvalFile, { encoding: "utf-8" });
          log.appendLine(`New log: ${workspaceRelativePath(toAbsolutePath(evalLogPath))}`);
          this.logviewManager_.showLogFile(Uri.file(evalLogPath)).catch(async (err: Error) => {
            await showError("Unable to preview log file - failed to start Inspect View", err);
          });
        }
      }
    }, 1000);
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