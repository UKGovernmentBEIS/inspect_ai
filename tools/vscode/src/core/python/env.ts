import * as fs from "fs";
import * as os from "os";
import { existsSync } from "node:fs";
import path, { join } from "path";
import { AbsolutePath, toAbsolutePath } from "../path";


export function findEnvPythonPath(startDir: AbsolutePath, baseDir: AbsolutePath): AbsolutePath | null {
  let currentDir = startDir;
  while (currentDir.path !== baseDir.path) {

    // Look for a pythong environment
    const pythonPath = findEnvPython(currentDir);
    if (pythonPath) {
      return toAbsolutePath(pythonPath);
    }

    // Move to the parent directory
    currentDir = currentDir.dirname();
  }

  // No Python environment found
  return null;
}

// Helper function to search for Python environment in a given directory
function findEnvPython(directory: AbsolutePath): string | null {
  const items = fs.readdirSync(directory.path);

  // Filter only directories and check if any is an environment directory
  const envDir = items
    .map((item) => path.join(directory.path, item))
    .filter((filePath) => fs.statSync(filePath).isDirectory())
    .find(isEnvDir);

  if (envDir) {
    return getPythonPath(envDir);
  }

  return null;
}

function getPythonPath(dir: string): string | null {
  const pythonSuffixes = os.platform() === "win32" ? ["Scripts/python.exe", "python.exe"] : ["bin/python3", "bin/python"];
  for (const suffix of pythonSuffixes) {
    const fullPath = path.join(dir, suffix);
    if (fs.existsSync(fullPath)) {
      return fullPath;
    }
  }

  return null;
}

function isEnvDir(dir: string) {
  return existsSync(join(dir, "pyvenv.cfg")) ||
    existsSync(join(dir, "conda-meta"));
}
