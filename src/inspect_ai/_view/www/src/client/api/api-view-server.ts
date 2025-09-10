import { asyncJsonParse } from "../../utils/json-worker";
import { download_file } from "./api-shared";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

/* global __VIEW_SERVER_API_URL__ */
declare global {
  // from vite config
  const __VIEW_SERVER_API_URL__: string | undefined;
}

const loaded_time = Date.now();
let last_eval_time = 0;

interface Request<T> {
  headers?: Record<string, string>;
  body?: string;
  parse?: (text: string) => Promise<T>;
  handleError?: (status: number) => T | undefined;
}

interface ServerFetchAPI {
  fetchString: (
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
    headers?: Record<string, string>,
    body?: string,
  ) => Promise<{
    parsed: any;
    raw: string;
  }>;
  fetchBytes: (
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
  ) => Promise<Uint8Array>;
  fetchType: <T>(
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
    request: Request<T>,
  ) => Promise<{ raw: string; parsed: T }>;
}

function createServerFetchApi(apiBaseUrl?: string): ServerFetchAPI {
  const API_BASE_URL = apiBaseUrl || "";

  function buildApiUrl(path: string): string {
    if (!API_BASE_URL) {
      return path;
    }
    const base = API_BASE_URL.endsWith("/")
      ? API_BASE_URL.slice(0, -1)
      : API_BASE_URL;
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    return base + cleanPath;
  }

  function isApiCrossOrigin(): boolean {
    try {
      return Boolean(
        API_BASE_URL && new URL(API_BASE_URL).origin !== window.location.origin,
      );
    } catch (TypeError) {
      return false;
    }
  }

  async function apiRequest<T>(
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
    request: Request<T>,
  ): Promise<{ raw: string; parsed: T }> {
    const url = buildApiUrl(path);

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
    const response = await fetch(url, {
      method,
      headers: responseHeaders,
      body: request.body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
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
    const url = buildApiUrl(path);

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
    const response = await fetch(url, {
      method,
      headers: responseHeaders,
      body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
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
    const url = buildApiUrl(path);

    // build headers
    const headers: HeadersInit = {
      Accept: "application/octet-stream",
      Pragma: "no-cache",
      Expires: "0",
      ["Cache-Control"]: "no-cache",
    };

    // make request
    const response = await fetch(url, {
      method,
      headers,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });
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

  return {
    fetchString: api,
    fetchBytes: api_bytes,
    fetchType: apiRequest,
  };
}

async function open_log_file() {
  // No op
}

/**
 * Create a view server API with optional server-side log listing
 */
export function createViewServerApi(
  options: { log_dir?: string; apiBaseUrl?: string } = {},
): LogViewAPI {
  const { log_dir } = options;

  const fetchApi = createServerFetchApi(options.apiBaseUrl);

  return {
    client_events: async () => {
      const params = new URLSearchParams();
      params.append("loaded_time", String(loaded_time.valueOf()));
      params.append("last_eval_time", String(last_eval_time.valueOf()));
      const result = await fetchApi.fetchString(
        "GET",
        `/events?${params.toString()}`,
      );
      return result.parsed;
    },
    eval_logs: async () => {
      const path = log_dir
        ? `/logs?log_dir=${encodeURIComponent(log_dir)}`
        : "/logs";
      const logs = await fetchApi.fetchString("GET", path);
      last_eval_time = Date.now();
      return logs.parsed;
    },
    eval_log: async (
      file: string,
      headerOnly?: number,
      _capabilities?: Capabilities,
    ): Promise<LogContents> => {
      return await fetchApi.fetchString(
        "GET",
        `/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`,
      );
    },
    eval_log_size: async (file: string): Promise<number> => {
      const result = await fetchApi.fetchString(
        "GET",
        `/log-size/${encodeURIComponent(file)}`,
      );
      return result.parsed;
    },
    eval_log_bytes: async (file: string, start: number, end: number) => {
      return await fetchApi.fetchBytes(
        "GET",
        `/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`,
      );
    },
    eval_log_overviews: async (files: string[]) => {
      const params = new URLSearchParams();
      for (const file of files) {
        params.append("file", file);
      }
      const result = await fetchApi.fetchString(
        "GET",
        `/log-headers?${params.toString()}`,
      );
      return result.parsed;
    },
    log_message: async (log_file: string, message: string) => {
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
      await fetchApi.fetchType<void>(
        "GET",
        `/log-message?${params.toString()}`,
        request,
      );
    },
    download_file,
    open_log_file,
    eval_pending_samples: async (
      log_file: string,
      etag?: string,
    ): Promise<PendingSampleResponse> => {
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
      const result = await fetchApi.fetchType<PendingSampleResponse>(
        "GET",
        `/pending-samples?${params.toString()}`,
        request,
      );

      return result.parsed;
    },
    eval_log_sample_data: async (
      log_file: string,
      id: string | number,
      epoch: number,
      last_event?: number,
      last_attachment?: number,
    ): Promise<SampleDataResponse | undefined> => {
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
      const result = await fetchApi.fetchType<SampleDataResponse>(
        "GET",
        `/pending-sample-data?${params.toString()}`,
        request,
      );

      return result.parsed;
    },
  };
}
