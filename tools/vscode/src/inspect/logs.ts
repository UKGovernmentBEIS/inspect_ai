import { Uri } from "vscode";
import { AbsolutePath } from "../core/path";
import { runProcess } from "../core/process";
import { inspectBinPath } from "./props";
import { createReadStream } from "fs";
import { createInterface } from "readline";
import { withMinimumInspectVersion } from "./version";
import { kInspectMaxLogFileSizeVersion } from "../providers/inspect/inspect-constants";



export function inspectEvalLogs(cwd: AbsolutePath, log_dir?: Uri): string | undefined {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["list", "logs", "--json"];
    if (log_dir) {
      cmdArgs.push("--log-dir");
      cmdArgs.push(log_dir.toString(true));
    }
    const output = runProcess(inspectBin, cmdArgs, cwd);
    return output;
  }
}

export function inspectEvalLog(cwd: AbsolutePath, log: string, headerOnly?: number): string | undefined {
  const inspectBin = inspectBinPath();
  if (inspectBin) {
    const cmdArgs = ["info", "log-file", log];
    withMinimumInspectVersion(kInspectMaxLogFileSizeVersion, () => {
      // This is a newer version of Inspect which includes support
      // for a max size before only header is sent, provide a size
      cmdArgs.push("--header-only");
      cmdArgs.push(String(headerOnly || 100));
    }, () => {
      // This is an old version of Inspect which respects only a boolean
      // so send a boolean for header only if that is requested
      if (headerOnly === 0) {
        cmdArgs.push("--header-only");
      }
    });

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

export interface InspectLogInfo {
  hasEvalKey: boolean,
  hasStatusKey: boolean,
  status?: string
}

export function inspectLogInfo(file: Uri): Promise<InspectLogInfo> {
  return new Promise((resolve, reject) => {

    // Create a read stream
    const fileStream = createReadStream(file.fsPath);
    fileStream.on('error', (err) => {
      reject(err);
    });

    // Create a readline interface
    const rl = createInterface({
      input: fileStream,
      crlfDelay: Infinity
    });

    const stopReading = () => {
      rl.close();
      fileStream.close();
    };

    // Eval logs will look like json and have a status and eval key minimally
    const state: InspectLogInfo = {
      hasEvalKey: false,
      hasStatusKey: false,
    };

    // Process each line
    let lineCount = 0;
    rl.on('line', (line) => {

      // Perform additional processing on each line here
      if (!state.hasStatusKey) {
        const match = line.match(/\s*"status":\s*"(\S+)"/);
        if (match) {
          state.hasStatusKey = true;
          state.status = match[1];
        }
      }

      if (!state.hasEvalKey) {
        const match = line.match(/\s*"eval":*/);
        state.hasEvalKey = !!match;
      }

      // We've found the keys
      if (state.hasEvalKey && state.hasStatusKey) {
        stopReading();
      }

      // If we haven't found keys yet, give up, this isn't valid
      if (++lineCount > 20) {
        stopReading();
      }
    });

    rl.on('close', () => {
      resolve(state);
    });

    rl.on('error', (err) => {
      reject(err);
    });
  });
}