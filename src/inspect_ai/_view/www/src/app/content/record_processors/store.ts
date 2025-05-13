import { RecordProcessor } from "./types";

const kStoreInstanceKey = /^(.+)?:([a-zA-Z0-9]{22}):instance$/;
const kStoreKey = /^(.+)?:([a-zA-Z0-9]{22}):(.+)$/;

// Expands store keys in the record. When an instance key is found, this will create a new node, and subsequent store
// keys will be added as children to that node. Since instance keys always appear first, we can do this in a single pass.
export const resolveStoreKeys: RecordProcessor = (
  record: Record<string, unknown>,
): Record<string, unknown> => {
  const result: Record<string, unknown> = {};
  const storeInstances: Record<string, Record<string, unknown>> = {};
  const instanceKeys: Set<string> = new Set();

  const entries = Object.entries(record);
  for (let i = 0; i < entries.length; i++) {
    const [key, value] = entries[i];

    // First check if it's an instance key
    const instanceInfo = parseStoreInstanceKey(key, value);
    if (instanceInfo) {
      const { storeName, instanceId } = instanceInfo;
      const instanceKey = storeKey(storeName, instanceId);

      // Create a container for this instance if it doesn't exist
      if (!storeInstances[instanceKey]) {
        storeInstances[instanceKey] = {};
      }

      instanceKeys.add(key);
      continue;
    } else {
      // Then check if it's a store key that belongs to an instance
      const storeKeyInfo = parseStoreKey(key);
      if (storeKeyInfo) {
        const { storeName, instanceId, keyName } = storeKeyInfo;
        const instanceKey = storeKey(storeName, instanceId);

        // If we have a container for this instance, add this key as a child
        if (storeInstances[instanceKey]) {
          storeInstances[instanceKey][keyName] = value;
          continue;
        }
      } else {
        // If it's not a store key or instance key, add it directly to the result
        result[key] = value;
      }
    }
  }

  // Add all store instances to the result
  for (const [instanceKey, children] of Object.entries(storeInstances)) {
    // Recursively process the children to handle nested store keys
    result[instanceKey] = resolveStoreKeys(children);
  }

  // Process any nested objects recursively
  for (const [key, value] of Object.entries(result)) {
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      result[key] = resolveStoreKeys(value as Record<string, unknown>);
    }
  }

  return result;
};

// Parses the store instance key
const parseStoreInstanceKey = (key: string, value: unknown) => {
  const match = key.match(kStoreInstanceKey);
  if (match) {
    const [, storeName, instanceId] = match;
    if (typeof value === "string" && instanceId === value) {
      return {
        storeName,
        instanceId,
      };
    }
  }
  return null;
};

// Parses a store key
const parseStoreKey = (key: string) => {
  const match = key.match(kStoreKey);
  if (match) {
    const [, storeName, instanceId, keyName] = match;
    if (keyName !== "instance") {
      return {
        storeName,
        instanceId,
        keyName,
      };
    }
  }
  return null;
};

// Create a unique key for the store instance
const storeKey = (storeName: string, instanceId: string) => {
  return `${storeName || ""} (${instanceId})`;
};
