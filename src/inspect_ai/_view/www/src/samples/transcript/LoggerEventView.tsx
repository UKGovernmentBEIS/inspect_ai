import clsx from "clsx";
import { ApplicationIcons } from "../../appearance/icons";
import { LoggerEvent } from "../../types/log";
import { EventRow } from "./event/EventRow";

import JSONPanel from "../../components/JsonPanel";
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
          {isJson(event.message.message) ? (
            <JSONPanel
              json={event.message.message}
              className={clsx(styles.jsonPanel)}
            />
          ) : (
            event.message.message
          )}
        </div>
        <div className={clsx("text-size-smaller", "text-style-secondary")}>
          {event.message.filename}:{event.message.lineno}
        </div>
      </div>
    </EventRow>
  );
};

export const isJson = (text: string): boolean => {
  text = text.trim();
  if (text.startsWith("{")) {
    try {
      JSON.parse(text);
      return true;
    } catch {
      return false;
    }
  }
  return false;
};
