// @ts-check
import { html } from "htm/preact";
import { useEffect } from "preact/hooks";
import { formatDateTime, formatTime } from "../utils/Format.mjs";
import { AsciiCinemaPlayer } from "./AsciiCinemaPlayer.mjs";
import { TextStyle } from "../appearance/Fonts.mjs";
import { LightboxCarousel } from "./LightboxCarousel.mjs";

/**
 * @typedef {Object} SessionLog
 * @property {string} name - The name of this session
 * @property {string} user - The user for this session
 * @property {string} input - The input for this session
 * @property {string} output - The output for this session
 * @property {string} timing - The timing for this session
 */

/**
 * Renders the HumanBaselineView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {Date} props.started - When the baselining started
 * @param {boolean} props.running - Whether the baselining is running
 * @param {boolean} [props.completed] - Whether the baselining was completed
 * @param {number} [props.runtime] - Duration of baselining in seconds
 * @param {string} [props.answer] - The answer for the baselining
 * @param {SessionLog[]} [props.sessionLogs] - The session logs for the baselining
 * @returns {import("preact").JSX.Element} The component.
 */
export const HumanBaselineView = ({
  started,
  runtime,
  answer,
  completed,
  running,
  sessionLogs,
}) => {
  const player_fns = [];

  // handle creation and revoking of these URLs
  const revokableUrls = [];
  const revokableUrl = (data) => {
    const blob = new Blob([data], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    revokableUrls.push(url);
    return url;
  };

  useEffect(() => {
    return () => {
      revokableUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  // Make a player for each session log
  let count = 1;
  let maxCols = 0;

  for (const sessionLog of sessionLogs) {
    const rows = extractSize(sessionLog.output, "LINES");
    const cols = extractSize(sessionLog.output, "COLUMNS");
    maxCols = Math.max(maxCols, parseInt(cols));

    const currentCount = count;
    const title =
      sessionLogs.length === 1
        ? "Terminal Session"
        : `Terminal Session ${currentCount}`;

    player_fns.push({
      label: title,
      render: () => html`
        <${AsciiCinemaPlayer}
          id=${`player-${currentCount}`}
          inputUrl=${revokableUrl(sessionLog.input)}
          outputUrl=${revokableUrl(sessionLog.output)}
          timingUrl=${revokableUrl(sessionLog.timing)}
          rows=${rows}
          cols=${cols}
          style=${{
            maxHeight: "100vh",
            maxWidth: "100vw",
            height: `${parseInt(rows) * 2}em`,
            width: `${parseInt(cols) * 2}em`,
          }}
          fit="both"
        />
      `,
    });
    count += 1;
  }

  const StatusMessage = ({ completed, running, answer }) => {
    if (running) {
      return html`<span style=${{ ...TextStyle.label }}>Running</span>`;
    } else if (completed) {
      return html`<span style=${{ ...TextStyle.label, marginRight: "0.5em" }}
          >Answer</span
        ><span>${answer}</span>`;
    } else {
      return "Unknown status";
    }
  };

  return html`<div style=${{ display: "flex", justifyContent: "center" }}>
    <div
      style=${{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gridTemplateRows: "auto auto",
        width: "100%",
      }}
    >
      <div
        style=${{
          justifySelf: "start",
          ...TextStyle.label,
        }}
      >
        ${started ? formatDateTime(started) : ""}${runtime
          ? ` (${formatTime(Math.floor(runtime))})`
          : ""}
      </div>
      <div
        style=${{
          justifySelf: "center",
          ...TextStyle.label,
        }}
      ></div>
      <div
        style=${{
          justifySelf: "end",
        }}
      >
        <${StatusMessage}
          completed=${completed}
          running=${running}
          answer=${answer}
        />
      </div>
      <div
        style=${{
          gridColumn: "span 3",
          width: "100%",
        }}
      >
        <${LightboxCarousel} slides=${player_fns} />
      </div>
    </div>
  </div>`;
};

/**
 * Extracts a numeric size value from a string based on a given label.
 *
 * Searches the input string for a pattern matching the format `LABEL="VALUE"`,
 * where `LABEL` is the provided label and `VALUE` is a numeric value.
 *
 * @param {string} value - The input string to search within.
 * @param {string} label - The label to look for in the string.
 * @returns {string | undefined} The extracted size as a string if found, otherwise `undefined`.
 */
const extractSize = (value, label) => {
  const regex = new RegExp(`${label}="(\\d+)"`);
  const match = value.match(regex);
  const size = match ? match[1] : undefined;
  return size;
};
