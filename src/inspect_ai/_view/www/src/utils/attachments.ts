/**
 * Resolves individual value by replacing protocol references with attachment content
 */
export const resolveAttachments = (
  value: any,
  attachments: Record<string, string>,
): any => {
  const kContentProtocol = "tc://";
  const kAttachmentProtocol = "attachment://";

  // Handle arrays recursively
  if (Array.isArray(value)) {
    return value.map((v) => resolveAttachments(v, attachments));
  }

  // Handle objects recursively
  if (value && typeof value === "object") {
    const resolvedObject: Record<string, unknown> = {};
    for (const key of Object.keys(value)) {
      resolvedObject[key] = resolveAttachments(value[key], attachments);
    }
    return resolvedObject;
  }

  // Handle string values with protocol references
  if (typeof value === "string") {
    let resolvedValue = value;
    if (resolvedValue.startsWith(kContentProtocol)) {
      resolvedValue = resolvedValue.replace(
        kContentProtocol,
        kAttachmentProtocol,
      );
    }
    if (resolvedValue.startsWith(kAttachmentProtocol)) {
      return attachments[resolvedValue.replace(kAttachmentProtocol, "")];
    }
    return resolvedValue;
  }

  // Return unchanged for other types
  return value;
};
