import { EvalSet } from "../../../@types/log";
import { fetchRange, fetchSize } from "../../remote/remoteZipFile";
import { download_file } from "../shared/api-shared";
import { Capabilities, LogPreview, LogRoot, LogViewAPI } from "../types";
import {
  fetchJsonFile,
  fetchLogFile,
  fetchManifest,
  fetchTextFile,
  joinURI,
} from "./fetch";

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 */
export default function staticHttpApi(
  log_dir?: string,
  log_file?: string,
): LogViewAPI {
  const resolved_log_dir = log_dir?.replace(" ", "+");
  const resolved_log_path = log_file ? log_file.replace(" ", "+") : undefined;
  return staticHttpApiForLog({
    log_file: resolved_log_path,
    log_dir: resolved_log_dir,
  });
}

/**
 * Fetches a file from the specified URL and parses its content.
 */
function staticHttpApiForLog(logInfo: {
  log_dir?: string;
  log_file?: string;
}): LogViewAPI {
  const log_dir = logInfo.log_dir;
  let manifest: Record<string, LogPreview> | undefined = undefined;
  let manifestPromise: Promise<Record<string, LogPreview>> | undefined =
    undefined;

  const getManifest = async (): Promise<Record<string, LogPreview>> => {
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
    get_log_root: async (): Promise<LogRoot | undefined> => {
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
            logs: logs,
            log_dir,
          });
        }
      }

      return undefined;
    },
    get_eval_set: async (dir?: string) => {
      const dirSegments = [];
      if (log_dir) {
        dirSegments.push(log_dir);
      }
      if (dir) {
        dirSegments.push(dir);
      }

      return await fetchJsonFile<EvalSet>(
        joinURI(...dirSegments, "eval-set.json"),
        (response) => {
          if (400 <= response.status && response.status < 500) {
            // Couldn't find a header file
            return true;
          } else {
            return false;
          }
        },
      );
    },
    get_flow: async (dir?: string) => {
      const dirSegments = [];
      if (log_dir) {
        dirSegments.push(log_dir);
      }
      if (dir) {
        dirSegments.push(dir);
      }

      return await fetchTextFile(
        joinURI(...dirSegments, "flow.yaml"),
        (response) => {
          if (400 <= response.status && response.status < 500) {
            // Couldn't find a flow file
            return true;
          } else {
            return false;
          }
        },
      );
    },
    log_message: async (log_file: string, message: string) => {
      console.log(`[CLIENT MESSAGE] (${log_file}): ${message}`);
    },
    get_log_contents: async (
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
    get_log_size: async (log_file: string) => {
      return await fetchSize(log_file);
    },
    get_log_bytes: async (log_file: string, start: number, end: number) => {
      return await fetchRange(log_file, start, end);
    },
    get_log_summary: async (log_file: string) => {
      const manifest = await getManifest();
      if (manifest) {
        const manifestAbs: Record<string, LogPreview> = {};
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
    get_log_summaries: async (files: string[]) => {
      if (files.length === 0) {
        return [];
      }

      if (log_dir) {
        const manifest = await getManifest();
        if (manifest) {
          const keys = Object.keys(manifest);
          const result: LogPreview[] = [];
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
