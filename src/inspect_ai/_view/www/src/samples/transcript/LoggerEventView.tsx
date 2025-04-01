import clsx from "clsx";
import { ApplicationIcons } from "../../appearance/icons";
import { LoggerEvent } from "../../types/log";
import { EventRow } from "./event/EventRow";

import { FC } from "react";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { parsedJson as maybeParseJson } from "../../utils/json";
import styles from "./LoggerEventView.module.css";

interface LoggerEventViewProps {
  event: LoggerEvent;
  className?: string | string[];
}

/**
 * Renders the LoggerEventView component.
 */
export const LoggerEventView: FC<LoggerEventViewProps> = ({
  event,
  className,
}) => {
  const obj = maybeParseJson(event.message.message);
  return (
    <EventRow
      className={className}
      title={event.message.level}
      icon={ApplicationIcons.logging[event.message.level.toLowerCase()]}
    >
      <div className={clsx("text-size-base", styles.grid)}>
        <div className={clsx("text-size-smaller")}>
          {obj !== undefined && obj !== null ? (
            <MetaDataGrid entries={obj as Record<string, unknown>} />
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
