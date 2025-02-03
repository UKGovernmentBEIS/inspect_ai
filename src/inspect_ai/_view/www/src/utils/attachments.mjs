/**
 * Resolves individual value
 *
 * @param {any} value - The value to resolve.
 * @param {Record<string,string>} attachments - The transcript events to display.
 * @returns {any} Value with resolved content.
 */
export const resolveAttachments = (value, attachments) => {
  const kContentProtocol = "tc://";
  const kAttachmentProtocol = "attachment://";

  if (Array.isArray(value)) {
    return value.map((v) => resolveAttachments(v, attachments));
  } else if (value && typeof value === "object") {
    /** @type {Record<string, unknown>} */
    const resolvedObject = {};
    for (const key of Object.keys(value)) {
      //@ts-ignore
      resolvedObject[key] = resolveAttachments(value[key], attachments);
    }
    return resolvedObject;
  } else if (typeof value === "string") {
    if (value.startsWith(kContentProtocol)) {
      value = value.replace(kContentProtocol, kAttachmentProtocol);
    }
    if (value.startsWith(kAttachmentProtocol)) {
      return attachments[value.replace(kAttachmentProtocol, "")];
    }
  }
  return value;
};
