// Version info loaded at runtime from version.json (emitted by vite plugin).
// This avoids baking volatile git-describe output into JS chunks, which would
// cascade hash changes across the entire build on every commit.

let cached: { version: string; commit: string } | null = null;

export const getVersionInfo = async (): Promise<{
  version: string;
  commit: string;
}> => {
  if (cached) return cached;
  try {
    const res = await fetch("version.json");
    cached = (await res.json()) as { version: string; commit: string };
  } catch {
    cached = { version: "unknown", commit: "unknown" };
  }
  return cached;
};
