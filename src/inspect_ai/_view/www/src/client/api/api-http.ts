import { EvalLog } from "../../@types/log";
import { asyncJsonParse } from "../../utils/json-worker";
import { encodePathParts } from "../../utils/uri";
import { fetchRange, fetchSize } from "../remote/remoteZipFile";
import { download_file } from "./api-shared";
import {
  Capabilities,
  LogContents,
  LogFiles,
  LogFilesFetchResponse,
  LogOverview,
  LogViewAPI,
} from "./types";

interface LogInfo {
  log_dir?: string;
  log_file?: string;
}

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 */
export default function simpleHttpApi(
  log_dir?: string,
  log_file?: string,
): LogViewAPI {
  const resolved_log_dir = log_dir?.replace(" ", "+");
  const resolved_log_path = log_file ? log_file.replace(" ", "+") : undefined;
  return simpleHttpAPI({
    log_file: resolved_log_path,
    log_dir: resolved_log_dir,
  });
}

/**
 * Fetches a file from the specified URL and parses its content.
 */
function simpleHttpAPI(logInfo: LogInfo): LogViewAPI {
  const log_dir = logInfo.log_dir;
  let manifest: Record<string, LogOverview> | undefined = undefined;
  let manifestPromise: Promise<Record<string, LogOverview>> | undefined =
    undefined;

  const getManifest = async (): Promise<Record<string, LogOverview>> => {
    if (!manifest && log_dir) {
      if (!manifestPromise) {
        manifestPromise = fetchManifest(log_dir).then((manifestRaw) => {
          manifest = manifestRaw?.parsed || {};
          return manifest;
        });
      }
      await manifestPromise;
    }
    return manifest || {};
  };

  async function open_log_file() {
    // No op
  }
  return {
    client_events: async () => {
      // There are no client events in the case of serving via
      // http
      return Promise.resolve([]);
    },
    eval_logs: async (): Promise<LogFiles | undefined> => {
      // First check based upon the log dir
      if (log_dir) {
        const manifest = await getManifest();
        if (manifest) {
          const logs = Object.keys(manifest).map((key) => {
            return {
              name: joinURI(log_dir, key),
              task: manifest[key].task,
              task_id: manifest[key].task_id,
            };
          });
          return Promise.resolve({
            files: logs,
            log_dir,
          });
        }
      }

      return undefined;
    },
    log_message: async (log_file: string, message: string) => {
      console.log(`[CLIENT MESSAGE] (${log_file}): ${message}`);
    },
    eval_log: async (
      log_file: string,
      _headerOnly?: number,
      _capabilities?: Capabilities,
    ) => {
      const response = await fetchLogFile(log_file);
      if (response) {
        return response;
      } else {
        throw new Error(`"Unable to load eval log ${log_file}`);
      }
    },
    eval_log_size: async (log_file: string) => {
      return await fetchSize(log_file);
    },
    eval_log_bytes: async (log_file: string, start: number, end: number) => {
      return await fetchRange(log_file, start, end);
    },
    eval_log_overview: async (log_file: string) => {
      const manifest = await getManifest();
      if (manifest) {
        const manifestAbs: Record<string, LogOverview> = {};
        Object.keys(manifest).forEach((key) => {
          manifestAbs[joinURI(log_dir || "", key)] = manifest[key];
        });
        const header = manifestAbs[log_file];
        if (header) {
          return header;
        }
      }
      throw new Error(`Unable to load eval log header for ${log_file}`);
    },
    eval_log_overviews: async (files: string[]) => {
      if (files.length === 0) {
        return [];
      }

      if (log_dir) {
        const manifest = await getManifest();
        if (manifest) {
          const keys = Object.keys(manifest);
          const result: LogOverview[] = [];
          files.forEach((file) => {
            const fileKey = keys.find((key) => {
              return file.endsWith(key);
            });
            if (fileKey) {
              result.push(manifest[fileKey]);
            }
          });
          return result;
        }
      }

      // No log.json could be found, and there isn't a log file,
      throw new Error(
        `Failed to load a listing file using the directory: ${log_dir}. Please be sure you have deployed a manifest file (listing.json).`,
      );
    },
    download_file,
    open_log_file,
  };
}

/**
 * Fetches a file from the specified URL and parses its content.
 */
async function fetchFile<T>(
  url: string,
  parse: (text: string) => Promise<T>,
  handleError?: (response: Response) => boolean,
): Promise<T | undefined> {
  const safe_url = encodePathParts(url);
  const response = await fetch(`${safe_url}`, { method: "GET" });
  if (response.ok) {
    const text = await response.text();
    return await parse(text);
  } else if (response.status !== 200) {
    if (handleError && handleError(response)) {
      return undefined;
    }
    const message = (await response.text()) || response.statusText;
    const error = new Error(`${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

/**
 * Fetches a log file and parses its content, updating the log structure if necessary.
 */
const fetchLogFile = async (file: string): Promise<LogContents | undefined> => {
  return fetchFile<LogContents>(file, async (text): Promise<LogContents> => {
    const log = (await asyncJsonParse(text)) as EvalLog;
    if (log.version === 1) {
      if (log.results) {
        const untypedLog = log as any;
        log.results.scores = [];
        untypedLog.results.scorer.scorer = untypedLog.results.scorer.name;
        log.results.scores.push(untypedLog.results.scorer);
        delete untypedLog.results.scorer;
        log.results.scores[0].metrics = untypedLog.results.metrics;
        delete untypedLog.results.metrics;

        // migrate samples
        const scorerName = log.results.scores[0].name;
        log.samples?.forEach((sample) => {
          const untypedSample = sample as any;
          sample.scores = { [scorerName]: untypedSample.score };
          delete untypedSample.score;
        });
      }
    }
    return {
      raw: text,
      parsed: log,
    };
  });
};

/**
 * Fetches a log file and parses its content, updating the log structure if necessary.
 */
const fetchManifest = async (
  log_dir: string,
): Promise<LogFilesFetchResponse | undefined> => {
  const logs = await fetchFile<LogFilesFetchResponse>(
    log_dir + "/listing.json",
    async (text) => {
      const parsed = await asyncJsonParse(text);
      return {
        raw: text,
        parsed,
      };
    },
    (response) => {
      if (response.status === 404) {
        // Couldn't find a header file
        return true;
      } else {
        return false;
      }
    },
  );
  return logs;
};

/**
 * Joins multiple URI segments into a single URI string.
 *
 * This function removes any leading or trailing slashes from each segment
 * and then joins them with a single slash (`/`).
 */
function joinURI(...segments: string[]): string {
  return segments
    .map((segment) => segment.replace(/(^\/+|\/+$)/g, "")) // Remove leading/trailing slashes from each segment
    .join("/");
}
