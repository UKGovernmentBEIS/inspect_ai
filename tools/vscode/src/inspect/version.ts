import { inspectVersionDescriptor } from "./props";

export function withMinimumInspectVersion(version: string, hasVersion: () => void, doesntHaveVersion: () => void): void;
export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T;

export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T | void {
  const descriptor = inspectVersionDescriptor();
  if (descriptor && (descriptor.version.compare(version) >= 0 || descriptor.isDeveloperBuild)) {
    return hasVersion();
  } else {
    return doesntHaveVersion();
  }
}

