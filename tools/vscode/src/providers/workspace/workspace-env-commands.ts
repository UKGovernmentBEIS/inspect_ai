import { existsSync, writeFileSync } from "fs";
import { Command } from "../../core/command";
import { workspacePath } from "../../core/path";
import { window, workspace } from "vscode";


export function workspaceEnvCommands() {
  return [new EditEnvFileCommand()];
}

export class EditEnvFileCommand implements Command {
  constructor() { }
  async execute(): Promise<void> {

    // The path to the env file
    const absPath = workspacePath(`.env`);

    // Ensure env file actually exists
    if (!existsSync(absPath.path)) {
      writeFileSync(absPath.path,
        "",
        { encoding: "utf-8" }
      );
    }

    // Open the env file
    const document = await workspace.openTextDocument(absPath.path);
    await window.showTextDocument(document);

  }

  private static readonly id = "inspect.editEnvFile";
  public readonly id = EditEnvFileCommand.id;
}
