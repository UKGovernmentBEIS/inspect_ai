import { Disposable, Event, EventEmitter, ExtensionContext } from "vscode";
import { pythonInterpreter } from "../../core/python";
import { inspectBinPath } from "../../inspect/props";
import { AbsolutePath } from "../../core/path";
import { delimiter } from "path";

// Activates the provider which tracks the availability of Inspect
export function activateInspectManager(context: ExtensionContext) {
  const inspectManager = new InspectManager(context);

  // Initialize the terminal with the inspect bin path
  // on the path (if needed)
  const terminalEnv = terminalEnvironment(context);
  context.subscriptions.push(inspectManager.onInspectChanged((e: InspectChangedEvent) => {
    terminalEnv.update(e.binPath);
  }));
  terminalEnv.update(inspectBinPath());

  return inspectManager;
}

// Fired when the active task changes
export interface InspectChangedEvent {
  available: boolean;
  binPath: AbsolutePath | null;
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
  private inspectBinPath_: string | undefined = undefined;

  get available(): boolean {
    return this.inspectBinPath_ !== null;
  }

  private updateInspectAvailable() {
    const binPath = inspectBinPath();
    const available = binPath !== null;
    const valueChanged = this.inspectBinPath_ !== binPath?.path;
    if (valueChanged) {
      this.inspectBinPath_ = binPath?.path;
      this.onInspectChanged_.fire({ available: !!this.inspectBinPath_, binPath });
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

// Configures the terminal environment to support inspect. We do this
// to ensure the the 'inspect' command will work from within the
// terminal (especially in cases where the global interpreter is being used)
const terminalEnvironment = (context: ExtensionContext) => {
  const filter = (binPath: AbsolutePath | null) => {
    switch (process.platform) {
      case "win32":
        {
          const localPath = process.env['LocalAppData'];
          if (localPath) {
            return binPath?.path.startsWith(localPath);
          }
          return false;
        }
      case "linux":
        return binPath && binPath.path.includes(".local/bin");
      default:
        return false;
    }
  };

  return {
    update: (binPath: AbsolutePath | null) => {
      // The path info
      const env = context.environmentVariableCollection;
      env.delete('PATH');
      // Actually update the path
      const binDir = binPath?.dirname();
      if (binDir && filter(binPath)) {
        env.append('PATH', `${delimiter}${binDir.path}`);
      }
    }
  };
};
