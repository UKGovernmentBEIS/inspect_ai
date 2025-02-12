import { ApplicationIcons } from "../../appearance/icons";
import { JSONPanel } from "../../components/JsonPanel";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { InfoEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import styles from "./InfoEventView.module.css";
import { TranscriptEventState } from "./types";

interface InfoEventViewProps {
  id: string;
  event: InfoEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const InfoEventView: React.FC<InfoEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
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
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      {panels}
    </EventPanel>
  );
};
