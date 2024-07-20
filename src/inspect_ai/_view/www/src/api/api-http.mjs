import { asyncJsonParse } from "../utils/Json.mjs";
import { download_file } from "./api-shared.mjs";

// This provides an API implementation that will serve a single
// file using an http parameter, designed to be deployed
// to a webserver without inspect or the ability to enumerate log
// files
export default function singleFileHttpApi() {
  const urlParams = new URLSearchParams(window.location.search);
  const fetchLogPath = urlParams.get("log_file");
  if (fetchLogPath) {
    const api = httpApiForFile(fetchLogPath);
    return api;
  }
}

function httpApiForFile(logFile) {
  let contents;
  const getContents = async () => {
    if (contents) {
      return contents;
    } else {
      const response = await fetch(`${logFile}`, { method: "GET" });
      if (response.ok) {
        const text = await response.text();

        const log = await asyncJsonParse(text);
        if (log.version === 1) {
          // Update log structure to v2 format
          if (log.results) {
            log.results.scores = [];
            log.results.scorer.scorer = log.results.scorer.name;
            log.results.scores.push(log.results.scorer);
            delete log.results.scorer;
            log.results.scores[0].metrics = log.results.metrics;
            delete log.results.metrics;

            // migrate samples
            const scorerName = log.results.scores[0].name;
            log.samples.forEach((sample) => {
              sample.scores = { [scorerName]: sample.score };
              delete sample.score;
            });
          }
        }

        return {
          parsed: log,
          raw: text,
        };
      } else if (response.status !== 200) {
        const message = (await response.text()) || response.statusText;
        const error = new Error(`Error: ${response.status}: ${message})`);
        throw error;
      } else {
        throw new Error(`${response.status} - ${response.statusText} `);
      }
    }
  };

  return {
    client_events: async () => {
      return Promise.resolve([]);
    },
    eval_logs: async () => {
      const contents = await getContents();
      const files = [
        {
          name: logFile,
          task: contents.parsed.eval.task,
          task_id: contents.parsed.eval.task_id,
        },
      ];
      return Promise.resolve({
        files,
      });
    },
    eval_log: async () => {
      return await getContents();
    },
    eval_log_headers: async () => {
      const contents = await getContents();
      return Promise.resolve([contents.parsed]);
    },
    download_file,
  };
}
