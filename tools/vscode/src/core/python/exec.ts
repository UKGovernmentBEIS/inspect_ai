
import { AbsolutePath, toAbsolutePath } from "../path";
import { runProcess, spawnProcess } from "../process";
import { pythonInterpreter } from "./interpreter";


export function runPythonModule(
  module: string,
  args: string[],
  cwd?: AbsolutePath
) {
  return runPython(["-m", module, ...args], cwd);
}


export function pythonBinaryPath(pythonBinDir: string, binary: string = "python3"): AbsolutePath {
  return toAbsolutePath(pythonBinDir).child(inspectBinDir()).child(binary);
}

export function runPython(
  args: string[],
  cwd?: AbsolutePath
) {

  const execCommand = pythonInterpreter().execCommand;
  if (execCommand) {
    args = [...execCommand.slice(1), ...args];
    return runProcess(execCommand[0], args, cwd);
  } else {
    throw new Error("No active Python interpreter available.");
  }
}

export function spawnPython(
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
  const execCommand = pythonInterpreter().execCommand;
  if (execCommand) {
    const cmd = execCommand[0];
    args = [...execCommand.slice(1), ...args];
    return spawnProcess(cmd, args, cwd, io, lifecycle);
  } else {
    throw new Error("No active Python interpreter available.");
  }

}


export function spawnPythonModule(
  module: string,
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
  return spawnPython(["-m", module, ...args], cwd, io, lifecycle);
}


function inspectBinDir(): string {
  switch (process.platform) {
    case "darwin":
      return "bin";
    case "win32":
      return "Scripts";
    case "linux":
    default:
      return "bin";
  }
}
