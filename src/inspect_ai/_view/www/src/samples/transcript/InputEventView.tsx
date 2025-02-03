import { ApplicationIcons } from "../../appearance/icons";
import { ANSIDisplay } from "../../components/AnsiDisplay";
import { InputEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptEventState } from "./types";

interface InputEventViewProps {
  id: string;
  event: InputEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the ErrorEventView component.
 */
export const InputEventView: React.FC<InputEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      title="Input"
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.input}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <ANSIDisplay
        output={event.input_ansi}
        style={{ fontSize: "clamp(0.4rem, 1.15vw, 0.9rem)" }}
      />
    </EventPanel>
  );
};
