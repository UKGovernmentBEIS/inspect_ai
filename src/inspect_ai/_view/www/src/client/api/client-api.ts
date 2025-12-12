import { EvalSample } from "../../@types/log";
import { sampleIdsEqual } from "../../app/shared/sample";
import { encodePathParts } from "../../utils/uri";
import {
  openRemoteLogFile,
  RemoteLogFile,
  SampleNotFoundError,
} from "../remote/remoteLogFile";
import { FileSizeLimitError } from "../remote/remoteZipFile";
import {
  ClientAPI,
  LogContents,
  LogDetails,
  LogFilesResponse,
  LogPreview,
  LogRoot,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

const isEvalFile = (file: string) => {
  return file.endsWith(".eval");
};

/**
 * Represents an error thrown when a file exceeds the maximum allowed size.
 */
export class SampleSizeLimitedExceededError extends Error {
  readonly id: string | number;
  readonly epoch: number;
  readonly maxBytes: number;
  readonly displayStack: boolean;

  constructor(id: string | number, epoch: number, maxBytes: number) {
    super(
      `Sample ${id} in epoch ${epoch} exceeds the maximum supported size (${maxBytes / 1024 / 1024}MB) and cannot be loaded.`,
    );

    this.name = "SampleSizeLimitedExceededError";
    this.id = id;
    this.epoch = epoch;
    this.maxBytes = maxBytes;
    this.displayStack = false;

    Object.setPrototypeOf(this, SampleSizeLimitedExceededError.prototype);
  }
}

interface LoadedLogFile {
  file?: string;
  remoteLog?: RemoteLogFile;
}

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 */
export const clientApi = (
  api: LogViewAPI,
  log_file?: string,
  debug = false,
): ClientAPI => {
  let current_log: LogContents | undefined = undefined;
  let current_path: string | undefined = undefined;

  const loadedEvalFile: LoadedLogFile = {
    file: undefined,
    remoteLog: undefined,
  };

  const remoteEvalFile = async (log_file: string, cached: boolean = false) => {
    if (cached && loadedEvalFile.file === log_file) {
      return loadedEvalFile.remoteLog;
    }

    const remoteLog = await openRemoteLogFile(
      api,
      encodePathParts(log_file),
      5,
    );

    if (cached) {
      loadedEvalFile.file = log_file;
      loadedEvalFile.remoteLog = remoteLog;
    }

    return remoteLog;
  };

  /**
   * Gets a log
   */
  const get_log = async (
    log_file: string,
    cached = false,
  ): Promise<LogContents> => {
    // If the requested log is different or no cached log exists, start fetching
    if (!cached || log_file !== current_path || !current_log) {
      // If there's already a pending fetch, return the same promise
      if (pending_log_promise) {
        return pending_log_promise;
      }

      // Otherwise, create a new promise for fetching the log
      pending_log_promise = api
        .get_log_contents(log_file, 100)
        .then((log) => {
          current_log = log;
          current_path = log_file;
          pending_log_promise = null;
          return log;
        })
        .catch((err) => {
          pending_log_promise = null;
          throw err;
        });

      return pending_log_promise;
    }
    return current_log;
  };
  let pending_log_promise: Promise<LogContents> | null = null;

  /**
   * Gets a log summary
   */
  const get_log_details = async (log_file: string): Promise<LogDetails> => {
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file);
      if (remoteLogFile) {
        return await remoteLogFile.readLogSummary();
      } else {
        throw new Error("Unable to read remote eval file");
      }
    } else {
      const logContents = await get_log(log_file);
      /**
       * @type {import("./Types.js").SampleSummary[]}
       */
      const sampleSummaries = logContents.parsed.samples
        ? logContents.parsed.samples?.map((sample) => {
            return {
              id: sample.id,
              epoch: sample.epoch,
              input: sample.input,
              target: sample.target,
              scores: sample.scores,
              metadata: sample.metadata,
              error: sample.error?.message,
            };
          })
        : [];

      const parsed = logContents.parsed;
      return {
        version: parsed.version,
        status: parsed.status,
        eval: parsed.eval,
        plan: parsed.plan,
        results: parsed.results,
        stats: parsed.stats,
        error: parsed.error,
        sampleSummaries,
      };
    }
  };

  /**
   * Gets a sample
   */
  const get_log_sample = async (
    log_file: string,
    id: string | number,
    epoch: number,
  ): Promise<EvalSample | undefined> => {
    if (isEvalFile(log_file)) {
      async function fetchSample(useCache: boolean) {
        const remoteLogFile = await remoteEvalFile(log_file, useCache);
        if (!remoteLogFile) {
          throw new Error(`Unable to read remote eval file ${log_file}`);
        }
        return await remoteLogFile.readSample(String(id), epoch);
      }

      function handleError(error: unknown) {
        if (error instanceof FileSizeLimitError) {
          throw new SampleSizeLimitedExceededError(id, epoch, error.maxBytes);
        }
        throw error;
      }

      try {
        // First attempt with cache
        return await fetchSample(true);
      } catch (error) {
        if (error instanceof SampleNotFoundError) {
          try {
            // Retry without cache
            return await fetchSample(false);
          } catch (retryError) {
            handleError(retryError);
          }
        } else {
          handleError(error);
        }
      }
    } else {
      const logContents = await get_log(log_file, true);
      if (logContents.parsed.samples && logContents.parsed.samples.length > 0) {
        return logContents.parsed.samples.find((sample) => {
          return sampleIdsEqual(sample.id, id) && sample.epoch === epoch;
        });
      }
    }
    return undefined;
  };

  const read_eval_file_log_summary = async (log_file: string) => {
    // If the API supports this, delegate to it
    if (api.get_log_summary) {
      return api.get_log_summary(log_file);
    } else {
      // Don't re-use the eval log file since we know these are all different log files
      const remoteLogFile = await openRemoteLogFile(
        api,
        encodePathParts(log_file),
        5,
      );
      return remoteLogFile.readEvalBasicInfo();
    }
  };

  /**
   * Gets log headers
   */
  const get_log_summaries = async (
    log_files: string[],
  ): Promise<LogPreview[]> => {
    const eval_files: Record<string, number> = {};
    const json_files: Record<string, number> = {};
    let index = 0;

    // Separate files into eval_files and json_files
    for (const file of log_files) {
      if (isEvalFile(file)) {
        eval_files[file] = index;
      } else {
        json_files[file] = index;
      }
      index++;
    }

    // Get the promises for eval log headers
    const evalLogHeadersPromises = Object.keys(eval_files).map((file) =>
      read_eval_file_log_summary(file).then((summary) => ({
        index: eval_files[file], // Store original index
        summary,
      })),
    );

    // Get the promise for json log headers
    const jsonLogHeadersPromise = api
      .get_log_summaries(Object.keys(json_files))
      .then((summaries) =>
        summaries.map((summary, i) => ({
          index: json_files[Object.keys(json_files)[i]], // Store original index
          summary,
        })),
      );

    // Wait for all promises to resolve
    const summaries = await Promise.all([
      ...evalLogHeadersPromises,
      jsonLogHeadersPromise,
    ]);

    // Flatten the nested array and sort headers by their original index
    const orderedSummaries = summaries.flat().sort((a, b) => a.index - b.index);

    // Return only the header values in the correct order
    return orderedSummaries.map(({ summary }) => summary);
  };

  const get_log_dir = async (): Promise<string | undefined> => {
    if (api.get_log_dir) {
      return await api.get_log_dir();
    } else {
      const logRoot = await api.get_log_root();
      return logRoot?.log_dir;
    }
  };

  const get_logs = async (
    mtime: number,
    clientFileCount: number,
  ): Promise<LogFilesResponse> => {
    if (api.get_logs) {
      const result = await api.get_logs(mtime, clientFileCount);
      return result;
    } else {
      const logRoot = await api.get_log_root();
      return {
        files: logRoot?.logs || [],
        response_type: "full",
      };
    }
  };

  const get_log_root = async (): Promise<LogRoot> => {
    const logFiles = await api.get_log_root();
    if (logFiles) {
      return logFiles!;
    } else if (log_file) {
      // Is there an explicitly passed log file?
      const summary = await get_log_details(log_file);
      if (summary) {
        return {
          logs: [
            {
              name: log_file,
              task: summary.eval.task,
              task_id: summary.eval.task_id,
            },
          ],
        };
      }
    }
    throw new Error("Unable to determine log paths.");
  };

  const get_log_pending_samples = (
    log_file: string,
    etag?: string,
  ): Promise<PendingSampleResponse> => {
    if (!api.eval_pending_samples) {
      throw new Error("API doesn't support streamed samples");
    }
    return api.eval_pending_samples(log_file, etag);
  };

  const get_log_sample_data = (
    log_file: string,
    id: string | number,
    epoch: number,
    last_event?: number,
    last_attachment?: number,
  ): Promise<SampleDataResponse | undefined> => {
    if (!api.eval_log_sample_data) {
      throw new Error("API doesn't supported streamed sample data");
    }
    return api.eval_log_sample_data(
      log_file,
      id,
      epoch,
      last_event,
      last_attachment,
    );
  };

  const middleware = debug
    ? createMiddlewareWrapper([debugMiddleware])
    : <T extends (...args: any[]) => any>(_name: string, fn: T): T => fn;

  return {
    client_events: middleware("client_events", () => {
      return api.client_events();
    }),
    get_log_dir: middleware("get_log_dir", get_log_dir),
    get_logs: middleware("get_log_files", get_logs),
    get_log_root: middleware("get_log_root", get_log_root),
    get_eval_set: middleware("get_eval_set", (dir?: string) => {
      return api.get_eval_set(dir);
    }),
    get_flow: middleware("get_flow", (dir?: string) => {
      return api.get_flow(dir);
    }),
    get_log_summaries: middleware("get_log_summaries", get_log_summaries),
    get_log_details: middleware("get_log_details", get_log_details),
    get_log_sample: middleware("get_log_sample", get_log_sample),
    open_log_file: middleware("open_log_file", (log_file, log_dir) => {
      return api.open_log_file(log_file, log_dir);
    }),
    download_file: middleware(
      "download_file",
      (
        download_file: string,
        file_contents:
          | string
          | Blob
          | ArrayBuffer
          | ArrayBufferView<ArrayBuffer>,
      ) => {
        return api.download_file(download_file, file_contents);
      },
    ),
    download_log: api.download_log
      ? middleware("download_log", (log_file: string) => {
          return api.download_log!(log_file);
        })
      : undefined,
    log_message: middleware(
      "log_message",
      (log_file: string, message: string) => {
        return api.log_message(log_file, message);
      },
    ),
    get_log_pending_samples: api.eval_pending_samples
      ? middleware("get_log_pending_samples", get_log_pending_samples)
      : undefined,
    get_log_sample_data: api.eval_log_sample_data
      ? middleware("get_log_sample_data", get_log_sample_data)
      : undefined,
  };
};

type Middleware<T extends (...args: any[]) => any> = (
  name: string,
  fn: T,
  args: Parameters<T>,
  result: ReturnType<T>,
) => ReturnType<T>;

const debugMiddleware: Middleware<any> = (name, _fn, args, result) => {
  if (result instanceof Promise) {
    const startTime = performance.now();
    return result.then((returned) => {
      const duration = performance.now() - startTime;
      console.log(`[ClientAPI] ${name}`, {
        args,
        returned,
        duration: `${duration.toFixed(2)}ms`,
      });
      return returned;
    });
  } else {
    console.log(`[ClientAPI] ${name}`, { args, returned: result });
    return result;
  }
};

const applyMiddleware = <T extends (...args: any[]) => any>(
  name: string,
  fn: T,
  middlewares: Middleware<T>[],
): T => {
  if (middlewares.length === 0) return fn;

  return ((...args: Parameters<T>) => {
    let result = fn(...args);

    for (const middleware of middlewares) {
      result = middleware(name, fn, args, result);
    }

    return result;
  }) as T;
};

const createMiddlewareWrapper = (middlewares: Middleware<any>[]) => {
  return <T extends (...args: any[]) => any>(name: string, fn: T): T => {
    return applyMiddleware(name, fn, middlewares);
  };
};
