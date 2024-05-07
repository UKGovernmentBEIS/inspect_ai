import { Uri } from "vscode";

import { InspectLogviewManager } from "./logview-manager";
import { workspacePath } from "../../core/path";
import { showError } from "../../components/error";
import { TerminalLink, TerminalLinkContext } from "vscode";

const kLogFilePattern = /^.*Log: (\S*?\.json)\s*/g;

interface LogViewTerminalLink extends TerminalLink {
  data: string;
}

export const logviewTerminalLinkProvider = (manager: InspectLogviewManager) => {
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
    handleTerminalLink: (link: LogViewTerminalLink) => {

      const logFile = /^[a-z0-9]+:\/\//.test(link.data) ? Uri.parse(link.data) : Uri.file(workspacePath(link.data).path);


      manager.showLogFile(logFile).catch(async (err: Error) => {
        await showError("Failed to preview log file - failed to start Inspect View", err);
      });
    },
  };
};
