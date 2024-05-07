import { Disposable, Event, EventEmitter, ExtensionContext } from "vscode";
import { pythonInterpreter } from "../../core/python";
import { inspectBinPath } from "../../inspect/props";
import { constants, existsSync, promises } from "fs";

// Activates the provider which tracks the availability of Inspect
export function activateInspectManager(context: ExtensionContext) {
  const inspectManager = new InspectManager(context);
  return inspectManager;
}

// Fired when the active task changes
export interface InspectChangedEvent {
  available: boolean;
}

export class InspectManager implements Disposable {
  constructor(context: ExtensionContext) {
    // If the interpreter changes, refresh the tasks
    context.subscriptions.push(
      pythonInterpreter().onDidChange(() => {
        this.updateInspectAvailable();
      })
    );
    this.updateInspectAvailable();
  }
  private inspectAvailable_: boolean = false;

  get available(): boolean {
    return !!this.inspectAvailable_;
  }

  private updateInspectAvailable() {
    const inspectPath = inspectBinPath();
    const available = inspectPath !== null && existsSync(inspectPath.path);
    const valueChanged = this.inspectAvailable_ !== available;
    this.inspectAvailable_ = available;
    if (valueChanged) {
      this.onInspectChanged_.fire({ available: this.inspectAvailable_ });
    }
    if (inspectPath && !available) {
      this.watchForInspect(inspectPath.path);
    }
  }

  watchForInspect(path: string) {
    this.inspectTimer = setInterval(() => {
      this.checkFileExistence(path);
    }, 1000);
  }

  checkFileExistence(filePath: string) {
    promises.access(filePath, constants.F_OK)
      .then(() => {
        if (this.inspectTimer) {
          clearInterval(this.inspectTimer);
          this.inspectTimer = null;
          this.updateInspectAvailable();
        }
      })
      .catch(() => {
        console.log(`File does not exist: ${filePath}`);
      });
  }

  private inspectTimer: NodeJS.Timeout | null = null;

  dispose() {
    if (this.inspectTimer) {
      clearInterval(this.inspectTimer);
      this.inspectTimer = null;
    }
  }




  private readonly onInspectChanged_ = new EventEmitter<InspectChangedEvent>();
  public readonly onInspectChanged: Event<InspectChangedEvent> =
    this.onInspectChanged_.event;
}
