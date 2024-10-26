import { ExtensionContext, TextDocumentShowOptions, Uri, commands } from "vscode";
import { kInspectLogViewType } from "./logview/logview-editor";
import { hasMinimumInspectVersion } from "../inspect/version";
import { kInspectEvalLogFormatVersion } from "./inspect/inspect-constants";
import { InspectViewManager } from "./logview/logview-view";
import { withEditorAssociation } from "../core/vscode/association";


export function activateOpenLog(
  context: ExtensionContext,
  viewManager: InspectViewManager
) {

  context.subscriptions.push(commands.registerCommand('inspect.openLogViewer', async (uri: Uri) => {

    // function to open using defualt editor in preview mode
    const openLogViewer = async () => {
      await commands.executeCommand(
        'vscode.open',
        uri,
        <TextDocumentShowOptions>{ preview: true }
      );
    };

    if (hasMinimumInspectVersion(kInspectEvalLogFormatVersion)) {
      if (uri.path.endsWith(".eval")) {

        await openLogViewer();

      } else {

        await withEditorAssociation(
          {
            viewType: kInspectLogViewType,
            filenamePattern: "{[0-9][0-9][0-9][0-9]}-{[0-9][0-9]}-{[0-9][0-9]}T{[0-9][0-9]}[:-]{[0-9][0-9]}[:-]{[0-9][0-9]}*{[A-Za-z0-9]{21}}*.json"
          },
          openLogViewer
        );

      }

      // notify the logs pane that we are doing this so that it can take a reveal action
      await commands.executeCommand('inspect.logListingReveal', uri);
    } else {
      await viewManager.showLogFile(uri, "activate");
    }

  }));

}