import { asyncJsonParse } from "../../../utils/json-worker";
import { download_file } from "../shared/api-shared";
import {
  Capabilities,
  LogContents,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "../types";
import { ApiError, HeaderProvider, Request, serverRequestApi } from "./request";

// The time that the view was initially loaded
const LOADED_TIME = Date.now();

// The time we fetched logs (used for finding client events since last fetch)
let lastEvalTime = 0;

/**
 * Create a view server API with optional server-side log listing
 */
export function viewServerApi(
  options: {
    logDir?: string;
    apiBaseUrl?: string;
    headerProvider?: HeaderProvider;
  } = {},
): LogViewAPI {
  const { apiBaseUrl, logDir, headerProvider } = options;

  const requestApi = serverRequestApi(
    apiBaseUrl || __VIEW_SERVER_API_URL__,
    headerProvider,
  );

  const client_events = async () => {
    const params = new URLSearchParams();
    params.append("loaded_time", String(LOADED_TIME.valueOf()));
    params.append("last_eval_time", String(lastEvalTime.valueOf()));
    const result = await requestApi.fetchString(
      "GET",
      `/events?${params.toString()}`,
    );
    return result.parsed;
  };

  const eval_logs = async () => {
    const path = logDir
      ? `/logs?log_dir=${encodeURIComponent(logDir)}`
      : "/logs";
    const logs = await requestApi.fetchString("GET", path);

    // Note the last request time so we can get events
    // since the last request
    lastEvalTime = Date.now();
    return logs.parsed;
  };

  const eval_set = async (dir?: string) => {
    if (logDir) dir ??= logDir;
    const path = dir ? `/eval-set?dir=${encodeURIComponent(dir)}` : "/eval-set";
    try {
      const result = await requestApi.fetchString("GET", path);
      return result.parsed;
    } catch (error) {
      // if the eval set is not found, no biggee as not all
      // log directories will have an eval set.
      if (error instanceof ApiError && error.status === 404) {
        return undefined;
      }
      throw error;
    }
  };

  const eval_log = async (
    file: string,
    headerOnly?: number,
    _capabilities?: Capabilities,
  ): Promise<LogContents> => {
    const result = await requestApi.fetchString(
      "GET",
      `/logs/${encodeURIComponent(file)}?header-only=${headerOnly}`,
    );
    return result;
  };

  const eval_log_size = async (file: string): Promise<number> => {
    const result = await requestApi.fetchString(
      "GET",
      `/log-size/${encodeURIComponent(file)}`,
    );
    return result.parsed;
  };

  const eval_log_bytes = async (
    file: string,
    start: number,
    end: number,
  ): Promise<Uint8Array> =>
    requestApi.fetchBytes(
      "GET",
      `/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`,
    );

  const eval_log_overviews = async (files: string[]) => {
    const params = new URLSearchParams();
    for (const file of files) {
      params.append("file", file);
    }
    const result = await requestApi.fetchString(
      "GET",
      `/log-headers?${params.toString()}`,
    );
    return result.parsed;
  };

  const log_message = async (
    log_file: string,
    message: string,
  ): Promise<void> => {
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
    await requestApi.fetchType<void>(
      "GET",
      `/log-message?${params.toString()}`,
      request,
    );
  };

  const eval_pending_samples = async (
    log_file: string,
    etag?: string,
  ): Promise<PendingSampleResponse> => {
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

    const result = await requestApi.fetchType<PendingSampleResponse>(
      "GET",
      `/pending-samples?${params.toString()}`,
      request,
    );

    return result.parsed;
  };

  const eval_log_sample_data = async (
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

    const result = await requestApi.fetchType<SampleDataResponse>(
      "GET",
      `/pending-sample-data?${params.toString()}`,
      request,
    );

    return result.parsed;
  };

  return {
    client_events,
    eval_logs,
    eval_set,
    eval_log,
    eval_log_size,
    eval_log_bytes,
    eval_log_overviews,
    log_message,
    download_file,
    open_log_file: async () => {},
    eval_pending_samples,
    eval_log_sample_data,
  };
}
