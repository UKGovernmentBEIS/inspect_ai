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
