import { existsSync } from "fs";
import { Uri, window } from "vscode";
import { pathExists, workspacePath } from "../../core/path";
import { isAbsolute } from "path";





export async function selectFileUri(): Promise<Uri | undefined> {
  const uriOrPath = await window.showInputBox({
    title: "Select Log File",
    prompt: "Provide a path to a log file",
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
        // This isn't a file URI so see if it is a valid file path
        const path = value;
        if (isAbsolute(path) && existsSync(path)) {
          return null;
        } else if (pathExists(path)) {
          return null
        }
        return "Specified location is not a valid URI (e.g. s3://my-bucket/logs)";
      }
    }
  });
  if (uriOrPath) {
    try {
      return Uri.parse(uriOrPath, true);
    } catch (e) {
      if (isAbsolute(uriOrPath) && existsSync(uriOrPath)) {
        return Uri.file(uriOrPath);
      } else if (pathExists(uriOrPath)) {
        return Uri.file(workspacePath(uriOrPath).path);
      }
    }
  } else {
    return undefined;
  }
}