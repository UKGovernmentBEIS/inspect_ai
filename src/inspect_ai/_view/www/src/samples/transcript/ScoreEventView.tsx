import { Fragment } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { ScoreEvent, Value1 } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptEventState } from "./types";

import clsx from "clsx";
import styles from "./ScoreEventView.module.css";

interface ScoreEventViewProps {
  id: string;
  event: ScoreEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the ScoreEventView component.
 */
export const ScoreEventView: React.FC<ScoreEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  const resolvedTarget = event.target
    ? Array.isArray(event.target)
      ? event.target.join("\n")
      : event.target
    : undefined;

  return (
    <EventPanel
      id={id}
      title={(event.intermediate ? "Intermediate " : "") + "Score"}
      className={clsx(className, "text-size-small")}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.scorer}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <div data-name="Explanation" className={clsx(styles.explanation)}>
        {event.target ? (
          <Fragment>
            <div className={clsx(styles.separator)}></div>
            <div className={"text-style-label"}>Target</div>
            <div>
              <MarkdownDiv markdown={resolvedTarget || ""} />
            </div>
          </Fragment>
        ) : (
          ""
        )}
        <div className={clsx(styles.separator)}></div>
        <div className={"text-style-label"}>Answer</div>
        <div>
          <MarkdownDiv markdown={event.score.answer || ""} />
        </div>
        <div className={clsx(styles.separator)}></div>
        <div className={"text-style-label"}>Explanation</div>
        <div>
          <MarkdownDiv markdown={event.score.explanation || ""} />
        </div>
        <div className={clsx(styles.separator)}></div>
        <div className={"text-style-label"}>Score</div>
        <div>{renderScore(event.score.value)}</div>
        <div className={clsx(styles.separator)}></div>
      </div>
      {event.score.metadata ? (
        <div data-name="Metadata">
          <MetaDataGrid
            entries={event.score.metadata}
            className={styles.metadata}
          />
        </div>
      ) : undefined}
    </EventPanel>
  );
};

const renderScore = (value: Value1) => {
  if (Array.isArray(value)) {
    return value.join(" ");
  } else if (typeof value === "object") {
    return <MetaDataGrid entries={value} />;
  } else {
    return value;
  }
};
