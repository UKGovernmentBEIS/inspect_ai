import { ExtensionContext } from "vscode";

import { Command } from "../../core/command";
import { logviewCommands } from "./commands";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectLogviewManager } from "./logview-manager";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { InspectManager } from "../inspect/inspect-manager";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { ExtensionHost } from "../../hooks";

export async function activateLogview(
  inspectManager: InspectManager,
  settingsMgr: InspectSettingsManager,
  envMgr: WorkspaceEnvManager,
  context: ExtensionContext,
  host: ExtensionHost
): Promise<[Command[], InspectLogviewManager]> {
  // initilize manager
  const logviewWebManager = new InspectLogviewWebviewManager(
    inspectManager,
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
