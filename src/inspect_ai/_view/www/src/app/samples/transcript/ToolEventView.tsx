import { ToolEvent } from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";
import { resolveToolInput } from "../chat/tools/tool";
import { ToolCallView } from "../chat/tools/ToolCallView";
import { ApprovalEventView } from "./ApprovalEventView";
import { EventPanel } from "./event/EventPanel";
import { TranscriptView } from "./TranscriptView";

import clsx from "clsx";
import { FC, useMemo } from "react";
import { PulsingDots } from "../../../components/PulsingDots";
import { ChatView } from "../chat/ChatView";
import { formatTiming, formatTitle } from "./event/utils";
import styles from "./ToolEventView.module.css";

interface ToolEventViewProps {
  id: string;
  event: ToolEvent;
  depth: number;
  className?: string | string[];
}

/**
 * Renders the ToolEventView component.
 */
export const ToolEventView: FC<ToolEventViewProps> = ({
  id,
  event,
  depth,
  className,
}) => {
  // Extract tool input
  const { input, functionCall, highlightLanguage } = useMemo(
    () => resolveToolInput(event.function, event.arguments),
    [event.function, event.arguments],
  );

  const { approvalEvent, lastModelEvent } = useMemo(() => {
    // Find an approval if there is one
    const approvalEvent = event.events.find((e) => {
      return e.event === "approval";
    });

    // Find a model message to render, if there is one
    const lastModelEvent = [...event.events].reverse().find((e) => {
      return e.event === "model";
    });

    return { approvalEvent, lastModelEvent };
  }, [event.events]);

  const title = `Tool: ${event.view?.title || event.function}`;
  return (
    <EventPanel
      id={id}
      title={formatTitle(title, undefined, event.working_time)}
      className={className}
      subTitle={formatTiming(event.timestamp, event.working_start)}
      icon={ApplicationIcons.solvers.use_tools}
    >
      <div data-name="Summary" className={styles.summary}>
        <ToolCallView
          id={`${id}-tool-call`}
          functionCall={functionCall}
          input={input}
          highlightLanguage={highlightLanguage}
          output={event.error?.message || event.result}
          mode="compact"
          view={event.view ? event.view : undefined}
        />

        {lastModelEvent && lastModelEvent.event === "model" ? (
          <ChatView
            id={`${id}-toolcall-chatmessage`}
            messages={lastModelEvent.output.choices.map((m) => m.message)}
            numbered={false}
            toolCallStyle="compact"
          />
        ) : undefined}

        {approvalEvent ? (
          <ApprovalEventView
            event={approvalEvent}
            className={styles.approval}
          />
        ) : (
          ""
        )}
        {event.pending ? (
          <div className={clsx(styles.progress)}>
            <PulsingDots subtle={false} size="medium" />
          </div>
        ) : undefined}
      </div>
      {event.events.length > 0 ? (
        <TranscriptView
          id={`${id}-subtask`}
          data-name="Transcript"
          data-default={event.failed || event.agent ? true : null}
          events={event.events}
          depth={depth + 1}
        />
      ) : (
        ""
      )}
    </EventPanel>
  );
};
