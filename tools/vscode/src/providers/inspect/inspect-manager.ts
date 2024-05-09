import { Disposable, Event, EventEmitter, ExtensionContext } from "vscode";
import { pythonInterpreter } from "../../core/python";
import { inspectBinPath } from "../../inspect/props";

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
    const available = inspectBinPath() !== null;
    const valueChanged = this.inspectAvailable_ !== available;
    this.inspectAvailable_ = available;
    if (valueChanged) {
      this.onInspectChanged_.fire({ available: this.inspectAvailable_ });
    }
    if (!available) {
      this.watchForInspect();
    }
  }

  watchForInspect() {
    this.inspectTimer = setInterval(() => {
      const path = inspectBinPath();
      if (path) {
        if (this.inspectTimer) {
          clearInterval(this.inspectTimer);
          this.inspectTimer = null;
          this.updateInspectAvailable();
        }
      }
    }, 3000);
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
