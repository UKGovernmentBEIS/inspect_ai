import { ChildProcess, SpawnOptions } from "child_process";
import * as os from "os";

import { Disposable, OutputChannel, Uri } from "vscode";
import { HostWebviewPanel } from "../../hooks";
import { jsonRpcPostMessageServer, JsonRpcPostMessageTarget, JsonRpcServerMethod, kMethodEvalLog, kMethodEvalLogBytes, kMethodEvalLogHeaders, kMethodEvalLogs, kMethodEvalLogSize } from "../../core/jsonrpc";
import { findOpenPort } from "../../core/port";
import { hasMinimumInspectVersion, withMinimumInspectVersion } from "../../inspect/version";
import { kInspectEvalLogFormatVersion, kInspectOpenInspectViewVersion } from "./inspect-constants";
import { inspectEvalLog, inspectEvalLogHeaders, inspectEvalLogs } from "../../inspect/logs";
import { activeWorkspacePath } from "../../core/path";
import { inspectBinPath } from "../../inspect/props";
import { shQuote } from "../../core/string";
import { spawnProcess } from "../../core/process";


export class InspectView implements Disposable {
  constructor(
    webviewPanel: HostWebviewPanel,
    private outputChannel_: OutputChannel,
    private log_dir_: Uri
  ) {
    this.disconnect_ = webviewPanelJsonRpcServer(webviewPanel, {
      [kMethodEvalLogs]: () => this.evalLogs(),
      [kMethodEvalLog]: (params: unknown[]) => this.evalLog(params[0] as string, params[1] as number | boolean),
      [kMethodEvalLogSize]: (params: unknown[]) => this.evalLogSize(params[0] as string),
      [kMethodEvalLogBytes]: (params: unknown[]) => this.evalLogBytes(params[0] as string, params[1] as number, params[2] as number),
      [kMethodEvalLogHeaders]: (params: unknown[]) => this.evalLogHeaders(params[0] as string[])
    });
  }

  private async evalLogs(): Promise<string | undefined> {
    if (this.haveInspectEvalLogFormat()) {
      await this.ensureServer();
      return this.api_json(`/api/logs`);
    } else {
      return evalLogs(this.log_dir_);
    }
  }

  private async evalLog(
    file: string,
    headerOnly: boolean | number
  ): Promise<string | undefined> {
    if (this.haveInspectEvalLogFormat()) {
      await this.ensureServer();
      return await this.api_json(`/api/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`);
    } else {
      return evalLog(file, headerOnly);
    }
  }


  private async evalLogSize(
    file: string
  ): Promise<number> {

    if (this.haveInspectEvalLogFormat()) {
      await this.ensureServer();
      return Number(await this.api_json(`/api/log-size/${encodeURIComponent(file)}`));
    } else {
      throw new Error("evalLogSize not implemented");
    }
  }

  private async evalLogBytes(
    file: string,
    start: number,
    end: number
  ): Promise<Uint8Array> {
    if (this.haveInspectEvalLogFormat()) {
      await this.ensureServer();
      return this.api_bytes(`/api/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`);
    } else {
      throw new Error("evalLogBytes not implemented");
    }
  }

  private async evalLogHeaders(files: string[]): Promise<string | undefined> {

    if (this.haveInspectEvalLogFormat()) {
      await this.ensureServer();
      const params = new URLSearchParams();
      for (const file of files) {
        params.append("file", file);
      }
      return this.api_json(`/api/log-headers?${params.toString()}`);
    } else {
      return evalLogHeaders(files);
    }

  }

  private async ensureServer(): Promise<undefined> {
    if (this.serverProcess_ === undefined || this.serverProcess_?.exitCode) {

      // find port
      this.serverProcess_ == undefined;
      this.serverPort_ = await findOpenPort(7676);

      return new Promise((resolve, reject) => {


        // find inspect
        const inspect = inspectBinPath();
        if (!inspect) {
          throw new Error("inspect view: inspect installation not found");
        }

        // launch process
        const options: SpawnOptions = {
          env: {
            "COLUMNS": "150"
          },
          shell: os.platform() === "win32"
        };

        // forward output to channel and resolve promise
        let resolved = false;
        const onOutput = (output: string) => {
          this.outputChannel_.append(output);
          if (!resolved) {
            resolved = true;
            resolve(undefined);
          }
        };

        // run server
        const quote = os.platform() === "win32" ? shQuote : (arg: string) => arg;
        const args = [
          "view", "start", 
          "--port", String(this.serverPort_), 
          "--log-dir", this.log_dir_.toString(),
          "--log-level", "info", "--no-ansi"
        ];
        this.serverProcess_ = spawnProcess(quote(inspect.path), args.map(quote), options, {
          stdout: onOutput,
          stderr: onOutput,
        }, {
          onClose: (code: number) => {
            this.outputChannel_.appendLine(`Inspect View exited with code ${code} (pid=${this.serverProcess_?.pid})`);
          },
          onError: (error: Error) => {
            this.outputChannel_.appendLine(`Error starting Inspect View ${error.message}`);
            reject(error);
          },
        });
        this.outputChannel_.appendLine(`Starting Inspect View on port ${this.serverPort_} (pid=${this.serverProcess_?.pid})`);
      });

    }
  }


  private haveInspectEvalLogFormat() {
    return hasMinimumInspectVersion(kInspectEvalLogFormatVersion);
  }

  private async api_json(path: string): Promise<string> {
    return await this.api(path, false) as string
  }

  private async api_bytes(path: string): Promise<Uint8Array> {
    return await this.api(path, false) as Uint8Array
  }

  private async api(path: string, binary: boolean = false): Promise<string | Uint8Array> {
    // build headers
    const headers = {
      Accept: binary ? "application/octet-stream" : "application/json",
      Pragma: "no-cache",
      Expires: "0",
      ["Cache-Control"]: "no-cache",
    };

    // make request
    const response = await fetch(`http://localhost:${this.serverPort_}${path}`, { method: "GET", headers });
    if (response.ok) {
      if (binary) {
        const buffer = await response.arrayBuffer();
        return new Uint8Array(buffer)
      } else {
        return await response.text();
      }
    } else if (response.status !== 200) {
      const message = (await response.text()) || response.statusText;
      const error = new Error(`Error: ${response.status}: ${message})`);
      throw error;
    } else {
      throw new Error(`${response.status} - ${response.statusText} `);
    }
  }


  dispose() {
    this.serverProcess_?.kill();
    this.disconnect_();
  }

  private disconnect_: VoidFunction;
  private serverProcess_?: ChildProcess = undefined;
  private serverPort_?: number = undefined;

}



export function webviewPanelJsonRpcServer(
  webviewPanel: HostWebviewPanel,
  methods:
    | Record<string, JsonRpcServerMethod>
    | ((name: string) => JsonRpcServerMethod | undefined)
): () => void {
  const target: JsonRpcPostMessageTarget = {
    postMessage: (data: unknown) => {
      void webviewPanel.webview.postMessage(data);
    },
    onMessage: (handler: (data: unknown) => void) => {
      const disposable = webviewPanel.webview.onDidReceiveMessage((ev) => {
        handler(ev);
      });
      return () => {
        disposable.dispose();
      };
    },
  };
  return jsonRpcPostMessageServer(target, methods);
}





// The eval commands below need to be coordinated in terms of their working directory
// The evalLogs() call will return log files with relative paths to the working dir (if possible)
// and subsequent calls like evalLog() need to be able to deal with these relative paths
// by using the same working directory.
//
// So, we always use the workspace root as the working directory and will resolve
// paths that way. Note that paths can be S3 urls, for example, in which case the paths
// will be absolute (so cwd doesn't really matter so much in this case).
function evalLogs(log_dir: Uri): Promise<string | undefined> {
  // Return both the log_dir and the logs

  const response = withMinimumInspectVersion<string | undefined>(
    kInspectOpenInspectViewVersion,
    () => {
      const logs = inspectEvalLogs(activeWorkspacePath(), log_dir);
      const logsJson = logs ? (JSON.parse(logs) as unknown) : [];
      return JSON.stringify({ log_dir: log_dir.toString(), files: logsJson });
    },
    () => {
      // Return the original log content
      return inspectEvalLogs(activeWorkspacePath());
    }
  );
  return Promise.resolve(response);

}

function evalLog(
  file: string,
  headerOnly: boolean | number
): Promise<string | undefined> {
  // Old clients pass a boolean value which we need to resolve
  // into the max number of MB the log can be before samples are excluded
  // and it becomes header_only
  if (typeof headerOnly === "boolean") {
    headerOnly = headerOnly ? 0 : Number.MAX_SAFE_INTEGER;
  }

  return Promise.resolve(
    inspectEvalLog(activeWorkspacePath(), file, headerOnly)
  );
}

function evalLogHeaders(files: string[]) {
  return Promise.resolve(inspectEvalLogHeaders(activeWorkspacePath(), files));
}
