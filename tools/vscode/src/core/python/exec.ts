import { existsSync } from "node:fs";
import { AbsolutePath, toAbsolutePath } from "../path";
import { runProcess, spawnProcess } from "../process";
import { PythonInterpreter, pythonInterpreter } from "./interpreter";
import { dirname, join } from "path";

export function runPythonModule(
  module: string,
  args: string[],
  cwd?: AbsolutePath
) {
  return runPython(["-m", module, ...args], cwd);
}

export function pythonBinaryPath(
  interpreter: PythonInterpreter,
  binary: string
): AbsolutePath | null {
  // First look within the bin dir of the interpreter
  if (interpreter.pythonBinDir) {
    const binaryPath = toAbsolutePath(interpreter.pythonBinDir)
      .child(inspectBinDir())
      .child(binary);
    if (existsSync(binaryPath.path)) {
      return binaryPath;
    }
  }

  // We couldn't find it, so now look around based upon heuristics
  const path = platformPaths(interpreter, binary).find((path) => {
    return existsSync(path);
  });
  if (path) {
    return toAbsolutePath(path);
  } else {
    return null;
  }
}

// A list of heuristic paths to use if we can't find inspect
// using the interpreter path. This will happen in cases
// where the global interpreter is being used (and it doesn't install
// scripts relative to the interpreter but instead in a global location)
const platformPaths = (interpreter: PythonInterpreter, binary: string) => {
  // find the folder that contained the python bin
  const binDir =
    interpreter.execCommand && interpreter.execCommand.length > 0
      ? dirname(interpreter.execCommand[0])
      : "";

  // Check in the bin dir next to the python interpreter (on all platforms)
  const paths = [join(binDir, binary)];
  switch (process.platform) {
    case "darwin":
      break;
    case "linux":
      // Also check .local/bin on linux
      paths.unshift(join(process.env.HOME || "", ".local", "bin", binary));
      break;
    default:
      break;
  }
  return paths;
};

export function runPython(args: string[], cwd?: AbsolutePath) {
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
    stdout?: (data: string) => void;
    stderr?: (data: string) => void;
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
    return spawnProcess(cmd, args, { cwd: cwd.path }, io, lifecycle);
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
