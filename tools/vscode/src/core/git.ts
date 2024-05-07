import { existsSync, readFileSync, writeFileSync } from "fs";
import path from "path";
import { lines } from "./text";
import { runProcess } from "./process";
import { AbsolutePath } from "./path";
import { platform } from "os";

export function ensureGitignore(
  dir: AbsolutePath,
  entries: string[]
): boolean {
  // if .gitignore exists, then ensure it has the requisite entries
  const gitignorePath = path.join(dir.path, ".gitignore");
  if (existsSync(gitignorePath)) {
    const gitignore = lines(
      readFileSync(gitignorePath, {
        encoding: "utf-8",
      })
    ).map((line) => line.trim());
    const requiredEntries: string[] = [];
    for (const requiredEntry of entries) {
      if (!gitignore.includes(requiredEntry)) {
        requiredEntries.push(requiredEntry);
      }
    }
    if (requiredEntries.length > 0) {
      writeGitignore(dir.path, gitignore.concat(requiredEntries));
      return true;
    } else {
      return false;
    }
  } else {
    // if it doesn't exist then auto-create if we are in a git project or we had the force flag
    try {
      const result = runProcess("git", ["rev-parse"], dir);
      if (result) {
        createGitignore(dir.path, entries);
        return true;
      } else {
        return false;
      }
    } catch {
      return false;
    }
  }
}

export function createGitignore(dir: string, entries: string[]) {
  writeGitignore(dir, entries);
}

function writeGitignore(dir: string, lines: string[]) {
  const lineEnding = platform() === "win32" ? "\r\n" : "\n";
  writeFileSync(
    path.join(dir, ".gitignore"),
    lines.join(lineEnding) + lineEnding,
    { encoding: "utf-8" }
  );
}

