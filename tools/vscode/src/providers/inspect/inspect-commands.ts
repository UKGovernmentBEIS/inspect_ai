import { ExtensionContext, Disposable, commands } from "vscode";


import { join } from "node:path";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";

import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { userDataDir } from "../../core/appdirs";
import { log } from "../../core/log";
import { kPythonPackageName } from "../../inspect/props";
import { removeFilesSync } from "../../core/file";


export function activateInspectCommands(
  stateManager: WorkspaceStateManager,
  context: ExtensionContext) {
  const inspectCommands = new InspectCommandDispatcher(stateManager);
  context.subscriptions.push(inspectCommands);
}


export class InspectCommandDispatcher implements Disposable {

  constructor(stateManager: WorkspaceStateManager) {
    // init commands dir and remove any existing commands
    this.commandsDir_ = inspectCommandsDir(stateManager);
    this.collectCommandsRequest();

    // watch for commands
    log.appendLine(`Watching for commands (${this.commandsDir_})`);
    this.watchInterval_ = setInterval(() => {
      (async () => {
        const commandsRequest = this.collectCommandsRequest();
        if (commandsRequest) {
          for (const command of commandsRequest) {
            log.appendLine(`Found command: ${command.command}`);
            log.appendLine(`Executing VS Code command ${command.command}`);
            await commands.executeCommand(command.command, ...command.args);
          }
        }
      })().catch(error => {
        // Handle errors if needed
        console.error(error);
      });
    }, 1000);
  }

  collectCommandsRequest(): Array<{ command: string, args: unknown[] }> | null {
    const commandFiles = readdirSync(this.commandsDir_);
    if (commandFiles.length > 0) {
      // read at most a single command and remove all of the others
      const commandFile = commandFiles[0];
      const commandContents = readFileSync(join(this.commandsDir_, commandFile), { encoding: "utf-8" });
      removeFilesSync(commandFiles.map(file => join(this.commandsDir_, file)));
      return JSON.parse(commandContents) as Array<{ command: string, args: unknown[] }>;
    } else {
      return null;
    }
  }

  dispose() {
    if (this.watchInterval_) {
      log.appendLine("Stopping watching for commands");
      clearTimeout(this.watchInterval_);
    }
  }

  private commandsDir_: string;
  private watchInterval_: NodeJS.Timeout;
}


function inspectCommandsDir(stateManager: WorkspaceStateManager): string {
  const commandsDir = userDataDir(join(kPythonPackageName, "vscode", stateManager.getWorkspaceInstance(), "commands"));

  if (!existsSync(commandsDir)) {
    mkdirSync(commandsDir, { recursive: true });
  }

  return commandsDir;
}