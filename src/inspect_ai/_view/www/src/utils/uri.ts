export const directoryRelativeUrl = (file: string, dir?: string): string => {
  if (!dir) {
    return uriEncodePathSegments(file);
  }

  // Normalize paths to ensure consistent directory separators
  const normalizedFile = file.replace(/\\/g, "/");
  const normalizedLogDir = dir.replace(/\\/g, "/");

  // Ensure log_dir ends with a trailing slash
  const dirWithSlash = normalizedLogDir.endsWith("/")
    ? normalizedLogDir
    : normalizedLogDir + "/";

  // Check if file is within the log directory
  if (normalizedFile.startsWith(dirWithSlash)) {
    // Get the relative path
    const relativePath = normalizedFile.substring(dirWithSlash.length);

    // Split the path into segments and encode each segment
    const segments = relativePath.split("/");
    const encodedSegments = segments.map((segment) =>
      encodeURIComponent(segment),
    );

    // Join the encoded segments back together
    return encodedSegments.join("/");
  }

  return uriEncodePathSegments(normalizedFile);
};

const uriEncodePathSegments = (path: string): string => {
  // encode each path segment separately
  const segments = path.split("/");
  return segments.map((segment) => encodeURIComponent(segment)).join("/");
};

export const join = (file: string, dir?: string): string => {
  if (!dir) {
    return file;
  }

  // Normalize paths to ensure consistent directory separators
  const normalizedFile = file.replace(/\\/g, "/");
  const normalizedLogDir = dir.replace(/\\/g, "/");

  // Ensure log_dir ends with a trailing slash
  const dirWithSlash = normalizedLogDir.endsWith("/")
    ? normalizedLogDir
    : normalizedLogDir + "/";

  // If file already starts with the logDir, it's already an absolute path, don't join again
  if (normalizedFile.startsWith(dirWithSlash)) {
    return normalizedFile;
  }

  return dirWithSlash + normalizedFile;
};

/**
 * Encodes the path segments of a URL or relative path to ensure special characters
 * (like `+`, spaces, etc.) are properly encoded without affecting legal characters like `/`.
 *
 * This function will encode file names and path portions of both absolute URLs and
 * relative paths. It ensures that components of a full URL, such as the protocol and
 * query parameters, remain intact, while only encoding the path.
 */
export function encodePathParts(url: string): string {
  if (!url) return url; // Handle empty strings

  try {
    // Parse a full Uri
    const fullUrl = new URL(url);
    fullUrl.pathname = fullUrl.pathname
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
    return fullUrl.toString();
  } catch {
    // This is a relative path that isn't parseable as Uri
    return url
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
  }
}

/**
 * Tests whether a string is a valid URI.
 *
 * @param value - The string to test
 * @returns true if the string is a valid URI, false otherwise
 */
export const isUri = (value: string): boolean => {
  if (!value) return false;

  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
};

export const prettyDirUri = (uri: string) => {
  if (uri.startsWith("file://")) {
    return uri.replace("file://", "");
  } else {
    return uri;
  }
};
