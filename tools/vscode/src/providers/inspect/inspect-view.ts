import { Disposable, Uri } from "vscode";
import { HostWebviewPanel } from "../../hooks";
import { jsonRpcPostMessageServer, JsonRpcPostMessageTarget, JsonRpcServerMethod, kMethodEvalLog, kMethodEvalLogBytes, kMethodEvalLogHeaders, kMethodEvalLogs, kMethodEvalLogSize } from "../../core/jsonrpc";
import { findOpenPort } from "../../core/port";
import { hasMinimumInspectVersion, withMinimumInspectVersion } from "../../inspect/version";
import { kInspectEvalLogFormatVersion, kInspectOpenInspectViewVersion } from "./inspect-constants";
import { inspectEvalLog, inspectEvalLogHeaders, inspectEvalLogs } from "../../inspect/logs";
import { activeWorkspacePath } from "../../core/path";


export class InspectView implements Disposable {
  constructor(
    webviewPanel: HostWebviewPanel,
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
      // TODO: implement
      await this.ensureServer();
      return Promise.resolve(undefined);
    } else {
      return evalLogs(this.log_dir_);
    }
  }

  private async evalLog(
    file: string,
    headerOnly: boolean | number
  ): Promise<string | undefined> {

    if (this.haveInspectEvalLogFormat()) {
      // TODO: implement
      await this.ensureServer();
      return Promise.resolve(undefined);
    } else {
      return evalLog(file, headerOnly);
    }

  }


  private async evalLogSize(
    file: string
  ): Promise<number> {

    if (this.haveInspectEvalLogFormat()) {
      // TODO: implement
      await this.ensureServer();
      return Promise.resolve(1);
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
      // TODO: implement
      await this.ensureServer();
      return Promise.resolve(Uint8Array.from([]));
    } else {
      throw new Error("evalLogBytes not implemented");
    }
  }

  private async evalLogHeaders(files: string[]): Promise<string | undefined> {

    if (this.haveInspectEvalLogFormat()) {
      // TODO: implement
      await this.ensureServer();

      return Promise.resolve(undefined);
    } else {
      return evalLogHeaders(files);
    }

  }

  private async ensureServer() {
    if (this.serverPort_ === undefined) {
      this.serverPort_ = await findOpenPort(7676);

      // TODO: launch the server
    }
  }


  private haveInspectEvalLogFormat() {
    return false;
    // return hasMinimumInspectVersion(kInspectEvalLogFormatVersion);
  }

  dispose() {

    // TODO: kill the server

    this.disconnect_();
  }



  private disconnect_: VoidFunction;
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
