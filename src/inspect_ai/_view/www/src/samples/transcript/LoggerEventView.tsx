import clsx from "clsx";
import { ApplicationIcons } from "../../appearance/icons";
import { LoggerEvent } from "../../types/log";
import { EventRow } from "./event/EventRow";

import styles from "./LoggerEventView.module.css";

interface LoggerEventViewProps {
  event: LoggerEvent;
  className?: string | string[];
}

/**
 * Renders the LoggerEventView component.
 */
export const LoggerEventView: React.FC<LoggerEventViewProps> = ({
  event,
  className,
}) => {
  return (
    <EventRow
      className={className}
      title={event.message.level}
      icon={ApplicationIcons.logging[event.message.level.toLowerCase()]}
    >
      <div className={clsx("text-size-base", styles.grid)}>
        <div className={clsx("text-size-smaller")}>
          ${event.message.message}
        </div>
        <div className={clsx("text-size-smaller", "text-style-secondary")}>
          {event.message.filename}:{event.message.lineno}
        </div>
      </div>
    </EventRow>
  );
};
