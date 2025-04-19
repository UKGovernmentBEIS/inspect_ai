export const directoryRelativeUrl = (file: string, dir?: string): string => {
  if (!dir) {
    return encodeURIComponent(file);
  }

  // Normalize paths to ensure consistent directory separators
  const normalizedFile = file.replace(/\\/g, "/");
  const normalizedLogDir = dir.replace(/\\/g, "/");

  // Ensure log_dir ends with a trailing slash
  const dirWithSlash = normalizedLogDir.endsWith("/")
    ? normalizedLogDir
    : normalizedLogDir + "/";

  // Check if file is within the log directory
  if (normalizedFile.startsWith(dirWithSlash)) {
    // Get the relative path
    const relativePath = normalizedFile.substring(dirWithSlash.length);

    // Split the path into segments and encode each segment
    const segments = relativePath.split("/");
    const encodedSegments = segments.map((segment) =>
      encodeURIComponent(segment),
    );

    // Join the encoded segments back together
    return encodedSegments.join("/");
  }

  // If path can't be made relative, return undefined
  return encodeURIComponent(file);
};
