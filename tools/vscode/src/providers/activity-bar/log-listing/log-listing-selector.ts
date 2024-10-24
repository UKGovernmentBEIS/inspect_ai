import { QuickPickItem, QuickPickItemKind, ThemeIcon, Uri, window } from "vscode";
import { prettyUriPath } from "../../../core/uri";


const kSeparator = "<separator>";
const kWorkspaceLogDirectory = "<workspace-log-dir>";
const kSelectLocalDirectory = "<select-local>";
const kSelectRemoteURL = "<select-remote-url>";
const kClearRecentLocations = "<clear-recent>";

export interface SelectLocationQuickPickItem extends QuickPickItem {
  location: string
}

export async function selectLogListingLocation(workspaceLogDir: Uri): Promise<Uri | undefined> {

  return new Promise<Uri | undefined>((resolve) => {

    // build list of items
    const items: SelectLocationQuickPickItem[] = [];
    items.push({
      iconPath: new ThemeIcon("code-oss"),
      label: "Workspace Log Directory",
      detail: prettyUriPath(workspaceLogDir),
      location: kWorkspaceLogDirectory
    });
    items.push({
      label: "Select a location",
      kind: QuickPickItemKind.Separator,
      location: kSeparator
    });
    items.push({
      iconPath: new ThemeIcon("vm"),
      label: "Local Log Directory...",
      detail: "View logs in folders on your local machine",
      location: kSelectLocalDirectory
    });
    items.push({
      iconPath: new ThemeIcon("remote-explorer"),
      label: "Remote Log Directory...",
      detail: "View logs in remote storage locations (e.g. S3)",
      location: kSelectRemoteURL
    });
    items.push({
      label: "Recent locations",
      kind: QuickPickItemKind.Separator,
      location: kSeparator
    });
    items.push({
      label: "Clear recent locations",
      location: kClearRecentLocations
    });

    // setup and show quick pick
    const quickPick = window.createQuickPick<SelectLocationQuickPickItem>();
    quickPick.canSelectMany = false;
    quickPick.items = items;
    let accepted = false;
    quickPick.onDidAccept(() => {
      accepted = true;
      quickPick.hide();
      resolve(undefined);

    });
    quickPick.onDidHide(() => {
      if (!accepted) {
        resolve(undefined);
      }
    });
    quickPick.show();
  });

}