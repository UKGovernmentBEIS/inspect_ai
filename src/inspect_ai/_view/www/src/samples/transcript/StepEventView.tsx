import clsx from "clsx";
import { RefObject, useCallback, useState } from "react";
import { StepEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptVirtualListComponent } from "./TranscriptView";
import { EventNode, TranscriptEventState } from "./types";

interface StepEventViewProps {
  event: StepEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  children: EventNode[];
  scrollRef?: RefObject<HTMLDivElement | null>;
  className?: string | string[];
}

/**
 * Renders the StepEventView component.
 */
export const StepEventView: React.FC<StepEventViewProps> = ({
  event,
  eventState,
  setEventState,
  children,
  scrollRef,
  className,
}) => {
  const descriptor = stepDescriptor(event);
  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text = summarize(children);

  const [transcriptState, setTranscriptState] = useState({});
  const onTranscriptState = useCallback(
    (state: TranscriptEventState) => {
      setTranscriptState({ ...state });
    },
    [transcriptState, setTranscriptState],
  );

  return (
    <EventPanel
      id={`step-${event.name}`}
      className={clsx("transcript-step", className)}
      title={title}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={descriptor.icon}
      collapse={false}
      text={text}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <TranscriptVirtualListComponent
        id={`step-${event.name}-transcript`}
        eventNodes={children}
        scrollRef={scrollRef}
        transcriptState={transcriptState}
        setTranscriptState={onTranscriptState}
      />
    </EventPanel>
  );
};

/**
 * Renders the StepEventView component.
 */
const summarize = (children: EventNode[]) => {
  if (children.length === 0) {
    return "(no events)";
  }

  const formatEvent = (event: string, count: number) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };

  // Count the types
  const typeCount: Record<string, number> = {};
  children.forEach((child) => {
    const currentCount = typeCount[child.event.event] || 0;
    typeCount[child.event.event] = currentCount + 1;
  });

  // Try to summarize event types
  const numberOfTypes = Object.keys(typeCount).length;
  if (numberOfTypes < 3) {
    return Object.keys(typeCount)
      .map((key) => {
        return formatEvent(key, typeCount[key]);
      })
      .join(", ");
  }

  // To many types, just return the number of events
  if (children.length === 1) {
    return "1 event";
  } else {
    return `${children.length} events`;
  }
};

/**
 * Returns a descriptor object containing icon and style based on the event type and name.
 */
const stepDescriptor = (
  event: StepEvent,
): { icon?: string; name?: string; endSpace?: boolean } => {
  const rootStepDescriptor = {
    endSpace: true,
  };

  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          ...rootStepDescriptor,
        };
      case "generate":
        return {
          ...rootStepDescriptor,
        };
      case "self_critique":
        return {
          ...rootStepDescriptor,
        };
      case "system_message":
        return {
          ...rootStepDescriptor,
        };
      case "use_tools":
        return {
          ...rootStepDescriptor,
        };
      case "multiple_choice":
        return {
          ...rootStepDescriptor,
        };
      default:
        return {
          ...rootStepDescriptor,
        };
    }
  } else if (event.type === "scorer") {
    return {
      ...rootStepDescriptor,
    };
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          ...rootStepDescriptor,
          name: "Sample Init",
        };
      default:
        return {
          endSpace: false,
        };
    }
  }
};
