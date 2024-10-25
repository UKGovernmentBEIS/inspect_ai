import { ExtensionContext } from "vscode";

import { Command } from "../../core/command";
import { logviewCommands } from "./commands";
import { InspectViewWebviewManager } from "./logview-view";
import { InspectViewManager } from "./logview-view";
import { InspectManager } from "../inspect/inspect-manager";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { ExtensionHost } from "../../hooks";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { activateLogviewEditor } from "./logview-editor";
import { InspectLogsWatcher } from "../inspect/inspect-logs-watcher";

export async function activateLogview(
  inspectManager: InspectManager,
  server: InspectViewServer,
  envMgr: WorkspaceEnvManager,
  logsWatcher: InspectLogsWatcher,
  context: ExtensionContext,
  host: ExtensionHost
): Promise<[Command[], InspectViewManager]> {

  // activate the log viewer editor
  activateLogviewEditor(context, server);

  // initilize manager
  const logviewWebManager = new InspectViewWebviewManager(
    inspectManager,
    server,
    context,
    host
  );
  const logviewManager = new InspectViewManager(
    context,
    logviewWebManager,
    envMgr,
    logsWatcher
  );

  // logview commands
  return [await logviewCommands(logviewManager), logviewManager];
}
