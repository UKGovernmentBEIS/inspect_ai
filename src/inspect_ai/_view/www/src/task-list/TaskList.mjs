//@ts-check
import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";

import { ListView } from "../components/ListView.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { formatPrettyDecimal } from "../utils/Format.mjs";

const kRowHeight = 65;

/**
 * Renders the ToolCallView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param { import("../api/Types.mjs").LogFiles } props.logs - The logs to display in the list
 * @param { Record<string, import("../types/log").EvalLog> } props.logHeaders - The log headers that contains status of the logs
 * @param { number } props.selectedIndex - Styles to apply to this compoenent
 * @param { (index: number) => void } props.onSelectedIndex - Styles to apply to this component
 * @param { (log: import("../types/log").EvalLog) => void} props.onShowLog - Fired when log should be shown
 * @param { Record<string, string>} props.style - Styles to apply to this component
 *
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const TaskList = ({
  logs,
  logHeaders,
  selectedIndex,
  onSelectedIndex,
  onShowLog,
  style,
}) => {
  const listRef = useRef();

  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };

  /**
   * Build the list of visible logs (logs we have header data for)
   *
   * @type {[import("../types/log").EvalLog[], (logs: import("../types/log").EvalLog[]) => void]}
   */
  const [visibleLogs, setVisibleLogs] = useState([]);
  useEffect(() => {
    const visible = [];
    for (const log of logs.files) {
      const headers = logHeaders[log.name];
      if (headers) {
        visible.push(headers);
      }
    }
    setVisibleLogs(visible);
  }, [logs, logHeaders]);

  /**
   * Build the list of visible logs (logs we have header data for)
   *
   * @type {[import("../components/ListView.mjs").Row<import("../types/log").EvalLog>[], (rows: import("../components/ListView.mjs").Row<import("../types/log").EvalLog>[]) => void]}
   */
  const [rows, setRows] = useState([]);
  useEffect(() => {
    setRows(
      visibleLogs.map((visibleLog, index) => {
        return {
          item: visibleLog,
          height: kRowHeight,
          index,
        };
      }),
    );
  }, [visibleLogs]);

  /**
   * Renders a row based on the item and index.
   *
   * @param {import("../types/log").EvalConfig} config - The evaluation configuration
   * @param {import("../types/log").TaskArgs} taskArgs - The evaluation task arguments
   * @returns {string} A string representation of the configuration
   */
  const configStr = (config, taskArgs) => {
    const hyperparameters = {
      ...config,
      ...taskArgs,
    };
    return Object.keys(hyperparameters)
      .map((param) => {
        return `${param}=${hyperparameters[param]}`;
      })
      .join(", ");
  };

  /**
   * Renders a row based on the item and index.
   *
   * @param {import("../components/ListView.mjs").Row<import("../types/log").EvalLog>} row - The row to render
   * @returns {import("preact").JSX.Element} The SampleTranscript component.
   */
  const renderRow = (row) => {
    return html` <div
      style=${{
        display: "grid",
        gridTemplateColumns: "3fr 1fr",
        width: "100%",
        height: `${row.height}px`,
        padding: "0.5em",
      }}
      tabindex="0"
    >
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          columnGap: "1em",
        }}
      >
        <div
          style=${{
            gridColumn: "1",
            fontSize: FontSize.large,
            fontWeight: 600,
          }}
        >
          ${row.item.eval.task}
        </div>
        <div style=${{ gridColumn: "2", fontSize: FontSize.base }}>
          ${new Date(row.item.eval.created).toLocaleString()}
        </div>
        <div style=${{ gridColumn: "1/-1", fontSize: FontSize.small }}>
          ${row.item.eval.model}:
          ${configStr(row.item.eval.config, row.item.eval.task_args)}
        </div>
      </div>
      <div>
        <${EvalStatus} logHeader=${row.item} />
      </div>
    </div>`;
  };

  return html`
    <${ListView}
      ref=${listRef}
      rows=${rows}
      renderer=${renderRow}
      selectedIndex=${selectedIndex}
      onSelectedIndex=${onSelectedIndex}
      onShowItem=${onShowLog}
      tabIndex="0"
      style=${listStyle}
    />
  `;
};

const EvalStatus = ({ logHeader }) => {
  switch (logHeader?.status) {
    case "error":
      return html`<${StatusError} message="Error" />`;

    case "cancelled":
      return html`<${StatusCancelled} message="Cancelled" />`;

    case "started":
      return html`<${StatusRunning} message="Running" />`;

    default:
      if (logHeader?.results?.scores) {
        return html`<${Scores} scores=${logHeader.results.scores} />`;
      } else {
        return "";
      }
  }
};

/**
 * Renders scores
 *
 * @param {Object} props - Object properties
 * @param {import("../types/log").Scores} props.scores - The evaluation configuration
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
const Scores = ({ scores }) => {
  return html`<div
    style=${{
      display: "flex",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "flex-end",
      rowGap: "1em",
    }}
  >
    ${scores.map((score) => {
      const name = score.name;
      const reducer = score.reducer;
      return html`
        <div
          style=${{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            marginLeft: "1em",
          }}
        >
          <div
            style=${{
              fontSize: FontSize.base,
              width: "100%",
              fontWeight: 300,
              borderBottom: "solid var(--bs-border-color) 1px",
              ...TextStyle.label,
              ...TextStyle.secondary,
            }}
          >
            ${name}
          </div>
          ${reducer
            ? html` <div
                style=${{
                  fontSize: FontSize.smaller,
                  width: "100%",
                  fontWeight: 300,
                }}
              >
                ${reducer}
              </div>`
            : ""}
          <div
            style=${{
              fontSize: FontSize.smaller,
              display: "grid",
              gridTemplateColumns: "max-content max-content",
              gridGap: "0 0.3rem",
            }}
          >
            ${Object.keys(score.metrics).map((key) => {
              const metric = score.metrics[key];
              return html` <div
                  style=${{ ...TextStyle.label, ...TextStyle.secondary }}
                >
                  ${metric.name}
                </div>
                <div style=${{ fontWeight: "600" }}>
                  ${formatPrettyDecimal(metric.value)}
                </div>`;
            })}
          </div>
        </div>
      `;
    })}
  </div>`;
};

/**
 * Status Cancelled Compoment
 *
 * @param {Object} props - Object properties
 * @param {string} props.message - The message
 * @returns {import("preact").JSX.Element} The Status component.
 */
const StatusCancelled = ({ message }) => {
  return html`<div
    style=${{
      marginTop: "0.2em",
      fontSize: FontSize.small,
      ...TextStyle.label,
      ...TextStyle.secondary,
    }}
  >
    ${message}
  </div>`;
};

/**
 * Status Running Compoment
 *
 * @param {Object} props - Object properties
 * @param {string} props.message - The message
 * @returns {import("preact").JSX.Element} The Status component.
 */
const StatusRunning = ({ message }) => {
  return html` <div
    style=${{
      display: "grid",
      gridTemplateColumns: "max-content max-content",
      columnGap: "0.5em",
      marginTop: "0.3em",
      fontSize: FontSize.small,
      ...TextStyle.secondary,
      ...TextStyle.label,
    }}
  >
    <div>${message}</div>
  </div>`;
};

/**
 * Status Error Compoment
 *
 * @param {Object} props - Object properties
 * @param {string} props.message - The message
 * @returns {import("preact").JSX.Element} The Status component.
 */
const StatusError = ({ message }) => {
  return html`<div
    style=${{
      color: "var(--bs-danger)",
      marginTop: "0.2em",
      fontSize: FontSize.small,
      ...TextStyle.label,
    }}
  >
    ${message}
  </div>`;
};
