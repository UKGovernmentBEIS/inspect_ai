import { asyncJsonParse } from "../utils/json-worker";
import JSON5 from "json5";

import {
  webViewJsonRpcClient,
  kMethodEvalLog,
  kMethodEvalLogs,
  kMethodEvalLogSize,
  kMethodEvalLogBytes,
  kMethodEvalLogHeaders,
} from "./jsonrpc";
import { getVscodeApi } from "../utils/vscode";
import { Capabilities, LogContents, LogViewAPI } from "./Types";

const vscodeClient = webViewJsonRpcClient(getVscodeApi());

async function client_events() {
  return [];
}

async function eval_logs() {
  const response = await vscodeClient(kMethodEvalLogs, []);
  if (response) {
    const parsed = JSON5.parse(response);
    if (Array.isArray(parsed)) {
      // This is an old response, which omits the log_dir
      return {
        log_dir: "",
        files: parsed,
      };
    } else {
      return parsed;
    }
  } else {
    return undefined;
  }
}

async function eval_log(
  log_file: string,
  headerOnly?: number,
  capabilities?: Capabilities,
): Promise<LogContents> {
  const response = await vscodeClient(kMethodEvalLog, [log_file, headerOnly]);
  if (response) {
    let json;
    if (capabilities?.webWorkers) {
      json = await asyncJsonParse(response);
    } else {
      json = JSON5.parse(response);
    }
    return {
      parsed: json,
      raw: response,
    };
  } else {
    throw new Error(`Unable to load eval log ${log_file}.`);
  }
}

async function eval_log_size(log_file: string) {
  return await vscodeClient(kMethodEvalLogSize, [log_file]);
}

async function eval_log_bytes(log_file: string, start: number, end: number) {
  return await vscodeClient(kMethodEvalLogBytes, [log_file, start, end]);
}

async function eval_log_headers(files: string[]) {
  const response = await vscodeClient(kMethodEvalLogHeaders, [files]);
  if (response) {
    return JSON5.parse(response);
  } else {
    return undefined;
  }
}

async function download_file() {
  throw Error("Downloading files is not supported in VS Code");
}

async function open_log_file(log_file: string, log_dir: string) {
  const msg = {
    type: "displayLogFile",
    url: log_file,
    log_dir: log_dir,
  };
  getVscodeApi()?.postMessage(msg);
}

const api: LogViewAPI = {
  client_events,
  eval_logs,
  eval_log,
  eval_log_size,
  eval_log_bytes,
  eval_log_headers,
  download_file,
  open_log_file,
};

export default api;
