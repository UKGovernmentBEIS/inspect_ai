import { FC } from "react";
import { ErrorEvent } from "../../../@types/log";
import { ANSIDisplay } from "../../../components/AnsiDisplay";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";
import { EventNode } from "./types";

interface ErrorEventViewProps {
  eventNode: EventNode<ErrorEvent>;
  className?: string | string[];
}

/**
 * Renders the ErrorEventView component.
 */
export const ErrorEventView: FC<ErrorEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      title="Error"
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.error}
    >
      <ANSIDisplay
        output={event.error.traceback_ansi}
        style={{
          fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
          margin: "0.5em 0",
        }}
      />
    </EventPanel>
  );
};
