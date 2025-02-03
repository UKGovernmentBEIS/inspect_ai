import { ExtensionContext, Disposable, commands, workspace, RelativePattern, Uri, FileSystemWatcher } from "vscode";


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

    this.commandsWatcher_ = workspace.createFileSystemWatcher(
      new RelativePattern(Uri.file(this.commandsDir_), "*"),
      false,
      true,
      true
    );
    this.commandsWatcher_.onDidCreate(async () => {
      const commandsRequest = this.collectCommandsRequest();
      if (commandsRequest) {
        for (const command of commandsRequest) {
          log.appendLine(`Found command: ${command.command}`);
          log.appendLine(`Executing VS Code command ${command.command}`);
          try {
            await commands.executeCommand(command.command, ...command.args);
          } catch (error) {
            log.error(error instanceof Error ? error : String(error));
          }
        }
      }
    });
    log.appendLine(`Watching for commands`);
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
    if (this.commandsWatcher_) {
      log.appendLine("Stopping watching for commands");
      this.commandsWatcher_.dispose();
    }
  }

  private commandsDir_: string;
  private commandsWatcher_: FileSystemWatcher;
}


function inspectCommandsDir(stateManager: WorkspaceStateManager): string {
  const commandsDir = userDataDir(join(kPythonPackageName, "vscode", stateManager.getWorkspaceInstance(), "commands"));

  if (!existsSync(commandsDir)) {
    mkdirSync(commandsDir, { recursive: true });
  }

  return commandsDir;
}