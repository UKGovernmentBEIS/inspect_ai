export function printCircularReferences(obj) {
  const seenObjects = new WeakMap();

  function detect(value, path = "") {
    if (typeof value === "object" && value !== null) {
      if (seenObjects.has(value)) {
        console.log(
          `Circular reference detected at path: ${seenObjects.get(value)}`,
        );
        return;
      }
      seenObjects.set(value, path);

      for (const key in value) {
        if (Object.prototype.hasOwnProperty.call(value, key)) {
          detect(value[key], `${path}.${key}`);
        }
      }
    }
  }

  detect(obj, "root");
}
