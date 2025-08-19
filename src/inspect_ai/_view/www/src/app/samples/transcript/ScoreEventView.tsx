import { FC, Fragment } from "react";
import { ScoreEvent, Value1 } from "../../../@types/log";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { EventPanel } from "./event/EventPanel";

import clsx from "clsx";
import { RecordTree } from "../../content/RecordTree";
import styles from "./ScoreEventView.module.css";
import { EventNode } from "./types";

interface ScoreEventViewProps {
  eventNode: EventNode<ScoreEvent>;
  className?: string | string[];
}

/**
 * Renders the ScoreEventView component.
 */
export const ScoreEventView: FC<ScoreEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  const resolvedTarget = event.target
    ? Array.isArray(event.target)
      ? event.target.join("\n")
      : event.target
    : undefined;

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      title={(event.intermediate ? "Intermediate " : "") + "Score"}
      className={clsx(className, "text-size-small")}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.scorer}
      collapsibleContent={true}
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
          <RecordTree
            id={`${eventNode.id}-score-metadata`}
            record={event.score.metadata}
            className={styles.metadataTree}
            defaultExpandLevel={0}
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
