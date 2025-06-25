/**
 * Extracts the filename without extension from a given path.
 */
export const filename = (path: string): string => {
  if (!path) {
    return "";
  }
  path = path.endsWith("/") ? path.slice(0, -1) : path;

  const pathparts = path.split("/");
  const basename = pathparts.slice(-1)[0];

  // Special case for .hidden files
  if (basename.startsWith(".") && !basename.substring(1).includes(".")) {
    return basename;
  }

  const match = basename.match(/(.*)\.\S+$/);
  if (match) {
    return match[1];
  } else {
    return path;
  }
};

export const basename = (path: string): string => {
  if (!path) {
    return "";
  }
  path = path.endsWith("/") ? path.slice(0, -1) : path;
  const pathparts = path.split("/");
  return pathparts.slice(-1)[0];
};

/**
 * Extracts the directory name from a given path.
 */
export const dirname = (path: string): string => {
  path = path.endsWith("/") ? path.slice(0, -1) : path;

  const pathparts = path.split("/");

  // If the path ends with a filename (or no slashes), remove the last part (filename)
  if (pathparts.length > 1) {
    pathparts.pop();
    // Join the remaining parts to form the directory path
    return pathparts.join("/");
  }

  // If no slashes, return empty string (no directory)
  return "";
};

/**
 * Tests whether the given path is in the specified directory.
 */
export const isInDirectory = (path: string, directory: string): boolean => {
  directory = directory.endsWith("/") ? directory.slice(0, -1) : directory;

  return dirname(path) === directory;
};

export const ensureTrailingSlash = (path?: string): string => {
  if (!path) {
    return "";
  }
  return path.endsWith("/") ? path : path + "/";
};
