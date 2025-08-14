/**
 * Downloads the provided content as a file using the browser's DOM API
 */
export async function download_file(
  filename: string,
  filecontents: string | Blob | ArrayBuffer | ArrayBufferView,
): Promise<void> {
  let blob: Blob;

  if (typeof filecontents === "string" && filecontents.startsWith("data:")) {
    // Convert data URL to Blob
    const response = await fetch(filecontents);
    blob = await response.blob();
  } else {
    // Handle regular content
    blob = new Blob([filecontents], { type: "text/plain" });
  }

  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}
