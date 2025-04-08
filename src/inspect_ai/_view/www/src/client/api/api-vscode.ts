import JSON5 from "json5";
import { asyncJsonParse } from "../../utils/json-worker";

import { getVscodeApi } from "../../utils/vscode";
import {
  kMethodEvalLog,
  kMethodEvalLogBytes,
  kMethodEvalLogHeaders,
  kMethodEvalLogs,
  kMethodEvalLogSize,
  kMethodPendingSamples,
  kMethodSampleData,
  webViewJsonRpcClient,
} from "./jsonrpc";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

const kNotFoundSignal = "NotFound";
const kNotModifiedSignal = "NotModified";

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

async function eval_pending_samples(
  log_file: string,
  etag?: string,
): Promise<PendingSampleResponse> {
  // TODO: use web worked to parse when possible
  const response = await vscodeClient(kMethodPendingSamples, [log_file, etag]);
  if (response) {
    if (response === kNotModifiedSignal) {
      return {
        status: "NotModified",
      };
    } else if (response === kNotFoundSignal) {
      return {
        status: "NotFound",
      };
    }

    const json = await asyncJsonParse(response);
    return {
      status: "OK",
      pendingSamples: json,
    };
  } else {
    throw new Error(`Unable to load pending samples ${log_file}.`);
  }
}

async function eval_log_sample_data(
  log_file: string,
  id: string | number,
  epoch: number,
  last_event?: number,
  last_attachment?: number,
): Promise<SampleDataResponse | undefined> {
  const response = await vscodeClient(kMethodSampleData, [
    log_file,
    id,
    epoch,
    last_event,
    last_attachment,
  ]);
  if (response) {
    if (response === kNotModifiedSignal) {
      return {
        status: "NotModified",
      };
    } else if (response === kNotFoundSignal) {
      return {
        status: "NotFound",
      };
    }
    const json = await asyncJsonParse(response);
    return {
      status: "OK",
      sampleData: json,
    };
  } else {
    throw new Error(`Unable to load live sample data ${log_file}.`);
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
  eval_pending_samples,
  eval_log_sample_data,
};

export default api;
