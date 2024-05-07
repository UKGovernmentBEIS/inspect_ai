import { ExtensionContext } from "vscode";

import { Command } from "../../core/command";
import { logviewCommands } from "./commands";
import { InspectLogviewWebviewManager } from "./logview-webview";
import { InspectLogviewManager } from "./logview-manager";
import { InspectSettingsManager } from "../settings/inspect-settings";
import { InspectManager } from "../inspect/inspect-manager";

export function activateLogview(
  inspectManager: InspectManager,
  settingsMgr: InspectSettingsManager,
  context: ExtensionContext
): [Command[], InspectLogviewManager] {

  // initilize manager
  const logviewWebManager = new InspectLogviewWebviewManager(inspectManager, context);
  const logviewManager = new InspectLogviewManager(logviewWebManager, settingsMgr);

  // logview commands
  return [logviewCommands(logviewManager), logviewManager];
}
