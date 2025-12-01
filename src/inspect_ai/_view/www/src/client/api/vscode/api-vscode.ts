import JSON5 from "json5";
import { asyncJsonParse } from "../../../utils/json-worker";

import { getVscodeApi } from "../../../utils/vscode";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  PendingSamples,
  SampleData,
  SampleDataResponse,
} from "../types";
import {
  kMethodEvalLog,
  kMethodEvalLogBytes,
  kMethodEvalLogDir,
  kMethodEvalLogFiles,
  kMethodEvalLogHeaders,
  kMethodEvalLogs,
  kMethodEvalLogSize,
  kMethodLogMessage,
  kMethodPendingSamples,
  kMethodSampleData,
  webViewJsonRpcClient,
} from "./jsonrpc";

const kNotFoundSignal = "NotFound";
const kNotModifiedSignal = "NotModified";

const vscodeClient = webViewJsonRpcClient(getVscodeApi());

async function client_events() {
  return [];
}

async function get_log_root() {
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

const get_log_dir = async () => {
  const response = await vscodeClient(kMethodEvalLogDir, []);
  if (response) {
    const parsed = JSON5.parse(response);
    return parsed.log_dir as string | undefined;
  }
  return undefined;
};

const get_logs = async (mtime: number, clientFileCount: number) => {
  const response = await vscodeClient(kMethodEvalLogFiles, [
    mtime,
    clientFileCount,
  ]);
  if (response) {
    const parsed = JSON5.parse(response);
    return parsed;
  } else {
    return [];
  }
};

async function get_eval_set(): Promise<undefined> {
  return undefined;
}

async function get_flow(): Promise<undefined> {
  return undefined;
}

async function get_log_contents(
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

async function get_log_size(log_file: string) {
  return await vscodeClient(kMethodEvalLogSize, [log_file]);
}

async function get_log_bytes(log_file: string, start: number, end: number) {
  return await vscodeClient(kMethodEvalLogBytes, [log_file, start, end]);
}

async function get_log_summaries(files: string[]) {
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

    const json = await asyncJsonParse<PendingSamples>(response);
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
    const json = await asyncJsonParse<SampleData>(response);
    return {
      status: "OK",
      sampleData: json,
    };
  } else {
    throw new Error(`Unable to load live sample data ${log_file}.`);
  }
}

async function log_message(log_file: string, message: string): Promise<void> {
  await vscodeClient(kMethodLogMessage, [log_file, message]);
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
  get_log_root,
  get_log_dir,
  get_logs,
  get_eval_set,
  get_flow,
  get_log_contents,
  get_log_size,
  get_log_bytes,
  get_log_summaries,
  log_message,
  download_file,
  open_log_file,
  eval_pending_samples,
  eval_log_sample_data,
};

export default api;
