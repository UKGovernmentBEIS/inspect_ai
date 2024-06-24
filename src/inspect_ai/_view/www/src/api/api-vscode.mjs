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

async function eval_log(file, headerOnly) {
  const response = await vscodeClient(kMethodEvalLog, [file, headerOnly]);
  if (response) {
    return JSON5.parse(response);
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

export default {
  client_events,
  eval_logs,
  eval_log,
  eval_log_headers,
};
