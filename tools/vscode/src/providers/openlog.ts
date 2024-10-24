import { ExtensionContext, TextDocumentShowOptions, Uri, commands } from "vscode";
import { kInspectLogViewType } from "./logview/logview-editor";
import { hasMinimumInspectVersion } from "../inspect/version";
import { kInspectEvalLogFormatVersion } from "./inspect/inspect-constants";
import { InspectViewManager } from "./logview/logview-view";


export function activateOpenLog(
  context: ExtensionContext,
  viewManager: InspectViewManager
) {

  context.subscriptions.push(commands.registerCommand('inspect.openLogViewer', async (uri: Uri) => {

    if (hasMinimumInspectVersion(kInspectEvalLogFormatVersion)) {
      if (uri.path.endsWith(".eval")) {
        // normal default path for .eval files (so they get preview treatment)
        await commands.executeCommand(
          'vscode.open',
          uri,
          <TextDocumentShowOptions>{ preview: true }
        );
      } else {
        // force our custom editor for .json as we aren't the default. this has the issue of not 
        // using preview so proliferates more editors
        await commands.executeCommand(
          'vscode.openWith',
          uri,
          kInspectLogViewType,
          <TextDocumentShowOptions>{ preview: true }
        );
      }

      // notify the logs pane that we are doing this so that it can take a reveal action
      await commands.executeCommand('inspect.logListingReveal', uri);
    } else {
      await viewManager.showLogFile(uri, "activate");
    }

  }));

}