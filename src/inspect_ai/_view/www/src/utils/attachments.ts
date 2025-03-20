export const resolveAttachments = <T>(
  value: T,
  attachments: Record<string, string>,
): T => {
  const CONTENT_PROTOCOL = "tc://";
  const ATTACHMENT_PROTOCOL = "attachment://";

  // Handle null or undefined early
  if (value === null || value === undefined) {
    return value;
  }

  // Handle arrays recursively
  if (Array.isArray(value)) {
    let hasChanged = false;
    const resolvedArray = value.map((v) => {
      const resolved = resolveAttachments(v, attachments);
      if (resolved !== v) hasChanged = true;
      return resolved;
    });

    // Only return the new array if something actually changed
    return hasChanged ? (resolvedArray as unknown as T) : value;
  }

  // Handle objects recursively, but skip Date instances and other special object types
  if (
    typeof value === "object" &&
    !(value instanceof Date) &&
    !(value instanceof RegExp)
  ) {
    let hasChanged = false;
    const resolvedObject: Record<string, unknown> = {};

    for (const [key, val] of Object.entries(value)) {
      const resolved = resolveAttachments(val, attachments);
      resolvedObject[key] = resolved;

      // Track if anything changed
      if (resolved !== val) hasChanged = true;
    }

    // Only return the new object if something actually changed
    return hasChanged ? (resolvedObject as unknown as T) : value;
  }

  // Handle string values with protocol references
  if (typeof value === "string") {
    // Check if the string starts with the content protocol
    if (value.startsWith(CONTENT_PROTOCOL)) {
      const updatedValue = value.replace(CONTENT_PROTOCOL, ATTACHMENT_PROTOCOL);

      // Now check if it's an attachment reference
      if (updatedValue.startsWith(ATTACHMENT_PROTOCOL)) {
        const attachmentId = updatedValue.slice(ATTACHMENT_PROTOCOL.length);
        const attachment = attachments[attachmentId];

        // Return the attachment content if it exists, otherwise return the original string
        return (attachment !== undefined ? attachment : value) as unknown as T;
      }

      return updatedValue as unknown as T;
    }

    // Check if it's directly an attachment reference
    if (value.startsWith(ATTACHMENT_PROTOCOL)) {
      const attachmentId = value.slice(ATTACHMENT_PROTOCOL.length);
      const attachment = attachments[attachmentId];

      // Return the attachment content if it exists, otherwise return the original string
      return (attachment !== undefined ? attachment : value) as unknown as T;
    }
  }

  // Return unchanged for other types
  return value;
};
