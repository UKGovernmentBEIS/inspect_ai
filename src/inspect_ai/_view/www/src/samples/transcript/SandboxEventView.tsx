import { ApplicationIcons } from "../../appearance/icons";
import { SandboxEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";
import { TranscriptEventState } from "./types";

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
      title="Sandbox"
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
      <div data-name={event.action} className={styles.contents}>
        <EventSection title="Target">
          <MarkdownDiv markdown={event.summary} />
        </EventSection>
      </div>
    </EventPanel>
  );
};
