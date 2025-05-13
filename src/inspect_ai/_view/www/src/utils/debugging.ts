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

export function findDifferences(
  obj1: unknown,
  obj2: unknown,
  path = "",
): string[] {
  // Helper to build a readable path string
  const makePath = (parent: string, key: string | number, isIndex = false) =>
    parent
      ? isIndex
        ? `${parent}[${key}]`
        : `${parent}.${key}`
      : isIndex
        ? `[${key}]`
        : `${key}`;

  // Primitive / simple equality check (Object.is handles NaN)
  if (Object.is(obj1, obj2)) return [];

  // Primitives or null → direct difference
  if (
    obj1 === null ||
    obj2 === null ||
    typeof obj1 !== "object" ||
    typeof obj2 !== "object"
  ) {
    return [
      `${path || "<root>"}: ${JSON.stringify(obj1)} → ${JSON.stringify(obj2)}`,
    ];
  }

  // --- Arrays --------------------------------------------------------------
  const isArr1 = Array.isArray(obj1);
  const isArr2 = Array.isArray(obj2);
  if (isArr1 || isArr2) {
    if (isArr1 !== isArr2) {
      return [`${path || "<root>"}: one is an array, the other is not`];
    }

    const diff: string[] = [];
    const maxLen = Math.max(
      (obj1 as unknown[]).length,
      (obj2 as unknown[]).length,
    );

    if ((obj1 as unknown[]).length !== (obj2 as unknown[]).length) {
      diff.push(
        `${path || "<root>"}: array length ${
          (obj1 as unknown[]).length
        } vs ${(obj2 as unknown[]).length}`,
      );
    }

    for (let i = 0; i < maxLen; i++) {
      diff.push(
        ...findDifferences(
          (obj1 as unknown[])[i],
          (obj2 as unknown[])[i],
          makePath(path, i, true),
        ),
      );
    }
    return diff;
  }

  // --- Plain objects -------------------------------------------------------
  const allKeys = new Set([
    ...Object.keys(obj1 as Record<string, unknown>),
    ...Object.keys(obj2 as Record<string, unknown>),
  ]);

  const diff: string[] = [];

  for (const key of allKeys) {
    const has1 = Object.prototype.hasOwnProperty.call(obj1, key);
    const has2 = Object.prototype.hasOwnProperty.call(obj2, key);
    const newPath = makePath(path, key);

    if (!has1) {
      diff.push(`${newPath}: property missing in first object`);
    } else if (!has2) {
      diff.push(`${newPath}: property missing in second object`);
    } else {
      diff.push(
        ...findDifferences(
          (obj1 as Record<string, unknown>)[key],
          (obj2 as Record<string, unknown>)[key],
          newPath,
        ),
      );
    }
  }

  return diff;
}
