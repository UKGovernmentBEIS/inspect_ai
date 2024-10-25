import { ExtensionContext, MessageItem, window } from "vscode";

import { CommandManager } from "./core/command";
import { activateCodeLens } from "./providers/codelens/codelens-provider";
import { activateLogview } from "./providers/logview/logview";
import { logviewTerminalLinkProvider } from "./providers/logview/logview-link-provider";
import { InspectSettingsManager } from "./providers/settings/inspect-settings";
import { initializeGlobalSettings } from "./providers/settings/user-settings";
import { activateEvalManager } from "./providers/inspect/inspect-eval";
import { activateActivityBar } from "./providers/activity-bar/activity-bar-provider";
import { activateActiveTaskProvider } from "./providers/active-task/active-task-provider";
import { activateWorkspaceTaskProvider } from "./providers/workspace/workspace-task-provider";
import {
  activateWorkspaceState,
} from "./providers/workspace/workspace-state-provider";
import { initializeWorkspace } from "./providers/workspace/workspace-init";
import { activateWorkspaceEnv } from "./providers/workspace/workspace-env-provider";
import { initPythonInterpreter } from "./core/python";
import { initInspectProps } from "./inspect";
import { activateInspectManager } from "./providers/inspect/inspect-manager";
import { checkActiveWorkspaceFolder } from "./core/workspace";
import { inspectBinPath, inspectVersionDescriptor } from "./inspect/props";
import { extensionHost } from "./hooks";
import { activateStatusBar } from "./providers/statusbar";
import { InspectViewServer } from "./providers/inspect/inspect-view-server";
import { InspectLogsWatcher } from "./providers/inspect/inspect-logs-watcher";
import { activateLogNotify } from "./providers/lognotify";
import { activateOpenLog } from "./providers/openlog";

const kInspectMinimumVersion = "0.3.8";

// This method is called when your extension is activated
// Your extension is activated the very first time the command is executed
export async function activate(context: ExtensionContext) {
  // we don't activate anything if there is no workspace
  if (!checkActiveWorkspaceFolder()) {
    return;
  }

  // Get the host
  const host = extensionHost();

  const commandManager = new CommandManager();

  // init python interpreter
  context.subscriptions.push(await initPythonInterpreter());

  // init inspect props
  context.subscriptions.push(initInspectProps());

  // Initialize global settings
  await initializeGlobalSettings();

  // Warn the user if they don't have a recent enough version
  void checkInspectVersion();

  // Activate the workspacestate manager
  const [stateCommands, stateManager] = activateWorkspaceState(context);

  // For now, create an output channel for env changes
  const workspaceActivationResult = activateWorkspaceEnv();
  const [envComands, workspaceEnvManager] = workspaceActivationResult;
  context.subscriptions.push(workspaceEnvManager);

  // Initial the workspace
  await initializeWorkspace(stateManager);

  // Inspect Manager watches for changes to inspect binary
  const inspectManager = activateInspectManager(context);
  context.subscriptions.push(inspectManager);

  // Eval Manager
  const [inspectEvalCommands, inspectEvalMgr] = await activateEvalManager(
    stateManager,
    context
  );

  // Activate a watcher which inspects the active document and determines
  // the active task (if any)
  const [taskCommands, activeTaskManager] = activateActiveTaskProvider(
    inspectEvalMgr,
    context
  );

  // Active the workspace manager to watch for tasks
  const workspaceTaskMgr = activateWorkspaceTaskProvider(
    inspectManager,
    context
  );

  // Read the extension configuration
  const settingsMgr = new InspectSettingsManager(() => { });

  // initialiaze view server
  const server = new InspectViewServer(context, inspectManager);

  // initialise logs watcher
  const logsWatcher = new InspectLogsWatcher(stateManager);

  // Activate the log view
  const [logViewCommands, logviewWebviewManager] = await activateLogview(
    inspectManager,
    server,
    workspaceEnvManager,
    logsWatcher,
    context,
    host
  );
  const inspectLogviewManager = logviewWebviewManager;

  // initilisze open log
  activateOpenLog(context, logviewWebviewManager);

  // Activate the Activity Bar
  const taskBarCommands = await activateActivityBar(
    inspectManager,
    inspectEvalMgr,
    inspectLogviewManager,
    activeTaskManager,
    workspaceTaskMgr,
    stateManager,
    workspaceEnvManager,
    server,
    logsWatcher,
    context
  );

  // Register the log view link provider
  window.registerTerminalLinkProvider(
    logviewTerminalLinkProvider()
  );

  // Activate Code Lens
  activateCodeLens(context);

  // Activate Status Bar
  activateStatusBar(context, inspectManager);

  // Activate Log Notification
  activateLogNotify(context, logsWatcher, settingsMgr, inspectLogviewManager);

  // Activate commands
  [
    ...logViewCommands,
    ...inspectEvalCommands,
    ...taskBarCommands,
    ...stateCommands,
    ...envComands,
    ...taskCommands,
  ].forEach((cmd) => commandManager.register(cmd));
  context.subscriptions.push(commandManager);

  // refresh the active task state
  await activeTaskManager.refresh();
}


const checkInspectVersion = async () => {
  if (inspectBinPath()) {
    const descriptor = inspectVersionDescriptor();
    if (descriptor && descriptor.version.compare(kInspectMinimumVersion) === -1) {
      const close: MessageItem = { title: "Close" };
      await window.showInformationMessage<MessageItem>(
        "The VS Code extension requires a newer version of Inspect. Please update " +
        "with pip install --upgrade inspect-ai",
        close
      );
    }
  }
};
