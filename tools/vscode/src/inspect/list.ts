

import { AbsolutePath } from "../core/path";
import { runProcess } from "../core/process";
import { inspectBinPath } from "./props";

export interface TaskDescriptor {
  file: string,
  name: string,
  attribs: Record<string, unknown>;
}

export const inspectListTasks = (cwd: AbsolutePath): TaskDescriptor[] => {
  return inspectListCmd(cwd, "tasks");
};

function inspectListCmd<T>(cwd: AbsolutePath, type: string, args?: string[]): T[] {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["list", type, "--json", ...(args || [])];
    const output = runProcess(inspectBin, cmdArgs, cwd);
    return JSON.parse(output) as T[];
  } else {
    return [];
  }
}