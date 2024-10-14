import { ExtensionContext } from "vscode";

import { Command } from "../../core/command";
import { logviewCommands } from "./commands";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectLogviewManager } from "./logview-manager";
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
): Promise<[Command[], InspectLogviewManager]> {

  // initialiaze view server
  const inspectViewServer = new InspectViewServer();

  // activate the log viewer editor
  activateLogviewEditor(context);

  // initilize manager
  const logviewWebManager = new InspectLogviewWebviewManager(
    inspectManager,
    inspectViewServer,
    context,
    host
  );
  const logviewManager = new InspectLogviewManager(
    logviewWebManager,
    settingsMgr,
    envMgr
  );

  // logview commands
  return [await logviewCommands(logviewManager), logviewManager];
}
