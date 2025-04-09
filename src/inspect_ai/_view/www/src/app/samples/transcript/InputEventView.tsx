import { FC } from "react";
import { InputEvent } from "../../../@types/log";
import { ANSIDisplay } from "../../../components/AnsiDisplay";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";

interface InputEventViewProps {
  id: string;
  event: InputEvent;
  className?: string | string[];
}

/**
 * Renders the ErrorEventView component.
 */
export const InputEventView: FC<InputEventViewProps> = ({
  id,
  event,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      title="Input"
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.input}
    >
      <ANSIDisplay
        output={event.input_ansi}
        style={{ fontSize: "clamp(0.4rem, 1.15vw, 0.9rem)" }}
      />
    </EventPanel>
  );
};
