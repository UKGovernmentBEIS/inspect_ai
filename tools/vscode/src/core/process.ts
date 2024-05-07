import { SpawnSyncOptionsWithStringEncoding, spawn, spawnSync } from "child_process";
import { AbsolutePath } from "./path";


export function runProcess(
  cmd: string | AbsolutePath,
  args: string[],
  cwd?: AbsolutePath
) {

  // Process options
  const options: SpawnSyncOptionsWithStringEncoding = {
    cwd: cwd?.path,
    encoding: "utf-8",
    windowsHide: true,
    maxBuffer: 1000 * 1000 * 100
  };

  cmd = typeof (cmd) === "string" ? cmd : cmd.path;
  const result = spawnSync(cmd, args, options);
  if (result.error) {
    throw new Error(
      `The process could not be started\n${result.error.message}`
    );
  } else if (result.status === 0) {
    return result.stdout;
  } else {
    throw new Error(
      `Command failed with code ${result.status}: ${result.stderr}`
    );
  }
}


export function spawnProcess(
  cmd: string,
  args: string[],
  cwd: AbsolutePath,
  io?: {
    stdout?: (data: Buffer | string) => void;
    stderr?: (data: Buffer | string) => void;
  },
  lifecycle?: {
    onError?: (error: Error) => void;
    onClose?: (code: number) => void;
  }
) {
  // Process options
  const options = {
    cwd: cwd.path,
    detached: true,
  };

  // Start the actual process
  const process = spawn(cmd, args, options);

  // Capture stdout
  if (process.stdout) {
    if (io?.stdout) {
      process.stdout.on("data", io.stdout);
    }
  } else {
    throw new Error("Unexpectedly missing stdout from server");
  }

  // Capture stderr
  if (process.stderr) {
    if (io?.stderr) {
      process.stderr.on("data", io.stderr);
    }
  } else {
    throw new Error("Unexpectedly missing stderr from server");
  }

  // Note errors
  if (lifecycle?.onError) {
    process.on("error", lifecycle.onError);
  }

  if (lifecycle?.onClose) {
    process.on("close", lifecycle?.onClose);
  }
  return process;
}