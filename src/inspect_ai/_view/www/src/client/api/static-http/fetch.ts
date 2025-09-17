import { EvalLog } from "../../../@types/log";
import { asyncJsonParse } from "../../../utils/json-worker";
import { encodePathParts } from "../../../utils/uri";
import { LogContents, LogFilesFetchResponse } from "../types";

/**
 * Fetches a file from the specified URL and parses its content.
 */
export async function fetchFile<T>(
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
export const fetchLogFile = async (
  file: string,
): Promise<LogContents | undefined> => {
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
export const fetchManifest = async (
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
 * Fetches a file, parsing its content and returning the result.
 */
export const fetchJsonFile = async <T>(
  file: string,
): Promise<T | undefined> => {
  return fetchFile<T>(file, async (text) => {
    return (await asyncJsonParse(text)) as T;
  });
};

/**
 * Joins multiple URI segments into a single URI string.
 *
 * This function removes any leading or trailing slashes from each segment
 * and then joins them with a single slash (`/`).
 */
export function joinURI(...segments: string[]): string {
  return segments
    .map((segment) => segment.replace(/(^\/+|\/+$)/g, "")) // Remove leading/trailing slashes from each segment
    .join("/");
}
