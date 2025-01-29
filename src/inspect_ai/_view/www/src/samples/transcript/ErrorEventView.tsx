import { ApplicationIcons } from "../../appearance/icons";
import { ANSIDisplay } from "../../components/AnsiDisplay";
import { ErrorEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptEventState } from "./types";

interface ErrorEventViewProps {
  id: string;
  event: ErrorEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the ErrorEventView component.
 */
export const ErrorEventView: React.FC<ErrorEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      title="Error"
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.error}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav: string) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed: boolean) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <ANSIDisplay
        output={event.error.traceback_ansi}
        style={{
          fontSize: "clamp(0.5rem, calc(0.25em + 1vw), 0.8rem)",
          margin: "0.5em 0",
        }}
      />
    </EventPanel>
  );
};
