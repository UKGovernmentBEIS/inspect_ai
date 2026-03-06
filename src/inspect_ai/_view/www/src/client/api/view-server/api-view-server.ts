import { Scores } from "../../../@types/log";
import { asyncJsonParse } from "../../../utils/json-worker";
import { download_file } from "../shared/api-shared";
import {
  Capabilities,
  EvalHeader,
  LogContents,
  LogPreview,
  LogViewAPI,
  PendingSampleResponse,
  PendingSamples,
  SampleData,
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

  const get_log_dir = async () => {
    if (logDir) {
      return logDir;
    }
    const obj = (await requestApi.fetchString("GET", "/log-dir")).parsed;
    return obj.log_dir as string | undefined;
  };

  const get_log_root = async () => {
    const path = logDir
      ? `/logs?log_dir=${encodeURIComponent(logDir)}`
      : "/logs";
    const logs = await requestApi.fetchString("GET", path);

    // Note the last request time so we can get events
    // since the last request
    lastEvalTime = Date.now();
    return logs.parsed;
  };

  const get_logs = async (mtime: number, clientFileCount: number) => {
    const path = logDir
      ? `/log-files?log_dir=${encodeURIComponent(logDir)}`
      : "/log-files";

    const headers: Record<string, string> = {};
    const token = log_file_token(mtime, clientFileCount);
    if (token) {
      headers["If-None-Match"] = token;
    }

    // Note the last request time so we can get events
    // since the last request
    lastEvalTime = Date.now();

    const envelope = await requestApi.fetchString("GET", path, headers);
    return envelope.parsed;
  };

  const log_file_token = (mtime: number, fileCount: number) => {
    // Use a weak etag as the mtime and file count may not
    // uniquely identify the state of the log directory
    return `W/"${mtime}-${fileCount}"`;
  };

  const get_eval_set = async (dir?: string) => {
    const basePath = "/eval-set";
    const params = new URLSearchParams();
    if (logDir) {
      params.append("log_dir", logDir);
    }
    if (dir) {
      params.append("dir", dir);
    }
    const query = params.toString();
    const path = query ? `${basePath}?${query}` : basePath;

    try {
      const result = await requestApi.fetchString("GET", path);
      return result.parsed;
    } catch (error) {
      // if the eval set is not found, no biggee as not all
      // log directories will have an eval set.
      if (
        error instanceof ApiError &&
        (error.status === 404 || error.status === 403)
      ) {
        return undefined;
      }
      throw error;
    }
  };

  const get_flow = async (dir?: string) => {
    const basePath = "/flow";
    const params = new URLSearchParams();
    if (logDir) {
      params.append("log_dir", logDir);
    }
    if (dir) {
      params.append("dir", dir);
    }
    const query = params.toString();
    const path = query ? `${basePath}?${query}` : basePath;

    try {
      const bytes = await requestApi.fetchBytes("GET", path);
      return new TextDecoder().decode(bytes);
    } catch (error) {
      // if the eval set is not found, no biggee as not all
      // log directories will have an eval set.
      if (
        error instanceof ApiError &&
        (error.status === 404 || error.status === 403)
      ) {
        return undefined;
      }
      throw error;
    }
  };

  const get_log_contents = async (
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

  const get_log_size = async (file: string): Promise<number> => {
    const result = await requestApi.fetchString(
      "GET",
      `/log-size/${encodeURIComponent(file)}`,
    );
    return result.parsed;
  };

  const toLogPreview = (header: EvalHeader): LogPreview => {
    const scores: Scores = Object.values(header.results?.scores || {});
    const metric = scores.length > 0 ? scores[0].metrics : undefined;
    const evalMetrics = Object.values(metric || {});
    const primary_metric = evalMetrics.length > 0 ? evalMetrics[0] : undefined;

    return {
      eval_id: header.eval.eval_id,
      run_id: header.eval.run_id,

      task: header.eval.task,
      task_id: header.eval.task_id,
      task_version: header.eval.task_version,

      version: header.version,
      status: header.status,
      error: header.error,

      model: header.eval.model,

      started_at: header.stats?.started_at,
      completed_at: header.stats?.completed_at,

      primary_metric,
    };
  };

  const get_log_bytes = async (
    file: string,
    start: number,
    end: number,
  ): Promise<Uint8Array> =>
    requestApi.fetchBytes(
      "GET",
      `/log-bytes/${encodeURIComponent(file)}?start=${start}&end=${end}`,
    );

  const get_log_summaries = async (files: string[]) => {
    const params = new URLSearchParams();
    for (const file of files) {
      params.append("file", file);
    }
    const result = await requestApi.fetchString(
      "GET",
      `/log-headers?${params.toString()}`,
    );
    const logHeaders: EvalHeader[] = result.parsed;
    return logHeaders.map(toLogPreview);
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
        const pendingSamples = await asyncJsonParse<PendingSamples | undefined>(
          text,
        );
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
        const sampleData = await asyncJsonParse<SampleData | undefined>(text);
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

  const download_log = async (log_file: string): Promise<void> => {
    const baseUrl = apiBaseUrl || __VIEW_SERVER_API_URL__;
    const url = `${baseUrl}/log-download/${encodeURIComponent(log_file)}`;

    const link = document.createElement("a");
    link.href = url;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return {
    client_events,
    get_log_root,
    get_logs,
    get_log_dir,
    get_eval_set,
    get_flow,
    get_log_contents,
    get_log_size,
    get_log_bytes,
    get_log_summaries,
    log_message,
    download_file,
    download_log,
    open_log_file: async () => {},
    eval_pending_samples,
    eval_log_sample_data,
  };
}
