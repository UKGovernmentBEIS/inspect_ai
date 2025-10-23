export const sampleIdsEqual = (
  id?: string | number,
  otherId?: string | number,
) => {
  // Both undefined
  if (id === undefined && otherId === undefined) {
    return true;
  }

  // One undefined
  if (id === undefined || otherId === undefined) {
    return false;
  }

  // Treat both as strings for comparison
  return String(id) === String(otherId);
};
