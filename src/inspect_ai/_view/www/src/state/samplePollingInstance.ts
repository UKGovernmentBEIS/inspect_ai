import { createSamplePolling } from "./samplePolling";
import { storeImplementation } from "./store";

let instance: ReturnType<typeof createSamplePolling> | null = null;

/**
 * Get the singleton sample polling instance.
 * Lazily creates the instance on first access.
 */
export function getSamplePolling() {
  if (!instance) {
    if (!storeImplementation) {
      throw new Error(
        "Store must be initialized before accessing samplePolling",
      );
    }
    instance = createSamplePolling(storeImplementation);
  }
  return instance;
}

/**
 * Cleanup the sample polling instance.
 * Should be called when the store is cleaned up.
 */
export function cleanupSamplePolling() {
  if (instance) {
    instance.cleanup();
    instance = null;
  }
}
