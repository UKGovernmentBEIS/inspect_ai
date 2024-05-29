import { inspectVersion } from "./props";


export const withMinimumInspectVersion = (version: string, hasVersion: () => void, doesntHaveVersion: () => void) => {
  const activeVersion = inspectVersion();
  if (activeVersion && activeVersion.compare(version) >= 0) {
    hasVersion();
  } else {
    doesntHaveVersion();
  }
};