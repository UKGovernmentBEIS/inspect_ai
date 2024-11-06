//@ts-check
import { html } from "htm/preact";

import { ColumnListView } from "../components/ListView/ColumnListView.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { formatPrettyDateTime, formatPrettyDecimal } from "../utils/Format.mjs";
import { Pagination } from "../components/Pagination.mjs";
import { StatusFooter } from "../components/StatusFooter.mjs";
import { TaskBar } from "./TaskBar.mjs";

const kRowHeight = 75;

/**
 * Renders the ToolCallView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param { string } props.logDir - the log directory
 * @param { string } props.logCount - the number of log files
 * @param { import("../api/Types.mjs").EvalLogHeader[] } props.logHeaders - The logs to display in the list
 * @param { number } props.page - The currently displaying page number
 * @param { (page: number) => void } props.onPageChanged - Update the current page number
 * @param { number } props.pageCount - The current number of pages
 * @param { string } props.status - The status of the listing
 * @param { number } props.selectedLogIndex - The selected log index
 * @param { (logIndex: number) => void } props.onSelectedLogIndex - update the selected log index
 * @param { Record<string, string>} props.style - Styles to apply to this component
 *
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const TaskList = ({
  logDir,
  logCount,
  logHeaders,
  page,
  pageCount,
  onPageChanged,
  selectedLogIndex,
  onSelectedLogIndex,
  status,
  style,
}) => {
  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };

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

  const columns = ["Time", "Task", "Config", "Samples", "Score"];
  const columnWidths = ["10rem", "17.5rem", ".75fr", ".5fr", "1.25fr"];

  /**
   * Renders a row based on the item and index.
   *
   * @param {import("../components/ListView/Types.mjs").Row<import("../types/log").EvalLog>} row - The row to render
   * @returns {import("preact").JSX.Element} The SampleTranscript component.
   */
  const renderRow = (row) => {
    return html` <div
      style=${{
        display: "grid",
        gridTemplateColumns: columnWidths.join(" "),
        width: "100%",
        minHeight: `${row.height}px`,
        padding: "0.5em 1em",
        columnGap: "0.5em",
        cursor: "pointer",
      }}
      tabindex="0"
    >
      <div style=${{ fontSize: FontSize.smaller, marginTop: "0.3em" }}>
        ${formatPrettyDateTime(new Date(row.item.eval.created))}
        <${EvalStatus} logHeader=${row.item} />
      </div>
      <div>
        <div
          style=${{
            fontSize: FontSize.base,
            fontWeight: 600,
          }}
        >
          ${row.item.eval.task}
        </div>
        <div
          style=${{
            fontSize: FontSize.smaller,
            fontWeight: 400,
          }}
        >
          ${row.item.eval.model}
        </div>
      </div>
      <div style=${{ fontSize: FontSize.small, marginTop: "0.3em" }}>
        <pre style=${{ whiteSpace: "pre-wrap" }}>
${configStr(row.item.eval.config, row.item.eval.task_args)}</pre
        >
      </div>
      <div style=${{ fontSize: FontSize.small, marginTop: "0.3em" }}>
        <div>
          ${`${row.item.eval.dataset.samples} ${row.item.eval.dataset.samples > 1 ? "Samples" : "Sample"}`}
        </div>
        <div>
          <${Epochs} epochs=${row.item.eval.config.epochs} />
        </div>
      </div>
      <div>
        ${row.item.results?.scores
          ? html`<${Scores} scores=${row.item.results?.scores} />`
          : ""}
      </div>
    </div>`;
  };

  const rows = logHeaders
    ? logHeaders.map((logHeader, index) => {
        return {
          item: logHeader,
          height: kRowHeight,
          index,
        };
      })
    : [];

  return html`
    <${TaskBar} logDir=${logDir} />
    <${ColumnListView}
      rows=${rows}
      renderer=${renderRow}
      columns=${columns}
      columnWidths=${columnWidths}
      selectedIndex=${selectedLogIndex}
      onSelectedIndex=${onSelectedLogIndex}
      onShowItem=${(item) => {
        onSelectedLogIndex(item.index);
      }}
      tabIndex="0"
      style=${listStyle}
    />
    <${StatusFooter} spinner=${status === "loading"} spinnerMessage="Loading..." statusMessages=${[{ text: `${logCount} log files` }]}>
      <${Pagination}
        pageCount=${pageCount}
        currentPage=${page}
        onCurrentPage=${onPageChanged}
      />
    </${StatusFooter}>
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
      return "";
  }
};

const Epochs = ({ epochs }) => {
  // Don't render if there are no epochs
  if (!epochs || epochs === 1) {
    return "";
  }

  const epochStr = [];
  epochStr.push(epochs);
  epochStr.push(`${epochs > 1 ? "Epochs" : "Epoch"}`);
  return html` <div>${epochStr.join(" ")}</div>`;
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
      justifyContent: "flex-start",
      columnGap: "1em",
    }}
  >
    ${scores.map((score) => {
      return html`
        <div
          style=${{
            display: "flex",
            flexDirection: "column",
            alignItems: "left",
          }}
        >
          <div style=${{ ...TextStyle.secondary, fontSize: FontSize.smaller }}>
            ${score.scorer}
          </div>
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
              return html` <div>${metric.name}</div>
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
