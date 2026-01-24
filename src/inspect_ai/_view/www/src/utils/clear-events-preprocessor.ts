/**
 * JSON preprocessor that clears large events arrays at the byte level.
 * Works directly with Uint8Array to avoid creating gigabyte-sized strings.
 * Discards all events if the events array exceeds 100MB, leaving an empty array.
 */

const MAX_EVENTS_SIZE_BYTES = 350 * 1024 * 1024;
const MAX_TOTAL_SIZE = 512 * 1024 * 1024;

/**
 * Finds the "events": [ pattern in the byte array.
 * Returns the position of the opening bracket, or -1 if not found.
 */
function findEventsArrayStart(data: Uint8Array): number {
  // Pattern: "events" followed by optional whitespace, colon, optional whitespace, [
  const pattern = new TextEncoder().encode('"events"');

  for (let i = 0; i < data.length - pattern.length - 10; i++) {
    // Check if pattern matches
    let matches = true;
    for (let j = 0; j < pattern.length; j++) {
      if (data[i + j] !== pattern[j]) {
        matches = false;
        break;
      }
    }

    if (matches) {
      // Found "events", now look for : and [
      let pos = i + pattern.length;

      // Skip whitespace
      while (
        pos < data.length &&
        (data[pos] === 32 ||
          data[pos] === 9 ||
          data[pos] === 10 ||
          data[pos] === 13)
      ) {
        pos++;
      }

      // Check for :
      if (pos < data.length && data[pos] === 58) {
        // colon
        pos++;

        // Skip whitespace
        while (
          pos < data.length &&
          (data[pos] === 32 ||
            data[pos] === 9 ||
            data[pos] === 10 ||
            data[pos] === 13)
        ) {
          pos++;
        }

        // Check for [
        if (pos < data.length && data[pos] === 91) {
          // opening bracket
          return pos;
        }
      }
    }
  }

  return -1;
}

/**
 * Finds the closing bracket of an array starting at arrayStart.
 * Properly handles nested structures and strings.
 */
function findArrayEnd(data: Uint8Array, arrayStart: number): number {
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let i = arrayStart; i < data.length; i++) {
    const byte = data[i];

    if (escaped) {
      escaped = false;
      continue;
    }

    if (byte === 92) {
      // backslash
      escaped = true;
      continue;
    }

    if (byte === 34) {
      // quote
      inString = !inString;
      continue;
    }

    if (inString) {
      continue;
    }

    if (byte === 91 || byte === 123) {
      // [ or {
      depth++;
    } else if (byte === 93 || byte === 125) {
      // ] or }
      depth--;
      if (depth === 0 && byte === 93) {
        return i;
      }
    }
  }

  return -1;
}

/**
 * Clears events array at the byte level if it exceeds 100MB.
 * Replaces the entire events array with an empty array.
 * This allows handling gigabyte-sized files without running out of memory.
 */
export function clearLargeEventsArray(data: Uint8Array): Uint8Array {
  // Early exit: if the entire file is smaller than the limit, events can't exceed it
  if (data.length <= MAX_EVENTS_SIZE_BYTES) {
    return data;
  }

  const arrayStart = findEventsArrayStart(data);
  if (arrayStart === -1) {
    return data;
  }

  const arrayEnd = findArrayEnd(data, arrayStart);
  if (arrayEnd === -1) {
    return data;
  }

  const eventsSize = arrayEnd - arrayStart - 1; // -1 to exclude brackets
  if (eventsSize <= MAX_EVENTS_SIZE_BYTES && data.length <= MAX_TOTAL_SIZE) {
    return data;
  }

  // Build result with empty events array: []
  const before = data.slice(0, arrayStart + 1); // Up to and including [
  const after = data.slice(arrayEnd); // From ] onwards

  // Combine: before + ] + after (just close the bracket immediately)
  const result = new Uint8Array(before.length + after.length);

  let offset = 0;
  result.set(before, offset);
  offset += before.length;
  result.set(after, offset);

  return result;
}
