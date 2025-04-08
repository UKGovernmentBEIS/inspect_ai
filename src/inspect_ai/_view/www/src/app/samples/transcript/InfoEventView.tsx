import { FC } from "react";
import { InfoEvent } from "../../../@types/log";
import { JSONPanel } from "../../../components/JsonPanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";
import styles from "./InfoEventView.module.css";

interface InfoEventViewProps {
  id: string;
  event: InfoEvent;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const InfoEventView: FC<InfoEventViewProps> = ({
  id,
  event,
  className,
}) => {
  const panels = [];
  if (typeof event.data === "string") {
    panels.push(<MarkdownDiv markdown={event.data} className={styles.panel} />);
  } else {
    panels.push(<JSONPanel data={event.data} className={styles.panel} />);
  }

  return (
    <EventPanel
      id={id}
      title={"Info" + (event.source ? ": " + event.source : "")}
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.info}
    >
      {panels}
    </EventPanel>
  );
};
