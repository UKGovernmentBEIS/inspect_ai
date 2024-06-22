import path, { basename, dirname, join } from "path";
import { activeWorkspaceFolder } from "./workspace";
import { existsSync } from "fs";

export type UnknownPath = string;

export type AbsolutePath = {
  path: string;
  dirname: () => AbsolutePath;
  filename: () => string;
  child: (file: string) => AbsolutePath;
};

export const activeWorkspacePath = (): AbsolutePath => {
  const root = activeWorkspaceFolder();
  return toAbsolutePath(root.uri.fsPath);
};

// Resolves a workspace relative path into an absolute path
export const workspacePath = (unknownPath?: UnknownPath) => {
  if (!unknownPath) {
    return activeWorkspacePath();
  }

  if (path.isAbsolute(unknownPath)) {
    return toAbsolutePath(unknownPath);
  } else {
    const workspaceRoot = activeWorkspaceFolder().uri;
    const absolutePath = path.resolve(workspaceRoot.fsPath, unknownPath);
    return toAbsolutePath(absolutePath);
  }
};

export const workspaceRelativePath = (absPath: AbsolutePath) => {
  const workspaceRoot = activeWorkspaceFolder();
  return path.relative(workspaceRoot.uri.fsPath, absPath.path);
};

export const toAbsolutePath = (path: string): AbsolutePath => {
  return {
    path,
    dirname: () => {
      return toAbsolutePath(dirname(path));
    },
    filename: () => {
      return basename(path);
    },
    child: (file: string) => {
      return toAbsolutePath(join(path, file));
    }
  };
};

export const pathExists = (path: string) => {
  const wsPath = workspacePath(path);
  return existsSync(wsPath.path);
};
