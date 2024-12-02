import { existsSync } from "fs";
import { ExtensionContext, Uri, UriHandler, window, commands } from "vscode";
import { showError } from "../components/error";

export function activateProtocolHandler(context: ExtensionContext) {
  const protocolHandler = new InspectProtocolHandler();
  context.subscriptions.push(window.registerUriHandler(protocolHandler));
}

export class InspectProtocolHandler implements UriHandler {
  public async handleUri(uri: Uri): Promise<void> {
    // Read the command
    const command = uri.path.replace(/^\//, "");
    const queryParams = new URLSearchParams(uri.query);
    switch (command) {
      // The open command
      case "open": {
        // Get the log file
        const logFile = queryParams.get("log");
        if (logFile) {
          const logUri = Uri.parse(logFile);

          // For local file paths, make sure the file exists or show an error
          if (logUri.scheme === "file") {
            if (!existsSync(logUri.fsPath)) {
              await showError(`The file ${logUri.fsPath} does exist.`);
              return;
            }
          }

          // Execute the open command
          await commands.executeCommand('inspect.openLogViewer', logUri);
        }
      }
    }
  }
}
