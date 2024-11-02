// Function that uses the dom to download the contents provided in filecontents
export async function download_file(filename, filecontents) {
  const blob = new Blob([filecontents], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
