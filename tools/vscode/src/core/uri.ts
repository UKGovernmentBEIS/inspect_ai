import path from "path";
import * as os from "os";
import { Uri } from "vscode";


export function resolveToUri(pathOrUri: string): Uri {
  const uriPattern = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;
  if (uriPattern.test(pathOrUri)) {
    try {
      return Uri.parse(pathOrUri);
    } catch (error) {
      throw new Error(`Invalid URI format: ${pathOrUri}`);
    }
  } else {
    try {
      const absolutePath = path.isAbsolute(pathOrUri)
        ? pathOrUri
        : path.resolve(pathOrUri);
      return Uri.file(absolutePath);
    } catch (error) {
      throw new Error(`Invalid file path: ${pathOrUri}`);
    }
  }
}


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

export function prettyUriPath(uri: Uri): string {
  if (uri.scheme === 'file') {
    const path = uri.fsPath;
    return path.replace(os.homedir(), "~");
  } else {
    return uri.toString(true);
  }
}

/**
 * Gets the relative path from a parent Uri to a child Uri
 * Returns null if child is not contained within parent
 */
export function getRelativeUri(parentUri: Uri, childUri: Uri): string | null {

  if (parentUri.scheme !== childUri.scheme) {
    return null;
  }

  const childStr = childUri.toString(true);
  let parentStr = parentUri.toString(true);
  if (childStr === parentStr) {
    return null;
  } else if (!childStr.startsWith(parentStr)) {
    return null;
  } else {
    if (!parentStr.endsWith("/")) {
      parentStr = `${parentStr}/`;
    }
    return childStr.slice(parentStr.length);
  }
}

export function normalizeWindowsUri(uri: string) {
  if (os.platform() === "win32") {
    // Check if the URI is already correctly formatted
    const windowsFilePattern = /^file:\/\/\/[a-zA-Z]:\\/;
    if (windowsFilePattern.test(uri)) {
      return uri;
    }

    // If not, correct the URI to have the right number of slashes
    const malformedPattern = /^file:\/\/([a-zA-Z]):\//;
    const correctedUri = uri.replace(malformedPattern, 'file:///$1:/');

    return correctedUri;
  } else {
    return uri;
  }
}