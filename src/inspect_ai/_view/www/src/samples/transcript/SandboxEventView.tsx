import { ApplicationIcons } from "../../appearance/icons";
import { SandboxEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptEventState } from "./types";

import clsx from "clsx";
import { MarkdownDiv } from "../../components/MarkdownDiv";

import styles from "./SandboxEventView.module.css";

interface SandboxEventViewProps {
  id: string;
  event: SandboxEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the SandboxEventView component.
 */
export const SandboxEventView: React.FC<SandboxEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      className={className}
      title={`Sandbox: ${event.action}`}
      icon={ApplicationIcons.sandbox}
      subTitle={formatDateTime(new Date(event.timestamp))}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <MarkdownDiv markdown={event.summary} className={clsx(styles.contents)} />
    </EventPanel>
  );
};
