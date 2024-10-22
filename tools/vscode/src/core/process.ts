import { SpawnOptions, SpawnSyncOptionsWithStringEncoding, spawn, spawnSync } from "child_process";
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
    maxBuffer: 1000 * 1000 * 125
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
  options: SpawnOptions,
  io?: {
    stdout?: (data: string) => void;
    stderr?: (data: string) => void;
  },
  lifecycle?: {
    onError?: (error: Error) => void;
    onClose?: (code: number) => void;
  }
) {
  // Process options
  options = { detached: true, ...options };

  // Start the actual process
  const process = spawn(cmd, args, options);

  // Capture stdout
  if (process.stdout) {
    process.stdout.setEncoding("utf-8");
    if (io?.stdout) {
      process.stdout.on("data", io.stdout);
    }
  } else {
    throw new Error("Unexpectedly missing stdout from server");
  }

  // Capture stderr
  if (process.stderr) {
    process.stderr.setEncoding("utf-8");
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