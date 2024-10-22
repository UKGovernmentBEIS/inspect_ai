//@ts-check

import { asyncJsonParse } from "../utils/Json.mjs";
// @ts-ignore
import JSON5 from "json5";

import {
  webViewJsonRpcClient,
  kMethodEvalLog,
  kMethodEvalLogs,
  kMethodEvalLogSize,
  kMethodEvalLogBytes,
  kMethodEvalLogHeaders,
} from "./jsonrpc.mjs";
import { getVscodeApi } from "../utils/vscode.mjs";

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

async function eval_log(file, headerOnly, capabilities) {
  const response = await vscodeClient(kMethodEvalLog, [file, headerOnly]);
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
    return undefined;
  }
}

async function eval_log_size(file) {
  return await vscodeClient(kMethodEvalLogSize, [file]);
}

async function eval_log_bytes(file, start, end) {
  return await vscodeClient(kMethodEvalLogBytes, [file, start, end]);
}

async function eval_log_headers(files) {
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

async function open_log_file(url, log_dir) {
  const msg = {
    type: "displayLogFile",
    url: url,
    log_dir: log_dir,
  };
  getVscodeApi().postMessage(msg);
}

/** @type {import("./Types.mjs").LogViewAPI} */
export default {
  client_events,
  eval_logs,
  eval_log,
  eval_log_size,
  eval_log_bytes,
  eval_log_headers,
  download_file,
  open_log_file,
};
