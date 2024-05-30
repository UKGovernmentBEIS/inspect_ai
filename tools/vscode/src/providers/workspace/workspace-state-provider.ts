import { ExtensionContext } from "vscode";
import { Command } from "../../core/command";
import { randomInt } from "../../core/random";

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

export interface ModelState {
  lastModel?: string;
}

export class WorkspaceStateManager {
  constructor(private readonly context_: ExtensionContext) {
  }

  public async initializeWorkspaceId() {
    const existingKey = this.context_.workspaceState.get<string>('INSPECT_WORKSPACE_ID');
    if (!existingKey) {
      const key = `${Date.now()}-${randomInt(0, 100000)}`;
      await this.context_.workspaceState.update('INSPECT_WORKSPACE_ID', key);
    }
  }

  public getWorkspaceInstance(): string {
    return this.context_.workspaceState.get<string>('INSPECT_WORKSPACE_ID')!;
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

  public getModelState(provider: string): ModelState {
    return this.context_.workspaceState.get(modelKey(provider)) || {};
  }

  public async setModelState(provider: string, state: ModelState) {
    await this.context_.workspaceState.update(modelKey(provider), state);
  }
}

function taskKey(file: string, task?: string) {
  if (task) {
    return `${file}@${task}`;
  } else {
    return `${file}`;
  }
}

function modelKey(provider: string) {
  return `provider-${provider}`;
}

