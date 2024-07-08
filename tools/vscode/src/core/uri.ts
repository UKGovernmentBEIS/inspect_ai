import path from "path";
import { Uri } from "vscode";

export function dirname(uri: Uri): Uri {
  if (uri.scheme === 'file') {
    // Handle file URIs
    const parentPath = path.dirname(uri.fsPath);
    return Uri.file(parentPath);
  } else {
    // Handle non-file URIs
    const parsedUrl = new URL(uri.toString());
    parsedUrl.pathname = path.dirname(parsedUrl.pathname);
    return Uri.parse(parsedUrl.toString());
  }
}