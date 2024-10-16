import { ExtensionContext } from "vscode";

import { Command } from "../../core/command";
import { logviewCommands } from "./commands";
import { InspectViewWebviewManager } from "./logview-view";
import { InspectViewManager } from "./logview-view";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { InspectManager } from "../inspect/inspect-manager";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { ExtensionHost } from "../../hooks";
import { InspectViewServer } from "../inspect/inspect-view-server";
import { activateLogviewEditor } from "./logview-editor";

export async function activateLogview(
  inspectManager: InspectManager,
  settingsMgr: InspectSettingsManager,
  envMgr: WorkspaceEnvManager,
  context: ExtensionContext,
  host: ExtensionHost
): Promise<[Command[], InspectViewManager]> {

  // initialiaze view server
  const server = new InspectViewServer(context, inspectManager);

  // activate the log viewer editor
  activateLogviewEditor(context, settingsMgr, server);

  // initilize manager
  const logviewWebManager = new InspectViewWebviewManager(
    inspectManager,
    server,
    context,
    host
  );
  const logviewManager = new InspectViewManager(
    logviewWebManager,
    settingsMgr,
    envMgr
  );

  // logview commands
  return [await logviewCommands(logviewManager), logviewManager];
}
