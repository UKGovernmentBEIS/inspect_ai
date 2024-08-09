import JSON5 from "json5";

import { asyncJsonParse } from "../utils/Json.mjs";

import {
  webViewJsonRpcClient,
  kMethodEvalLog,
  kMethodEvalLogs,
  kMethodEvalLogHeaders,
} from "./jsonrpc.mjs";

const vscodeApi = window.acquireVsCodeApi
  ? window.acquireVsCodeApi()
  : undefined;

const vscodeClient = webViewJsonRpcClient(vscodeApi);

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

async function eval_log(file, headerOnly, capabilities) {
  const response = await vscodeClient(kMethodEvalLog, [file, headerOnly]);
  if (response) {
    let json;
    if (capabilities.webWorkers) {
      json = await asyncJsonParse(response);
    } else {
      json = JSON5.parse(response);
    }
    return {
      parsed: json,
      raw: response,
    };
  } else {
    return undefined;
  }
}

async function eval_log_headers(files) {
  const response = await vscodeClient(kMethodEvalLogHeaders, [files]);
  if (response) {
    return JSON5.parse(response);
  } else {
    return undefined;
  }
}

async function download_file(logFile) {
  vscodeApi.postMessage({ type: "openWorkspaceFile", url: logFile });
}

export default {
  client_events,
  eval_logs,
  eval_log,
  eval_log_headers,
  download_file,
};
