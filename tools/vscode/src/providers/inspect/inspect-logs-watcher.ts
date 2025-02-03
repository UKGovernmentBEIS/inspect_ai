import { Disposable, Event, EventEmitter, Uri } from "vscode";

import { inspectLastEvalPaths } from "../../inspect/props";
import { existsSync, readFileSync, statSync } from "fs";
import { log } from "../../core/log";
import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { withMinimumInspectVersion } from "../../inspect/version";
import { kInspectChangeEvalSignalVersion } from "./inspect-constants";
import { resolveToUri } from "../../core/uri";

export interface InspectLogCreatedEvent {
  log: Uri
  externalWorkspace: boolean;
}

export class InspectLogsWatcher implements Disposable {
  constructor(
    private readonly workspaceStateManager_: WorkspaceStateManager,
  ) {
    log.appendLine("Watching for evaluation logs");
    this.lastEval_ = Date.now();

    const evalSignalFiles = inspectLastEvalPaths().map(path => path.path);

    this.watchInterval_ = setInterval(() => {
      for (const evalSignalFile of evalSignalFiles) {
        if (existsSync(evalSignalFile)) {
          const updated = statSync(evalSignalFile).mtime.getTime();
          if (updated > this.lastEval_) {
            this.lastEval_ = updated;

            let evalLogPath: string | undefined;
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

            if (evalLogPath !== undefined) {
              // see if this is another instance of vscode
              const externalWorkspace = !!workspaceId && workspaceId !== this.workspaceStateManager_.getWorkspaceInstance();

              // log
              log.appendLine(`New log: ${evalLogPath}`);

              // fire event
              try {
                const logUri = resolveToUri(evalLogPath);
                this.onInspectLogCreated_.fire({ log: logUri, externalWorkspace });
              } catch (error) {
                log.appendLine(`Unexpected error parsing URI ${evalLogPath}`);
              }

            }
          }
        }
      }
    }, 500);
  }
  private lastEval_: number;
  private watchInterval_: NodeJS.Timeout;

  private readonly onInspectLogCreated_ =
    new EventEmitter<InspectLogCreatedEvent>();
  public readonly onInspectLogCreated: Event<InspectLogCreatedEvent> =
    this.onInspectLogCreated_.event;

  dispose() {
    if (this.watchInterval_) {
      log.appendLine("Stopping watching for new evaluations logs");
      clearTimeout(this.watchInterval_);
    }
  }
}
