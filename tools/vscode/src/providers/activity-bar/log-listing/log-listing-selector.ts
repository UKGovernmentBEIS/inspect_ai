import { QuickPickItem, QuickPickItemKind, ThemeIcon, Uri, window } from "vscode";
import { prettyUriPath } from "../../../core/uri";
import { activeWorkspaceFolder } from "../../../core/workspace";


const kSeparator = "<separator>";
const kWorkspaceLogDirectory = "<workspace-log-dir>";
const kSelectLocalDirectory = "<select-local>";
const kSelectRemoteURL = "<select-remote-url>";
const kClearRecentLocations = "<clear-recent>";

export interface SelectLocationQuickPickItem extends QuickPickItem {
  location: string
}

export async function selectLogListingLocation(workspaceLogDir: Uri): Promise<Uri | null | undefined> {

  return new Promise<Uri | null | undefined>((resolve) => {

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
    quickPick.onDidAccept(async () => {
      // accept and hide quickpick
      accepted = true;
      quickPick.hide();

      // process selection
      const location = quickPick.selectedItems[0].location;
      if (location === kWorkspaceLogDirectory) {
        resolve(null);
      } else if (location === kSelectLocalDirectory) {
        resolve(await selectLocalDirectory());
      } else if (location === kSelectRemoteURL) {
        resolve(await selectRemoteURL());
      }


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


export async function selectLocalDirectory(): Promise<Uri | undefined> {
  const selection = await window.showOpenDialog({
    title: `Local Log Directory`,
    openLabel: `Select Directory`,
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: activeWorkspaceFolder().uri
  });
  if (selection) {
    return selection[0];
  } else {
    return undefined;
  }
}

export async function selectRemoteURL(): Promise<Uri | undefined> {
  const remoteUrl = await window.showInputBox({
    title: "Remote Log Directory",
    prompt: "Provide a remote log directory (e.g. s3://my-bucket/logs)",
    validateInput: (value) => {
      // don't try to validate empty string
      if (value.length === 0) {
        return null;
      }

      // check for parseable uri
      try {
        Uri.parse(value, true);
        return null;
      } catch (e) {
        return "Specified locatoin is not a valid URI (e.g. s3://my-bucket/logs)";
      }
    }
  });
  if (remoteUrl) {
    return Uri.parse(remoteUrl, true);
  } else {
    return undefined;
  }
}