import { SemVer, coerce } from "semver";

import { log } from "../core/log";
import { pythonBinaryPath, pythonInterpreter } from "../core/python";
import { AbsolutePath, toAbsolutePath } from "../core/path";
import { Disposable } from "vscode";
import { runProcess } from "../core/process";
import { join } from "path";
import { userRuntimeDir } from "../core/appdirs";
import { kInspectChangeEvalSignalVersion } from "../providers/inspect/inspect-constants";

const kPythonPackageName = "inspect_ai";

// we cache the results of these functions so long as
// they (a) return success, and (b) the active python
// interpreter hasn't been changed
class InspectPropsCache implements Disposable {
  private readonly eventHandle_: Disposable;

  constructor(
    private binPath_: AbsolutePath | null,
    private version_: SemVer | null,
    private viewPath_: AbsolutePath | null
  ) {
    this.eventHandle_ = pythonInterpreter().onDidChange(() => {
      log.info("Resetting Inspect props to null");
      this.binPath_ = null;
      this.version_ = null;
      this.viewPath_ = null;
    });
  }

  get binPath(): AbsolutePath | null {
    return this.binPath_;
  }

  setBinPath(binPath: AbsolutePath) {
    log.info(`Inspect bin path: ${binPath.path}`);
    this.binPath_ = binPath;
  }

  get version(): SemVer | null {
    return this.version_;
  }

  setVersion(version: SemVer) {
    log.info(`Inspect version: ${version.toString()}`);
    this.version_ = version;
  }

  get viewPath(): AbsolutePath | null {
    return this.viewPath_;
  }

  setViewPath(path: AbsolutePath) {
    log.info(`Inspect view path: ${path.path}`);
    this.viewPath_ = path;
  }

  dispose() {
    this.eventHandle_.dispose();
  }
}

export function initInspectProps(): Disposable {
  inspectPropsCache_ = new InspectPropsCache(null, null, null);
  return inspectPropsCache_;
}

let inspectPropsCache_: InspectPropsCache;

export function inspectVersion(): SemVer | null {
  if (inspectPropsCache_.version) {
    return inspectPropsCache_.version;
  } else {
    const inspectBin = inspectBinPath();
    if (inspectBin) {
      try {
        const versionJson = runProcess(inspectBin, [
          "info",
          "version",
          "--json",
        ]);
        const version = JSON.parse(versionJson) as {
          version: string;
          path: string;
        };
        const parsedVersion = coerce(version.version);
        if (parsedVersion) {
          inspectPropsCache_.setVersion(parsedVersion);
        }
        return parsedVersion;
      } catch (error) {
        log.error("Error attempting to read Inspect version.");
        log.error(error instanceof Error ? error : String(error));
        return null;
      }
    } else {
      return null;
    }
  }
}

// path to inspect view www assets
export function inspectViewPath(): AbsolutePath | null {
  if (inspectPropsCache_.viewPath) {
    return inspectPropsCache_.viewPath;
  } else {
    const inspectBin = inspectBinPath();
    if (inspectBin) {
      try {
        const versionJson = runProcess(inspectBin, [
          "info",
          "version",
          "--json",
        ]);
        const version = JSON.parse(versionJson) as {
          version: string;
          path: string;
        };
        const viewPath = toAbsolutePath(version.path)
          .child("_view")
          .child("www");
        if (viewPath) {
          inspectPropsCache_.setViewPath(viewPath);
        }
        return viewPath;
      } catch (error) {
        log.error("Error attempting to read Inspect view path.");
        log.error(error instanceof Error ? error : String(error));
        return null;
      }
    } else {
      return null;
    }
  }
}

export function inspectBinPath(): AbsolutePath | null {
  if (inspectPropsCache_.binPath) {
    return inspectPropsCache_.binPath;
  } else {
    const interpreter = pythonInterpreter();
    if (interpreter.available) {
      try {
        const binPath = pythonBinaryPath(interpreter, inspectFileName());
        if (binPath) {
          inspectPropsCache_.setBinPath(binPath);
        }
        return binPath;
      } catch (error) {
        log.error("Error attempting to read Inspect version.");
        log.error(error instanceof Error ? error : String(error));
        return null;
      }
    } else {
      return null;
    }
  }
}

export function inspectLastEvalPath(): AbsolutePath | null {
  const version = inspectVersion();
  const fileName =
    version && version.compare(kInspectChangeEvalSignalVersion) < 0
      ? "last-eval"
      : "last-eval-result";
  const lastEvalFile = join(
    userRuntimeDir(kPythonPackageName),
    "view",
    fileName
  );
  return toAbsolutePath(lastEvalFile);
}

function inspectFileName(): string {
  switch (process.platform) {
    case "darwin":
      return "inspect";
    case "win32":
      return "inspect.exe";
    case "linux":
    default:
      return "inspect";
  }
}
