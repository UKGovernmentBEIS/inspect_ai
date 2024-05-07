import { workspace, WorkspaceFolder } from "vscode";

export function activeWorkspaceFolder(): WorkspaceFolder {
  const workspaceFolder = workspace.workspaceFolders![0];
  return workspaceFolder;
}


export function checkActiveWorkspaceFolder(): WorkspaceFolder | undefined {
  const workspaceFolder = workspace.workspaceFolders?.[0];
  return workspaceFolder;
}
