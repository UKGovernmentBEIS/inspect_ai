import { Uri, window } from "vscode";
import { resolveLogFile } from "./logview-link-provider";

export async function selectFileUri(): Promise<Uri | undefined> {
  const uriOrPath = await window.showInputBox({
    title: "Select Log File",
    prompt: "Provide a path to a log file",
    validateInput: async (value) => {
      // don't try to validate empty string
      if (value.length === 0) {
        return null;
      }

      const logFile = await resolveLogFile(value);
      if (logFile) {
        return null;
      } else {
        return "Specified location is not a valid URI (e.g. s3://my-bucket/logs)";
      }
    },
  });
  if (uriOrPath) {
    return await resolveLogFile(uriOrPath);
  } else {
    return undefined;
  }
}
