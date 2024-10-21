import { inspectVersionDescriptor } from "./props";

export function withMinimumInspectVersion(version: string, hasVersion: () => void, doesntHaveVersion: () => void): void;
export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T;

export function withMinimumInspectVersion<T>(version: string, hasVersion: () => T, doesntHaveVersion: () => T): T | void {
  if (hasMinimumInspectVersion(version)) {
    return hasVersion();
  } else {
    return doesntHaveVersion();
  }
}

export function hasMinimumInspectVersion(version: string, strictDevCheck = false): boolean {
  const descriptor = inspectVersionDescriptor();
  if (descriptor && (descriptor.version.compare(version) >= 0 || (!strictDevCheck && descriptor.isDeveloperBuild))) {
    return true;
  } else {
    return false;
  }
}