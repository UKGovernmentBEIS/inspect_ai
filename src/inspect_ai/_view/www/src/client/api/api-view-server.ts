import { asyncJsonParse } from "../../utils/json-worker";
import { download_file } from "./api-shared";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

declare global {
  const __VIEW_SERVER_API_URL__: string | undefined;
}

const LOADED_TIME = Date.now();

let lastEvalTime = 0;

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

interface Request<T> {
  headers?: Record<string, string>;
  body?: string;
  parse?: (text: string) => Promise<T>;
  handleError?: (status: number) => T | undefined;
}

interface ServerFetchAPI {
  fetchString: (
    method: HttpMethod,
    path: string,
    headers?: Record<string, string>,
    body?: string,
  ) => Promise<{
    parsed: any;
    raw: string;
  }>;
  fetchBytes: (method: HttpMethod, path: string) => Promise<Uint8Array>;
  fetchType: <T>(
    method: HttpMethod,
    path: string,
    request: Request<T>,
  ) => Promise<{ raw: string; parsed: T }>;
}

function createServerFetchApi(apiBaseUrl?: string): ServerFetchAPI {
  const apiUrl = apiBaseUrl || "";

  function buildApiUrl(path: string): string {
    if (!apiUrl) {
      return path;
    }
    const base = apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl;
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    return base + cleanPath;
  }

  function isApiCrossOrigin(): boolean {
    try {
      return Boolean(
        apiUrl && new URL(apiUrl).origin !== window.location.origin,
      );
    } catch (error) {
      return false;
    }
  }

  async function apiRequest<T>(
    method: HttpMethod,
    path: string,
    request: Request<T>,
  ): Promise<{ raw: string; parsed: T }> {
    const url = buildApiUrl(path);

    const responseHeaders: HeadersInit = {
      Accept: "application/json",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
      ...request.headers,
    };
    if (request.body) {
      responseHeaders["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers: responseHeaders,
      body: request.body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (!response.ok) {
      const errorResponse = request.handleError?.(response.status);
      if (errorResponse) {
        return {
          raw: response.statusText,
          parsed: errorResponse,
        };
      }

      const message = (await response.text()) || response.statusText;
      throw new Error(`API Error ${response.status}: ${message}`);
    }

    const text = await response.text();
    const parse = request.parse || asyncJsonParse;
    return {
      parsed: (await parse(text)) as T,
      raw: text,
    };
  }

  async function api(
    method: HttpMethod,
    path: string,
    headers?: Record<string, string>,
    body?: string,
  ): Promise<{ parsed: any; raw: string }> {
    const url = buildApiUrl(path);

    const requestHeaders: HeadersInit = {
      Accept: "application/json",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
      ...headers,
    };
    if (body) {
      requestHeaders["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (response.ok) {
      const text = await response.text();
      return {
        parsed: await asyncJsonParse(text),
        raw: text,
      };
    }

    const message = (await response.text()) || response.statusText;
    throw new Error(`HTTP ${response.status}: ${message}`);
  }

  async function apiBytes(
    method: HttpMethod,
    path: string,
  ): Promise<Uint8Array> {
    const url = buildApiUrl(path);

    const headers: HeadersInit = {
      Accept: "application/octet-stream",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
    };

    const response = await fetch(url, {
      method,
      headers,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (!response.ok) {
      const message = (await response.text()) || response.statusText;
      throw new Error(`HTTP ${response.status}: ${message}`);
    }

    const buffer = await response.arrayBuffer();
    return new Uint8Array(buffer);
  }

  return {
    fetchString: api,
    fetchBytes: apiBytes,
    fetchType: apiRequest,
  };
}

async function open_log_file(): Promise<void> {}

const clientEvents = (fetchApi: ServerFetchAPI) => async () => {
  const params = new URLSearchParams();
  params.append("loaded_time", String(LOADED_TIME.valueOf()));
  params.append("last_eval_time", String(lastEvalTime.valueOf()));
  const result = await fetchApi.fetchString(
    "GET",
    `/events?${params.toString()}`,
  );
  return result.parsed;
};

const evalLogs = (fetchApi: ServerFetchAPI, log_dir?: string) => async () => {
  const path = log_dir
    ? `/logs?log_dir=${encodeURIComponent(log_dir)}`
    : "/logs";
  const logs = await fetchApi.fetchString("GET", path);
  lastEvalTime = Date.now();
  return logs.parsed;
};

const evalLog =
  (fetchApi: ServerFetchAPI) =>
  async (
    file: string,
    headerOnly?: number,
    _capabilities?: Capabilities,
  ): Promise<LogContents> => {
    const result = await fetchApi.fetchString(
      "GET",
      `/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`,
    );
    return result;
  };

const evalLogSize =
  (fetchApi: ServerFetchAPI) =>
  async (file: string): Promise<number> => {
    const result = await fetchApi.fetchString(
      "GET",
      `/log-size/${encodeURIComponent(file)}`,
    );
    return result.parsed;
  };

const evalLogBytes =
  (fetchApi: ServerFetchAPI) =>
  async (file: string, start: number, end: number): Promise<Uint8Array> =>
    fetchApi.fetchBytes(
      "GET",
      `/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`,
    );

const evalLogOverviews =
  (fetchApi: ServerFetchAPI) => async (files: string[]) => {
    const params = new URLSearchParams();
    for (const file of files) {
      params.append("file", file);
    }
    const result = await fetchApi.fetchString(
      "GET",
      `/log-headers?${params.toString()}`,
    );
    return result.parsed;
  };

const logMessage =
  (fetchApi: ServerFetchAPI) =>
  async (log_file: string, message: string): Promise<void> => {
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
  };

const evalPendingSamples =
  (fetchApi: ServerFetchAPI) =>
  async (log_file: string, etag?: string): Promise<PendingSampleResponse> => {
    const params = new URLSearchParams();
    params.append("log", log_file);

    const headers: Record<string, string> = {};
    if (etag) {
      headers["If-None-Match"] = etag;
    }

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

    const result = await fetchApi.fetchType<PendingSampleResponse>(
      "GET",
      `/pending-samples?${params.toString()}`,
      request,
    );

    return result.parsed;
  };

const evalLogSampleData =
  (fetchApi: ServerFetchAPI) =>
  async (
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

    const request: Request<SampleDataResponse> = {
      headers: {},
      parse: async (text: string) => {
        const sampleData = await asyncJsonParse(text);
        return {
          status: "OK",
          sampleData,
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

    const result = await fetchApi.fetchType<SampleDataResponse>(
      "GET",
      `/pending-sample-data?${params.toString()}`,
      request,
    );

    return result.parsed;
  };

/**
 * Create a view server API with optional server-side log listing
 */
export function createViewServerApi(
  options: { log_dir?: string; apiBaseUrl?: string } = {},
): LogViewAPI {
  const { log_dir } = options;

  const fetchApi = createServerFetchApi(options.apiBaseUrl);

  return {
    client_events: clientEvents(fetchApi),
    eval_logs: evalLogs(fetchApi, log_dir),
    eval_log: evalLog(fetchApi),
    eval_log_size: evalLogSize(fetchApi),
    eval_log_bytes: evalLogBytes(fetchApi),
    eval_log_overviews: evalLogOverviews(fetchApi),
    log_message: logMessage(fetchApi),
    download_file,
    open_log_file,
    eval_pending_samples: evalPendingSamples(fetchApi),
    eval_log_sample_data: evalLogSampleData(fetchApi),
  };
}
