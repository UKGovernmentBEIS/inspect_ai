import { ExtensionContext } from "vscode";
import { Command } from "../../core/command";

export function activateWorkspaceState(
  context: ExtensionContext
): [Command[], WorkspaceStateManager] {
  const stateManager = new WorkspaceStateManager(context);
  return [[], stateManager];
}

export interface DocumentState {
  limit?: string;
  epochs?: string;
  temperature?: string;
  topP?: string;
  topK?: string;
  maxTokens?: string;
  params?: Record<string, string>;
}

export class WorkspaceStateManager {
  constructor(private readonly context_: ExtensionContext) {
  }

  public getState(key: string) {
    return this.context_.workspaceState.get(key);
  }

  public async setState(key: string, value: string) {
    await this.context_.workspaceState.update(key, value);
  }

  public getTaskState(taskFilePath: string, taskName?: string): DocumentState {
    return this.context_.workspaceState.get(taskKey(taskFilePath, taskName)) || {};
  }

  public async setTaskState(taskFilePath: string, state: DocumentState, taskName?: string) {
    await this.context_.workspaceState.update(taskKey(taskFilePath, taskName), state);
  }
}

function taskKey(file: string, task?: string) {
  if (task) {
    return `${file}@${task}`;
  } else {
    return `${file}`;
  }
}

