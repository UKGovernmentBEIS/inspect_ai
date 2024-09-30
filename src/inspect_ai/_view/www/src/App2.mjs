import "bootstrap/dist/css/bootstrap.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "prismjs/themes/prism.css";
import "prismjs";
import "../App.css";
import { sleep } from "./utils/sync.mjs";

import { chunkArray } from "./utils/Array.mjs";
import { html } from "htm/preact";
import { useEffect, useState } from "preact/hooks";

import { ProgressBar } from "./components/ProgressBar.mjs";
import { EvalList } from "./eval-list/EvalList.mjs";
import { ErrorPanel } from "./components/ErrorPanel.mjs";
import { AppErrorBoundary } from "./components/AppErrorBoundary.mjs";
import { FontSize } from "./appearance/Fonts.mjs";
import { ApplicationIcons } from "./appearance/Icons.mjs";

// Registration component
import "./Register.mjs";

/**
 * Renders the App.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("./api/Types.mjs").LogViewAPI} props.api - The id of this event.
 * @param {boolean} props.pollForLogs - Whether to poll for logs
 * @returns {import("preact").JSX.Element} The component.
 */
export function App2({ api }) {
  const [logs, setLogs] = useState(
    /** @type LogFiles */ { log_dir: "", files: [] },
  );
  const [logHeaders, setLogHeaders] = useState(
    /** @type {Record<string, EvalLog>} */ {},
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(undefined);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        // Load log files
        const logFiles = await api.eval_logs();
        setLogs(logFiles);

        // Load the headers in chunks
        const chunkSize = 8;
        const fetchInterval = 2000;
        const chunks = chunkArray(logFiles.files, chunkSize);
        const loaded_headers = {};
        for (const chunk of chunks) {
          const fileNames = chunk.map((c) => {
            return c.name;
          });
          const headers = await api.eval_log_headers(fileNames);
          headers.forEach((header, index) => {
            const logName = fileNames[index];
            loaded_headers[logName] = header;
          });
          setLogHeaders({ ...loaded_headers });
          if (headers.length === chunkSize) {
            await sleep(
              api.header_fetch_interval !== undefined
                ? api.header_fetch_interval
                : fetchInterval,
            );
          }
        }
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  /**
   * @param {import("./types/log").EvalLog} log - The log object passed to the callback.
   */
  const onShowLog = (log) => {
    window.alert(log.eval.task);
  };

  return html`
    <${AppErrorBoundary}>
        <${ProgressBar} animating=${loading}  containerStyle=${{
          background: "var(--bs-light)",
          marginBottom: "-1px",
        }}/>
        <div style=${{ height: "100vh" }}>
        
        ${
          error !== undefined
            ? html` <${ErrorPanel}
                title="An error occurred while loading this task."
                error=${error}
              />`
            : ""
        }

        ${
          error === undefined
            ? html` <div
                  style=${{
                    fontSize: FontSize.small,
                    fontWeight: 600,
                    padding: "0.5em",
                    background: "var(--bs-light-bg-subtle)",
                    borderBottom: "solid 1px var(--bs-light-border-subtle)",
                  }}
                >
                  <i class=${ApplicationIcons.folder} /> ${logs.log_dir}
                </div>
                <${EvalList}
                  logs=${logs}
                  logHeaders=${logHeaders}
                  selectedIndex=${selectedIndex}
                  onSelectedIndex=${setSelectedIndex}
                  onShowLog=${onShowLog}
                  style=${{ height: "100%", width: "100%" }}
                />`
            : ""
        }
        </div>
    </${AppErrorBoundary}>`;
}
