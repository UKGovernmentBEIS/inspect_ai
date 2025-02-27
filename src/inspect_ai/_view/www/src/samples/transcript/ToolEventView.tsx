import { ApplicationIcons } from "../../appearance/icons";
import { ToolEvent } from "../../types/log";
import { resolveToolInput } from "../chat/tools/tool";
import { ToolCallView } from "../chat/tools/ToolCallView";
import { ApprovalEventView } from "./ApprovalEventView";
import { EventPanel } from "./event/EventPanel";
import { TranscriptView } from "./TranscriptView";
import { TranscriptEventState } from "./types";

import { FC, useMemo } from "react";
import { formatTiming, formatTitle } from "./event/utils";
import styles from "./ToolEventView.module.css";

interface ToolEventViewProps {
  id: string;
  event: ToolEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  depth: number;
  className?: string | string[];
}

/**
 * Renders the ToolEventView component.
 */
export const ToolEventView: FC<ToolEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  depth,
  className,
}) => {
  // Extract tool input
  const { input, functionCall, highlightLanguage } = useMemo(
    () => resolveToolInput(event.function, event.arguments),
    [event.function, event.arguments],
  );

  // Find an approval if there is one
  const approvalEvent = event.events.find((e) => {
    return e.event === "approval";
  });

  const title = `Tool: ${event.view?.title || event.function}`;
  return (
    <EventPanel
      id={id}
      title={formatTitle(title, undefined, event.working_time)}
      className={className}
      subTitle={formatTiming(event.timestamp, event.working_start)}
      icon={ApplicationIcons.solvers.use_tools}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <div data-name="Summary" className={styles.summary}>
        <ToolCallView
          functionCall={functionCall}
          input={input}
          highlightLanguage={highlightLanguage}
          output={event.error?.message || event.result}
          mode="compact"
          view={event.view ? event.view : undefined}
        />
        {approvalEvent ? (
          <ApprovalEventView
            event={approvalEvent}
            className={styles.approval}
          />
        ) : (
          ""
        )}
      </div>
      {event.events.length > 0 ? (
        <TranscriptView
          id={`${id}-subtask`}
          data-name="Transcript"
          events={event.events}
          depth={depth + 1}
        />
      ) : (
        ""
      )}
    </EventPanel>
  );
};
