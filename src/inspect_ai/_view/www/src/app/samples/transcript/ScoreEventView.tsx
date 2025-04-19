import { FC, Fragment } from "react";
import { ScoreEvent, Value1 } from "../../../@types/log";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { EventPanel } from "./event/EventPanel";

import clsx from "clsx";
import styles from "./ScoreEventView.module.css";

interface ScoreEventViewProps {
  id: string;
  event: ScoreEvent;
  className?: string | string[];
}

/**
 * Renders the ScoreEventView component.
 */
export const ScoreEventView: FC<ScoreEventViewProps> = ({
  id,
  event,
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
