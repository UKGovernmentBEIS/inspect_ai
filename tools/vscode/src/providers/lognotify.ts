import { window, ExtensionContext, MessageItem, commands } from "vscode";
import { InspectLogsWatcher } from "./inspect/inspect-logs-watcher";
import { InspectSettingsManager } from "./settings/inspect-settings";
import { InspectViewManager } from "./logview/logview-view";


export function activateLogNotify(
  context: ExtensionContext,
  logsWatcher: InspectLogsWatcher,
  settingsMgr: InspectSettingsManager,
  viewManager: InspectViewManager
) {

  context.subscriptions.push(logsWatcher.onInspectLogCreated(async e => {

    if (e.externalWorkspace) {
      return;
    }

    if (!settingsMgr.getSettings().notifyEvalComplete) {
      return;
    }

    if (viewManager.logFileWillVisiblyUpdate(e.log)) {
      return false;
    }

    // see if we can pick out the task name
    const logFile = e.log.path.split("/").pop()!;
    const parts = logFile?.split("_");
    const task = parts.length > 1 ? parts[1] : "task";

    // show the message
    const viewLog: MessageItem = { title: "View Log" };
    const dontShowAgain: MessageItem = { title: "Don't Show Again" };
    const result = await window.showInformationMessage(
      `Eval complete: ${task}`,
      viewLog,
      dontShowAgain,
    );
    if (result === viewLog) {
      // open the editor
      await commands.executeCommand('inspect.openLogViewer', e.log);

    } else if (result === dontShowAgain) {
      settingsMgr.setNotifyEvalComplete(false);
    }


  }));


}