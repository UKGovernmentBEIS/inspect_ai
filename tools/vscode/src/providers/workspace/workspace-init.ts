import { Command } from "../../core/command";
import { WorkspaceStateManager } from "./workspace-state-provider";
import { ensureGitignore } from "../../core/git";
import {
  activeWorkspacePath,
} from "../../core/path";


const kGitInitKey = "gitInit";

export async function initializeWorkspace(
  state: WorkspaceStateManager
): Promise<[Command[]]> {
  const hasInitializedGit = state.getState(kGitInitKey);
  if (hasInitializedGit !== "true" || 1 === 1) {
    const path = activeWorkspacePath();

    // If we're in a workspace, initialize
    ensureGitignore(path, ignorePaths());

    await state.setState(kGitInitKey, "true");

  }
  return [[]];
}

// TODO: Extract this for use adding additional paths (like if the modify env with logdir)

function ignorePaths() {
  const ignores: string[] = [".env", "logs/", "__pycache__/"];
  return ignores;
}
