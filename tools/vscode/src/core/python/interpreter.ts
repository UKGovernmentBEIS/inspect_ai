import {
  extensions,
  Event,
  EventEmitter,
  Disposable,
  Uri,
  Extension,
} from "vscode";
import { activeWorkspaceFolder } from "../workspace";
import { log } from "../log";
import { runProcess } from "../process";

export function pythonInterpreter(): PythonInterpreter {
  return pythonInterpreter_;
}

export async function initPythonInterpreter(): Promise<Disposable> {
  const pyExtension = extensions.getExtension("ms-python.python");
  if (pyExtension && !pyExtension.isActive) {
    log.info("Activating Python extension");
    await pyExtension.activate();
  }
  pythonInterpreter_ = new PythonInterpreter(
    pyExtension as Extension<PythonExtension> | undefined
  );
  return pythonInterpreter_;
}

let pythonInterpreter_: PythonInterpreter;

export class PythonInterpreter implements Disposable {
  private execCommand_: string[] | null;
  private onDidChangeEmitter_: EventEmitter<Uri | undefined> = new EventEmitter<
    Uri | undefined
  >();
  private readonly eventHandle_?: Disposable;

  constructor(private readonly pyExtension_?: Extension<PythonExtension>) {
    // get exec command
    this.execCommand_ = this.getExecCommand();
    this.updatePythonBinDir();

    // subscribe to changes
    if (this.pyExtension_) {
      const api = this.pyExtension_.exports;
      this.eventHandle_ = api.settings.onDidChangeExecutionDetails((e) => {
        const execCommand = this.getExecCommand();
        if (execCommand) {
          this.execCommand_ = execCommand;
          this.updatePythonBinDir();
          this.onDidChangeEmitter_.fire(e);
        }
      });
    }
  }
  private pythonBinDir_: string | null = null;

  dispose() {
    if (this.eventHandle_) {
      this.eventHandle_.dispose();
    }
  }

  get available(): boolean {
    return !!this.execCommand_;
  }

  get execCommand(): string[] | null {
    return this.execCommand_;
  }

  get pythonBinDir(): string | null {
    return this.pythonBinDir_;
  }

  private updatePythonBinDir() {
    // Find the bin dir
    if (this.execCommand_ !== null) {
      const args = [
        ...this.execCommand_.slice(1),
        "-c",
        "import sys; print(sys.prefix);",
      ];
      const result = runProcess(this.execCommand_[0], args);
      this.pythonBinDir_ = result.trim();
    }
  }

  public readonly onDidChange: Event<Uri | undefined> =
    this.onDidChangeEmitter_.event;

  private getExecCommand(): string[] | null {
    const workspaceFolder = activeWorkspaceFolder();
    if (this.pyExtension_) {
      const execDetails =
        this.pyExtension_.exports.settings.getExecutionDetails(
          workspaceFolder.uri
        ) as { execCommand?: string[] };
      if (Array.isArray(execDetails?.execCommand)) {
        log.info(
          "Found python exec command: " + execDetails?.execCommand.join(" ")
        );
        return execDetails?.execCommand;
      } else {
        log.info("No Python exec command found.");
      }
    }
    return null;
  }
}

// from: https://github.com/microsoft/vscode-python/blob/main/src/client/api.ts
interface PythonExtension {
  settings: {
    /**
     * An event that is emitted when execution details (for a resource) change. For instance, when interpreter configuration changes.
     */
    readonly onDidChangeExecutionDetails: Event<Uri | undefined>;
    /**
     * Returns all the details the consumer needs to execute code within the selected environment,
     * corresponding to the specified resource taking into account any workspace-specific settings
     * for the workspace to which this resource belongs.
     * @param {Uri | undefined} [resource] A resource for which the setting is asked for.
     * * When no resource is provided, the setting scoped to the first workspace folder is returned.
     * * If no folder is present, it returns the global setting.
     * @returns {({ execCommand: string[] | undefined })}
     */
    getExecutionDetails(resource?: Uri | undefined): {
      /**
       * E.g of execution commands returned could be,
       * * `['<path to the interpreter set in settings>']`
       * * `['<path to the interpreter selected by the extension when setting is not set>']`
       * * `['conda', 'run', 'python']` which is used to run from within Conda environments.
       * or something similar for some other Python environments.
       *
       * @type {(string[] | undefined)} When return value is `undefined`, it means no interpreter is set.
       * Otherwise, join the items returned using space to construct the full execution command.
       */
      execCommand: string[] | undefined;
    };
  };
}
