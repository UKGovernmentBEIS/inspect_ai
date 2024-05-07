import { Command } from "../../core/command";
import {
  Disposable,
  EventEmitter,
  Event,
  FileSystemWatcher,
  OutputChannel,
  Uri,
  workspace,
  GlobPattern,
} from "vscode";
import { clearEnv, readEnv, writeEnv } from "../../core/env";
import { isEqual } from "lodash";
import { workspaceEnvCommands } from "./workspace-env-commands";
import { activeWorkspaceFolder } from "../../core/workspace";

export function activateWorkspaceEnv(outputChannel: OutputChannel): [Command[], WorkspaceEnvManager] {
  // Monitor changes to the file
  const envManager = new WorkspaceEnvManager(outputChannel);
  return [workspaceEnvCommands(), envManager];
}

// Fired when the active task changes
export interface EnvironmentChangedEvent { }

// Manages the workspace environment
export class WorkspaceEnvManager implements Disposable {
  constructor(
    outputChannel: OutputChannel
  ) {

    const envUri = this.getEnvUri();
    this.env = readEnv(envUri);


    // When the file changes, notify listeners if it is 
    // actually different
    const onChange = (uri: Uri) => {
      const newEnv = readEnv(uri);
      if (!isEqual(this.env, newEnv)) {
        this.env = newEnv;
        this.onEnvironmentChanged_.fire({});
      }
    };
    this.envWatcher_ = new EnvFileWatcher("**/.env", outputChannel, onChange);
  }
  private envWatcher_: EnvFileWatcher;
  private env: Record<string, string> = {};

  public getValues(): Record<string, string> {
    return this.env;
  }

  private getEnvUri() {
    const workspaceFolder = activeWorkspaceFolder();
    return Uri.joinPath(workspaceFolder?.uri, ".env");
  }

  public setValues(env: Record<string, string>) {
    const envUri = this.getEnvUri();
    const keys = Object.keys(env);
    keys.forEach((key) => {
      const value = env[key];
      if (value === "") {
        // Only actually clear the value if it has changed
        if (this.env[key] && this.env[key] !== value) {
          delete this.env[key];
          clearEnv(key, envUri);
        }
      } else {
        // Only actually change the value if it has changed
        if (this.env[key] !== value) {
          this.env[key] = value;
          writeEnv(key, value, envUri);
        }
      }
    });
  }

  private readonly onEnvironmentChanged_ =
    new EventEmitter<EnvironmentChangedEvent>();
  public readonly onEnvironmentChanged: Event<EnvironmentChangedEvent> =
    this.onEnvironmentChanged_.event;

  [Symbol.dispose](): void {
    throw new Error("Method not implemented.");
  }

  dispose() {
    this.envWatcher_.dispose();
  }
}

class EnvFileWatcher implements Disposable {
  constructor(
    envGlob: GlobPattern,
    private readonly outputChannel_: OutputChannel,
    onChange: (e: Uri) => void
  ) {
    this.outputChannel_.appendLine("Watching environment...");
    this.watcher = workspace.createFileSystemWatcher(
      envGlob,
      false,
      false,
      false
    );
    const myChanged = (uri: Uri) => {
      onChange(uri);
    };

    this.disposables.push(this.watcher.onDidCreate(myChanged));
    this.disposables.push(this.watcher.onDidChange(myChanged));
    this.disposables.push(this.watcher.onDidDelete(myChanged));
  }
  [Symbol.dispose](): void {
    throw new Error("Method not implemented.");
  }

  dispose() {
    this.disposables.forEach((d) => { d.dispose(); });
    this.outputChannel_.appendLine("Stopping watching environment...");
    this.watcher.dispose();
  }
  private watcher: FileSystemWatcher;
  private disposables: Disposable[] = [];
}


