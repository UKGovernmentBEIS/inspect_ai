import { asyncJsonParse } from "../../utils/json-worker";
import { download_file } from "./api-shared";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

const loaded_time = Date.now();
let last_eval_time = 0;

async function client_events() {
  const params = new URLSearchParams();
  params.append("loaded_time", String(loaded_time.valueOf()));
  params.append("last_eval_time", String(last_eval_time.valueOf()));
  return (await api("GET", `/api/events?${params.toString()}`)).parsed;
}

async function eval_logs() {
  const logs = await api("GET", `/api/logs`);
  last_eval_time = Date.now();
  return logs.parsed;
}

async function eval_log(
  file: string,
  headerOnly?: number,
  _capabilities?: Capabilities,
): Promise<LogContents> {
  return await api(
    "GET",
    `/api/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`,
  );
}

async function eval_log_size(file: string): Promise<number> {
  return (await api("GET", `/api/log-size/${encodeURIComponent(file)}`)).parsed;
}

async function eval_log_bytes(file: string, start: number, end: number) {
  return await api_bytes(
    "GET",
    `/api/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`,
  );
}

async function eval_log_headers(files: string[]) {
  const params = new URLSearchParams();
  for (const file of files) {
    params.append("file", file);
  }
  return (await api("GET", `/api/log-headers?${params.toString()}`)).parsed;
}

async function eval_pending_samples(
  log_file: string,
  etag?: string,
): Promise<PendingSampleResponse> {
  // Attach the log file
  const params = new URLSearchParams();
  params.append("log", log_file);

  // Send the etag along
  const headers: Record<string, string> = {};
  if (etag) {
    headers["If-None-Match"] = etag;
  }

  // Build up the request
  const request: Request<PendingSampleResponse> = {
    headers,
    parse: async (text: string) => {
      const pendingSamples = await asyncJsonParse(text);
      return {
        status: "OK",
        pendingSamples,
      };
    },
    handleError: (status: number) => {
      if (status === 404) {
        return {
          status: "NotFound",
        };
      } else if (status === 304) {
        return {
          status: "NotModified",
        };
      }
    },
  };
  // Fetch the result
  const result = (
    await apiRequest<PendingSampleResponse>(
      "GET",
      `/api/pending-samples?${params.toString()}`,
      request,
    )
  ).parsed;

  return result;
}

async function eval_log_sample_data(
  log_file: string,
  id: string | number,
  epoch: number,
  last_event?: number,
  last_attachment?: number,
): Promise<SampleDataResponse | undefined> {
  const params = new URLSearchParams();
  params.append("log", log_file);
  params.append("id", String(id));
  params.append("epoch", String(epoch));
  if (last_event !== undefined) {
    params.append("last-event-id", String(last_event));
  }

  if (last_attachment !== undefined) {
    params.append("after-attachment-id", String(last_attachment));
  }

  // Build up the request
  const request: Request<SampleDataResponse> = {
    headers: {},
    parse: async (text: string) => {
      const pendingSamples = await asyncJsonParse(text);
      return {
        status: "OK",
        sampleData: pendingSamples,
      };
    },
    handleError: (status: number) => {
      if (status === 404) {
        return {
          status: "NotFound",
        };
      } else if (status === 304) {
        return {
          status: "NotModified",
        };
      }
    },
  };
  // Fetch the result
  const result = (
    await apiRequest<SampleDataResponse>(
      "GET",
      `/api/pending-sample-data?${params.toString()}`,
      request,
    )
  ).parsed;

  return result;
}

async function log_message(log_file: string, message: string) {
  const params = new URLSearchParams();
  params.append("log_file", log_file);
  params.append("message", message);

  const request: Request<void> = {
    headers: {
      "Content-Type": "text/plain",
    },
    parse: async (text: string) => {
      if (text !== "") {
        throw new Error(`Unexpected response from log_message: ${text}`);
      }
      return;
    },
  };
  await apiRequest<void>(
    "GET",
    `/api/log-message?${params.toString()}`,
    request,
  );
}

interface Request<T> {
  headers?: Record<string, string>;
  body?: string;
  parse?: (text: string) => Promise<T>;
  handleError?: (status: number) => T | undefined;
}

async function apiRequest<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  request: Request<T>,
): Promise<{ raw: string; parsed: T }> {
  // build headers
  const responseHeaders: HeadersInit = {
    Accept: "application/json",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache",
    ...request.headers,
  };
  if (request.body) {
    responseHeaders["Content-Type"] = "application/json";
  }

  // make request
  const response = await fetch(`${path}`, {
    method,
    headers: responseHeaders,
    body: request.body,
  });
  if (response.ok) {
    const text = await response.text();
    const parse = request.parse || asyncJsonParse;
    return {
      parsed: (await parse(text)) as T,
      raw: text,
    };
  } else if (response.status !== 200) {
    // See if the request handler wants to handle this
    const errorResponse = request.handleError
      ? request.handleError(response.status)
      : undefined;
    if (errorResponse) {
      return {
        raw: response.statusText,
        parsed: errorResponse,
      };
    }

    const message = (await response.text()) || response.statusText;
    const error = new Error(`Error: ${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

async function api(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  headers?: Record<string, string>,
  body?: string,
) {
  // build headers
  const responseHeaders: HeadersInit = {
    Accept: "application/json",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache",
    ...headers,
  };
  if (body) {
    responseHeaders["Content-Type"] = "application/json";
  }

  // make request
  const response = await fetch(`${path}`, {
    method,
    headers: responseHeaders,
    body,
  });
  if (response.ok) {
    const text = await response.text();
    return {
      parsed: await asyncJsonParse(text),
      raw: text,
    };
  } else if (response.status !== 200) {
    const message = (await response.text()) || response.statusText;
    const error = new Error(`${message}`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

async function api_bytes(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
) {
  // build headers
  const headers: HeadersInit = {
    Accept: "application/octet-stream",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache",
  };

  // make request
  const response = await fetch(`${path}`, { method, headers });
  if (response.ok) {
    const buffer = await response.arrayBuffer();
    return new Uint8Array(buffer);
  } else if (response.status !== 200) {
    const message = (await response.text()) || response.statusText;
    const error = new Error(`Error: ${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

async function open_log_file() {
  // No op
}

const browserApi: LogViewAPI = {
  client_events,
  eval_logs,
  eval_log,
  eval_log_size,
  eval_log_bytes,
  eval_log_overviews: eval_log_headers,
  log_message,
  download_file,

  open_log_file,
  eval_pending_samples,
  eval_log_sample_data,
};
export default browserApi;
