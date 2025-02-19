export function printCircularReferences(obj: Record<string, unknown>): void {
  const seenObjects = new WeakMap<object, string>();

  function detect(value: unknown, path: string = ""): void {
    // Only proceed if value is an object (not null)
    if (value !== null && typeof value === "object") {
      // Check if we've seen this object before
      if (seenObjects.has(value as object)) {
        console.log(
          `Circular reference detected at path: ${seenObjects.get(value as object)}`,
        );
        return;
      }

      // Store the current path for this object
      seenObjects.set(value as object, path);

      // Recursively check all properties
      for (const key in value) {
        if (Object.prototype.hasOwnProperty.call(value, key)) {
          detect((value as Record<string, unknown>)[key], `${path}.${key}`);
        }
      }
    }
  }

  detect(obj, "root");
}
