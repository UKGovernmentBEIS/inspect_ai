/**
 * Downloads the provided content as a file using the browser's DOM API
 */
export async function download_file(
  filename: string,
  filecontents: string | Blob | ArrayBuffer | ArrayBufferView,
): Promise<void> {
  const blob = new Blob([filecontents], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Encodes the path segments of a URL or relative path to ensure special characters
 * (like `+`, spaces, etc.) are properly encoded without affecting legal characters like `/`.
 *
 * This function will encode file names and path portions of both absolute URLs and
 * relative paths. It ensures that components of a full URL, such as the protocol and
 * query parameters, remain intact, while only encoding the path.
 */
export function encodePathParts(url: string): string {
  if (!url) return url; // Handle empty strings

  try {
    // Parse a full Uri
    const fullUrl = new URL(url);
    fullUrl.pathname = fullUrl.pathname
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
    return fullUrl.toString();
  } catch {
    // This is a relative path that isn't parseable as Uri
    return url
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
  }
}
