import { ExtensionContext, window } from "vscode";
import { EnvConfigurationProvider } from "./env-config-provider";
import { activateTaskOutline } from "./task-outline-provider";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { ActiveTaskManager } from "../active-task/active-task-provider";
import { WorkspaceTaskManager } from "../workspace/workspace-task-provider";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { TaskConfigurationProvider } from "./task-config-provider";
import { InspectManager } from "../inspect/inspect-manager";
import { DebugConfigTaskCommand, RunConfigTaskCommand } from "./task-config-commands";
import { InspectLogviewManager } from "../logview/logview-manager";

export async function activateActivityBar(
  inspectManager: InspectManager,
  inspectEvalMgr: InspectEvalManager,
  inspectLogviewManager: InspectLogviewManager,
  activeTaskManager: ActiveTaskManager,
  workspaceTaskMgr: WorkspaceTaskManager,
  workspaceStateMgr: WorkspaceStateManager,
  workspaceEnvMgr: WorkspaceEnvManager,
  context: ExtensionContext
) {

  const [outlineCommands, treeDataProvider] = await activateTaskOutline(context, inspectEvalMgr, workspaceTaskMgr, activeTaskManager, inspectManager, inspectLogviewManager);
  context.subscriptions.push(treeDataProvider);

  const envProvider = new EnvConfigurationProvider(context.extensionUri, workspaceEnvMgr, workspaceStateMgr, inspectManager);
  context.subscriptions.push(
    window.registerWebviewViewProvider(EnvConfigurationProvider.viewType, envProvider)
  );

  const taskConfigProvider = new TaskConfigurationProvider(context.extensionUri, workspaceStateMgr, activeTaskManager, inspectManager);
  context.subscriptions.push(
    window.registerWebviewViewProvider(TaskConfigurationProvider.viewType, taskConfigProvider)
  );
  const taskConfigCommands = [
    new RunConfigTaskCommand(activeTaskManager, inspectEvalMgr),
    new DebugConfigTaskCommand(activeTaskManager, inspectEvalMgr),
  ];

  return [...outlineCommands, ...taskConfigCommands];
}

