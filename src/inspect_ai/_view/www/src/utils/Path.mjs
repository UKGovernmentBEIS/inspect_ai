// @ts-check
/**
 * Extracts the filename without extension from a given path.
 *
 * @param {string} path - The full path of the file.
 * @returns {string} - The filename without its extension, or the original path if no extension is found.
 */
export const filename = (path) => {
  const pathparts = path.split("/");
  const basename = pathparts.slice(-1)[0];
  const match = basename.match(/(.*)\.\S+$/);
  if (match) {
    return match[1];
  } else {
    return path;
  }
};
