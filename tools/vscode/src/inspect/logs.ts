import { AbsolutePath } from "../core/path";
import { runProcess } from "../core/process";
import { inspectBinPath } from "./props";



export function inspectEvalLogs(cwd: AbsolutePath): string | undefined {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["list", "logs", "--json"];
    const output = runProcess(inspectBin, cmdArgs, cwd);
    return output;
  }
}

export function inspectEvalLog(cwd: AbsolutePath, log: string, headerOnly: boolean): string | undefined {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["info", "log-file", log];
    if (headerOnly) {
      cmdArgs.push("--header-only");
    }
    const output = runProcess(inspectBin, cmdArgs, cwd);
    return output;
  }
}

export function inspectEvalLogHeaders(cwd: AbsolutePath, logs: string[]): string | undefined {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["info", "log-file-headers", ...logs];
    const output = runProcess(inspectBin, cmdArgs, cwd);
    return output;
  }
}