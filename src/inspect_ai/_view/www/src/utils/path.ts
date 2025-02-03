/**
 * Extracts the filename without extension from a given path.
 */
export const filename = (path: string): string => {
  const pathparts = path.split("/");
  const basename = pathparts.slice(-1)[0];
  const match = basename.match(/(.*)\.\S+$/);
  if (match) {
    return match[1];
  } else {
    return path;
  }
};

/**
 * Extracts the directory name from a given path.
 */
export const dirname = (path: string): string => {
  const pathparts = path.split("/");

  // If the path ends with a filename (or no slashes), remove the last part (filename)
  if (pathparts.length > 1) {
    pathparts.pop();
  }

  // Join the remaining parts to form the directory path
  return pathparts.join("/");
};
