import { Command } from "../../core/command";
import {
  Disposable,
  EventEmitter,
  Event,
  Uri,
} from "vscode";
import { clearEnv, readEnv, writeEnv } from "../../core/env";
import { isEqual } from "lodash";
import { workspaceEnvCommands } from "./workspace-env-commands";
import { activeWorkspaceFolder } from "../../core/workspace";
import { log } from "../../core/log";
import { existsSync, statSync } from "fs";
import { toAbsolutePath, workspacePath, workspaceRelativePath } from "../../core/path";
import { kInspectEnvValues } from "../inspect/inspect-constants";
import { join } from "path";

export function activateWorkspaceEnv(): [Command[], WorkspaceEnvManager] {
  // Monitor changes to the file
  const envManager = new WorkspaceEnvManager();
  return [workspaceEnvCommands(), envManager];
}

// Fired when the active task changes
export interface EnvironmentChangedEvent { }

// Manages the workspace environment
export class WorkspaceEnvManager implements Disposable {
  constructor() {
    const envUri = this.getEnvUri();
    this.env = readEnv(envUri);
    this.lastUpdated_ = Date.now();
    const envRelativePath = workspaceRelativePath(toAbsolutePath(envUri.fsPath));
    log.appendLine(`Watching ${envRelativePath}`);
    this.envWatcher_ = setInterval(() => {
      if (existsSync(envUri.fsPath)) {
        const envUpdated = statSync(envUri.fsPath).mtime.getTime();
        if (envUpdated > this.lastUpdated_) {
          this.lastUpdated_ = envUpdated;
          const newEnv = readEnv(envUri);
          if (!isEqual(this.env, newEnv)) {
            log.appendLine(`${envRelativePath} changed`);
            this.env = newEnv;
            this.onEnvironmentChanged_.fire({});
          }
        }
      }
    }, 1000);
  }
  private envWatcher_: NodeJS.Timeout;
  private lastUpdated_: number;
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

  public getDefaultLogDir() {
    // See if there is a log dir
    const envVals = this.getValues();
    const env_log = envVals[kInspectEnvValues.logDir];

    // If there is a log dir, try to parse and use it
    try {
      return Uri.parse(env_log, true);
    } catch {
      // This isn't a uri, bud
      const logDir = env_log ? workspacePath(env_log).path : join(workspacePath().path, "logs");
      return Uri.file(logDir);
    }

  }

  private readonly onEnvironmentChanged_ =
    new EventEmitter<EnvironmentChangedEvent>();
  public readonly onEnvironmentChanged: Event<EnvironmentChangedEvent> =
    this.onEnvironmentChanged_.event;

  [Symbol.dispose](): void {
    throw new Error("Method not implemented.");
  }

  dispose() {
    if (this.envWatcher_) {
      log.appendLine(`Stop watching .env`);
      clearTimeout(this.envWatcher_);
    }
  }
}