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
import { activateWorkspaceState } from "./providers/workspace/workspace-state-provider";
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
import { activateProtocolHandler } from "./providers/protocol-handler";
import { activateInspectCommands } from "./providers/inspect/inspect-commands";
import { end, start } from "./core/log";

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
  start("Identifying Python");
  context.subscriptions.push(await initPythonInterpreter());
  end("Identifying Python");

  // init inspect props
  context.subscriptions.push(initInspectProps());

  // Initialize global settings
  await initializeGlobalSettings();

  // Warn the user if they don't have a recent enough version
  start("Check Inspect");
  void checkInspectVersion();
  end("Check Inspect");

  // Activate the workspacestate manager
  start("Activate Workspace");
  const [stateCommands, stateManager] = activateWorkspaceState(context);
  end("Activate Workspace");

  // For now, create an output channel for env changes
  start("Monitor Workspace Env");
  const workspaceActivationResult = activateWorkspaceEnv();
  const [envComands, workspaceEnvManager] = workspaceActivationResult;
  context.subscriptions.push(workspaceEnvManager);
  end("Monitor Workspace Env");

  // Initialize the protocol handler
  activateProtocolHandler(context);

  // Inspect Manager watches for changes to inspect binary
  start("Monitor Inspect Binary");
  const inspectManager = activateInspectManager(context);
  context.subscriptions.push(inspectManager);
  end("Monitor Inspect Binary");

  // Eval Manager
  start("Setup Eval Command");
  const [inspectEvalCommands, inspectEvalMgr] = await activateEvalManager(
    stateManager,
    context,
  );

  // Activate commands interface
  activateInspectCommands(stateManager, context);
  end("Setup Eval Command");

  // Activate a watcher which inspects the active document and determines
  // the active task (if any)
  start("Monitor Tasks");
  const [taskCommands, activeTaskManager] = activateActiveTaskProvider(
    inspectEvalMgr,
    context,
  );

  // Active the workspace manager to watch for tasks
  const workspaceTaskMgr = activateWorkspaceTaskProvider(
    inspectManager,
    context,
  );
  end("Monitor Tasks");

  // Read the extension configuration
  const settingsMgr = new InspectSettingsManager(() => {});

  // initialiaze view server
  start("Setup View Server");
  const server = new InspectViewServer(context, inspectManager);
  context.subscriptions.push(server);
  end("Setup View Server");

  // initialise logs watcher
  start("Setup Log Watcher");
  const logsWatcher = new InspectLogsWatcher(stateManager);
  end("Setup Log Watcher");

  // Activate the log view
  start("Setup Log Viewer");
  const [logViewCommands, logviewWebviewManager] = await activateLogview(
    inspectManager,
    server,
    workspaceEnvManager,
    logsWatcher,
    context,
    host,
  );
  const inspectLogviewManager = logviewWebviewManager;

  // initilisze open log
  activateOpenLog(context, logviewWebviewManager);
  end("Setup Log Viewer");

  // Activate the Activity Bar
  start("Setup Activity Bar");
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
    context,
  );
  end("Setup Activity Bar");

  start("Final Setup");
  // Register the log view link provider
  window.registerTerminalLinkProvider(logviewTerminalLinkProvider());

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

  end("Final Setup");

  // refresh the active task state
  start("Refresh Tasks");
  await activeTaskManager.refresh();
  end("Refresh Tasks");
}

const checkInspectVersion = async () => {
  if (inspectBinPath()) {
    const descriptor = inspectVersionDescriptor();
    if (
      descriptor &&
      descriptor.version.compare(kInspectMinimumVersion) === -1
    ) {
      const close: MessageItem = { title: "Close" };
      await window.showInformationMessage<MessageItem>(
        "The VS Code extension requires a newer version of Inspect. Please update " +
          "with pip install --upgrade inspect-ai",
        close,
      );
    }
  }
};
