import clsx from "clsx";
import { FC } from "react";
import { InfoEvent } from "../../../@types/log";
import { JSONPanel } from "../../../components/JsonPanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";
import styles from "./InfoEventView.module.css";
import { EventNode } from "./types";

interface InfoEventViewProps {
  eventNode: EventNode<InfoEvent>;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const InfoEventView: FC<InfoEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  const panels = [];
  if (typeof event.data === "string") {
    panels.push(
      <MarkdownDiv
        markdown={event.data}
        className={clsx(styles.panel, "text-size-base")}
      />,
    );
  } else {
    panels.push(<JSONPanel data={event.data} className={styles.panel} />);
  }

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      title={"Info" + (event.source ? ": " + event.source : "")}
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.info}
    >
      {panels}
    </EventPanel>
  );
};
