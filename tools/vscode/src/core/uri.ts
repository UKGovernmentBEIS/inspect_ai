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

export function isPathContained(parentUri: Uri, childUri: Uri): boolean {
  if (parentUri.scheme !== childUri.scheme) {
    return false;
  }

  return childUri.fsPath === parentUri.fsPath ||
    childUri.fsPath.startsWith(parentUri.fsPath + path.sep);
}

/**
 * Gets the relative path from a parent Uri to a child Uri
 * Returns null if child is not contained within parent
 */
export function getRelativePath(parentUri: Uri, childUri: Uri): string | null {
  if (!isPathContained(parentUri, childUri)) {
    return null;
  }

  if (childUri.fsPath === parentUri.fsPath) {
    return '';
  }

  return childUri.fsPath.slice(parentUri.fsPath.length + 1);
}