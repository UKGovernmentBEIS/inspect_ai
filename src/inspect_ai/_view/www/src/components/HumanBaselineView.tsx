import { FC, useEffect } from "react";
import { formatDateTime, formatTime } from "../utils/format";
import { AsciinemaPlayer } from "./AsciinemaPlayer";
import "./HumanBaselineView.css";
import { LightboxCarousel } from "./LightboxCarousel";

export interface SessionLog {
  name: string;
  user: string;
  input: string;
  output: string;
  timing: string;
}

interface HumanBaselineViewProps {
  started?: Date;
  running: boolean;
  completed?: boolean;
  runtime?: number;
  answer?: string;
  sessionLogs: SessionLog[];
}

/**
 * Renders the HumanBaselineView component.
 */
export const HumanBaselineView: FC<HumanBaselineViewProps> = ({
  started,
  runtime,
  answer,
  completed,
  running,
  sessionLogs,
}) => {
  const player_fns = [];

  // handle creation and revoking of these URLs
  const revokableUrls: string[] = [];
  const revokableUrl = (data: BlobPart) => {
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
    const rows = extractSize(sessionLog.output, "LINES", 24);
    const cols = extractSize(sessionLog.output, "COLUMNS", 80);
    maxCols = Math.max(maxCols, cols);

    const currentCount = count;
    const title =
      sessionLogs.length === 1
        ? "Terminal Session"
        : `Terminal Session ${currentCount}`;

    player_fns.push({
      label: title,
      render: () => (
        <AsciinemaPlayer
          id={`player-${currentCount}`}
          inputUrl={revokableUrl(sessionLog.input)}
          outputUrl={revokableUrl(sessionLog.output)}
          timingUrl={revokableUrl(sessionLog.timing)}
          rows={rows}
          cols={cols}
          className={"asciinema-player"}
          style={{
            height: `${rows * 2}em`,
            width: `${cols * 2}em`,
          }}
          fit="both"
        />
      ),
    });
    count += 1;
  }

  interface StatusMessageProps {
    completed?: boolean;
    running?: boolean;
    answer?: string;
  }

  const StatusMessage: FC<StatusMessageProps> = ({
    completed,
    running,
    answer,
  }) => {
    if (running) {
      return <span className={"text-style-label"}>Running</span>;
    } else if (completed) {
      return (
        <div>
          <span
            className={
              "text-style-label text-style-secondary asciinema-player-status"
            }
          >
            Answer
          </span>
          <span>{answer}</span>
        </div>
      );
    } else {
      return "Unknown status";
    }
  };

  return (
    <div className={"asciinema-wrapper"}>
      <div className={"asciinema-container"}>
        <div className={"asciinema-header-left text-style-label"}>
          {started ? formatDateTime(started) : ""}
          {runtime ? ` (${formatTime(Math.floor(runtime))})` : ""}
        </div>
        <div className={"asciinema-header-center text-style-label"}></div>
        <div className={"asciinema-header-right"}>
          <StatusMessage
            completed={completed}
            running={running}
            answer={answer}
          />
        </div>
        <div className={"asciinema-body"}>
          <LightboxCarousel id="ascii-cinema" slides={player_fns} />
        </div>
      </div>
    </div>
  );
};

/**
 * Extracts a numeric size value from a string based on a given label.
 *
 * Searches the input string for a pattern matching the format `LABEL="VALUE"`,
 * where `LABEL` is the provided label and `VALUE` is a numeric value.
 */
const extractSize = (
  value: string,
  label: string,
  defaultValue: number,
): number => {
  const regex = new RegExp(`${label}="(\\d+)"`);
  const match = value.match(regex);
  const size = match ? match[1] : undefined;
  if (size) {
    return parseInt(size);
  } else {
    return defaultValue;
  }
};
