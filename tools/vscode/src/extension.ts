import { ExtensionContext, MessageItem, window } from "vscode";

import { CommandManager } from "./core/command";
import { activateCodeLens } from "./providers/codelens/codelens-provider";
import { activateLogview } from "./providers/logview/logview";
import { LogViewFileWatcher } from "./providers/logview/logview-file-watcher";
import { logviewTerminalLinkProvider } from "./providers/logview/logview-link-provider";
import { InspectLogviewManager } from "./providers/logview/logview-manager";
import { InspectSettingsManager } from "./providers/settings/inspect-settings";
import { initializeGlobalSettings } from "./providers/settings/user-settings";
import { activateEvalManager } from "./providers/inspect/inspect-eval";
import { activateActivityBar } from "./providers/activity-bar/activity-bar-provider";
import { activateActiveTaskProvider } from "./providers/active-task/active-task-provider";
import { activateWorkspaceTaskProvider } from "./providers/workspace/workspace-task-provider";
import { WorkspaceStateManager, activateWorkspaceState } from "./providers/workspace/workspace-state-provider";
import { initializeWorkspace } from "./providers/workspace/workspace-init";
import { activateWorkspaceEnv } from "./providers/workspace/workspace-env-provider";
import { initPythonInterpreter } from "./core/python";
import { initInspectProps } from "./inspect";
import { activateInspectManager } from "./providers/inspect/inspect-manager";
import { checkActiveWorkspaceFolder } from "./core/workspace";
import { inspectBinPath, inspectVersion } from "./inspect/props";

const kInspectMinimumVersion = "0.3.8";

// This method is called when your extension is activated
// Your extension is activated the very first time the command is executed
export async function activate(context: ExtensionContext) {

  // we don't activate anything if there is no workspace
  if (!checkActiveWorkspaceFolder()) {
    return;
  }

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
  const [inspectEvalCommands, inspectEvalMgr] = await activateEvalManager(stateManager, context);

  // Activate a watcher which inspects the active document and determines
  // the active task (if any)
  const [taskCommands, activeTaskManager] = activateActiveTaskProvider(inspectEvalMgr, context);

  // Active the workspace manager to watch for tasks
  const workspaceTaskMgr = activateWorkspaceTaskProvider(inspectManager, context);

  // Read the extension configuration
  const settingsMgr = new InspectSettingsManager(() => {
    // If settings have changed, see if we need to stop or start the file watcher
    if (logFileWatcher && !settingsMgr.getSettings().logViewAuto) {
      stopLogWatcher();
    } else if (
      !logFileWatcher &&
      settingsMgr.getSettings().logViewAuto &&
      inspectLogviewManager
    ) {
      startLogWatcher(logviewWebviewManager, stateManager);
    }
  });

  // Activate the log view
  const [logViewCommands, logviewWebviewManager] = await activateLogview(
    inspectManager,
    settingsMgr,
    workspaceEnvManager,
    context
  );
  const inspectLogviewManager = logviewWebviewManager;

  // Activate the Activity Bar
  const taskBarCommands = await activateActivityBar(
    inspectManager,
    inspectEvalMgr,
    inspectLogviewManager,
    activeTaskManager,
    workspaceTaskMgr,
    stateManager,
    workspaceEnvManager,
    context
  );


  // Register the log view link provider
  window.registerTerminalLinkProvider(
    logviewTerminalLinkProvider(logviewWebviewManager)
  );

  // Activate the file watcher for this workspace
  if (settingsMgr.getSettings().logViewAuto) {
    startLogWatcher(logviewWebviewManager, stateManager);
  }

  // Activate Code Lens
  activateCodeLens(context);

  // Activate commands
  [
    ...logViewCommands,
    ...inspectEvalCommands,
    ...taskBarCommands,
    ...stateCommands,
    ...envComands,
    ...taskCommands
  ].forEach((cmd) => commandManager.register(cmd));
  context.subscriptions.push(commandManager);

  // refresh the active task state
  await activeTaskManager.refresh();
}

// This method is called when your extension is deactivated
export function deactivate() {
  stopLogWatcher();
}

// Log file watching
let logFileWatcher: LogViewFileWatcher | undefined;

const startLogWatcher = (
  logviewWebviewManager: InspectLogviewManager,
  workspaceStateManager: WorkspaceStateManager
) => {
  logFileWatcher = new LogViewFileWatcher(
    logviewWebviewManager,
    workspaceStateManager
  );
};

const stopLogWatcher = () => {
  if (logFileWatcher) {
    logFileWatcher.dispose();
    logFileWatcher = undefined;
  }
};

const checkInspectVersion = async () => {
  if (inspectBinPath()) {
    const version = inspectVersion();
    if (version && version.compare(kInspectMinimumVersion) === -1) {

      const close: MessageItem = { title: "Close" };
      await window.showInformationMessage<MessageItem>(
        "The VS Code extension requires a newer version of Inspect. Please update " +
        "with pip install --upgrade inspect-ai",
        close
      );
    }
  }
};