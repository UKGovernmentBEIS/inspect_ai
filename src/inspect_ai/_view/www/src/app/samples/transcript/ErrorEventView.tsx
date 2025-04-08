import { FC } from "react";
import { ErrorEvent } from "../../../@types/log";
import { ANSIDisplay } from "../../../components/AnsiDisplay";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";

interface ErrorEventViewProps {
  id: string;
  event: ErrorEvent;
  className?: string | string[];
}

/**
 * Renders the ErrorEventView component.
 */
export const ErrorEventView: FC<ErrorEventViewProps> = ({
  id,
  event,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      title="Error"
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.error}
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
