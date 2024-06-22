import { inspectVersion } from "./props";

export function withMinimumInspectVersion(version: string, hasVersion: () => void, doesntHaveVersion: () => void): void;
export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T;

export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T | void {
  const activeVersion = inspectVersion();
  if (activeVersion && activeVersion.compare(version) >= 0) {
    return hasVersion();
  } else {
    return doesntHaveVersion();
  }
}

