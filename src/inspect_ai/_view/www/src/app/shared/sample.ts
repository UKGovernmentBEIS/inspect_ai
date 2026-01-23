import type { SampleHandle } from "../types";

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

export const sampleHandlesEqual = (
  sample1?: SampleHandle,
  sample2?: SampleHandle,
): boolean => {
  if (!sample1 && !sample2) {
    return true;
  }

  if (!sample1 || !sample2) {
    return false;
  }

  return (
    sampleIdsEqual(sample1.id, sample2.id) &&
    sample1.epoch === sample2.epoch &&
    sample1.logFile === sample2.logFile
  );
};

export const createSampleHandle = (
  id: string | number,
  epoch: number,
  logFile: string,
): SampleHandle => {
  return { id, epoch, logFile };
};
