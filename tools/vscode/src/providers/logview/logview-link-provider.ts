import { commands, MessageItem, Uri, window, workspace } from "vscode";

import { workspacePath } from "../../core/path";
import { TerminalLink, TerminalLinkContext } from "vscode";
import { existsSync } from "fs";
import { basename } from "path";

const kLogFilePattern = /^.*Log: (\S*?\.json)\s*/g;

interface LogViewTerminalLink extends TerminalLink {
  data: string;
}

export const logviewTerminalLinkProvider = () => {
  return {
    provideTerminalLinks: (
      context: TerminalLinkContext,
    ) => {
      // Find the log file result, if present
      const matches = [...context.line.matchAll(kLogFilePattern)];
      if (matches.length === 0) {
        return [];
      }

      // Forward matches
      const result = matches.map((match) => {
        // The path from the terminal.
        const path = match[1];

        // Sort out the decoration range for the link
        const line = context.line;
        const startIndex = line.indexOf(path);
        return {
          startIndex,
          length: path.length,
          tooltip: "View Log",
          data: path,
        } as LogViewTerminalLink;
      });
      return result;
    },
    handleTerminalLink: async (link: LogViewTerminalLink) => {

      // Resolve the clicked link into a complete Uri to the file
      const logUri = await resolveLogFile(link.data);
      if (logUri) {

        await commands.executeCommand("inspect.openLogViewer", logUri);

      } else {
        // Since we couldn't resolve the log file, just let the user know
        const close: MessageItem = { title: "Close" };
        await window.showInformationMessage<MessageItem>(
          "Unable to find this log file within the current workspace.",
          close
        );
      }
    },
  };
};

const resolveLogFile = async (link: string) => {
  if (/^[a-z0-9]+:\/\//.test(link)) {
    // This is a Uri - just parse it and return
    // (e.g. S3 url)
    return Uri.parse(link);
  } else {
    // This is likely a file path. 
    const wsAbs = workspacePath(link);
    if (existsSync(wsAbs.path)) {
      // This is a workspace file that exists
      return Uri.file(wsAbs.path);
    } else {
      // This is a path to a file which I can't find
      // in the workspace as an absolute path, try searching for
      // the file itself in any folder.
      const filename = basename(link);
      const files = await workspace.findFiles(`**/${filename}`);
      if (files.length === 1) {
        return Uri.file(files[0].path);
      } else {
        return undefined;
      }
    }
  }
};