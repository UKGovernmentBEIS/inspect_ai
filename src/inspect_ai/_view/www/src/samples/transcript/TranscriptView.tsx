import { FC, RefObject, useCallback, useState } from "react";
import { Events } from "../../types/log";
import { ApprovalEventView } from "./ApprovalEventView";
import { ErrorEventView } from "./ErrorEventView";
import { InfoEventView } from "./InfoEventView";
import { InputEventView } from "./InputEventView";
import { LoggerEventView } from "./LoggerEventView";
import { ModelEventView } from "./ModelEventView";
import { SampleInitEventView } from "./SampleInitEventView";
import { SampleLimitEventView } from "./SampleLimitEventView";
import { SandboxEventView } from "./SandboxEventView";
import { ScoreEventView } from "./ScoreEventView";
import { StateEventView } from "./state/StateEventView";
import { StepEventView } from "./StepEventView";
import { SubtaskEventView } from "./SubtaskEventView";
import { ToolEventView } from "./ToolEventView";
import { EventNode, EventType, TranscriptEventState } from "./types";

import clsx from "clsx";
import styles from "./TranscriptView.module.css";
import { TranscriptVirtualListComponent } from "./TranscriptVirtualListComponent";

interface TranscriptViewProps {
  id: string;
  events: Events;
  depth: number;
}

type TranscriptState = Record<string, TranscriptEventState>;

/**
 * Renders the TranscriptView component.
 */
export const TranscriptView: FC<TranscriptViewProps> = ({
  id,
  events,
  depth,
}) => {
  const [transcriptState, setTranscriptState] = useState<TranscriptState>({});
  const onTranscriptState = useCallback(
    (state: TranscriptState) => {
      setTranscriptState(state);
    },
    [setTranscriptState],
  );

  // Normalize Events themselves
  const resolvedEvents = fixupEventStream(events);
  const eventNodes = treeifyEvents(
    resolvedEvents,
    depth !== undefined ? depth : 0,
  );
  return (
    <TranscriptComponent
      id={id}
      eventNodes={eventNodes}
      transcriptState={transcriptState}
      setTranscriptState={onTranscriptState}
    />
  );
};

interface TranscriptVirtualListProps {
  id: string;
  events: Events;
  depth?: number;
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptVirtualList: FC<TranscriptVirtualListProps> = (
  props,
) => {
  let { id, scrollRef, events, depth } = props;

  // Normalize Events themselves
  const resolvedEvents = fixupEventStream(events);
  const eventNodes = treeifyEvents(resolvedEvents, depth || 0);

  const [transcriptState, setTranscriptState] = useState({});
  const onTranscriptState = useCallback(
    (state: TranscriptEventState) => {
      setTranscriptState(state);
    },
    [setTranscriptState],
  );

  return (
    <TranscriptVirtualListComponent
      id={id}
      eventNodes={eventNodes}
      scrollRef={scrollRef}
      transcriptState={transcriptState}
      setTranscriptState={onTranscriptState}
    />
  );
};

interface TranscriptComponentProps {
  id: string;
  transcriptState: TranscriptState;
  setTranscriptState: (state: TranscriptState) => void;
  eventNodes: EventNode[];
}
/**
 * Renders the Transcript component.
 */
export const TranscriptComponent: FC<TranscriptComponentProps> = ({
  id,
  transcriptState,
  setTranscriptState,
  eventNodes,
}) => {
  const setEventState = useCallback(
    (state: TranscriptEventState, eventId: string) => {
      setTranscriptState({ ...transcriptState, [eventId]: state });
    },
    [setTranscriptState, transcriptState],
  );

  const rows = eventNodes.map((eventNode, index) => {
    const clz = [styles.eventNode];
    if (eventNode.depth % 2 == 0) {
      clz.push(styles.darkenBg);
    }
    if (index === eventNodes.length - 1) {
      clz.push(styles.lastNode);
    }

    const eventId = `${id}-event${index}`;

    const row = (
      <div
        key={eventId}
        className={clsx(
          styles.eventNodeContainer,
          index === eventNodes.length - 1 ? styles.noBottom : undefined,
        )}
      >
        <RenderedEventNode
          id={eventId}
          node={eventNode}
          className={clsx(clz)}
          eventState={transcriptState[eventId] || {}}
          setEventState={(state: TranscriptEventState) => {
            setEventState(state, eventId);
          }}
        />
      </div>
    );
    return row;
  });

  return (
    <div
      id={id}
      className={clsx("text-size-small", styles.transcriptComponent)}
    >
      {rows}
    </div>
  );
};

interface RenderedEventNodeProps {
  id: string;
  node: EventNode;
  scrollRef?: RefObject<HTMLDivElement | null>;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}
/**
 * Renders the event based on its type.
 */
export const RenderedEventNode: FC<RenderedEventNodeProps> = ({
  id,
  node,
  scrollRef,
  eventState,
  setEventState,
  className,
}) => {
  switch (node.event.event) {
    case "sample_init":
      return (
        <SampleInitEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "sample_limit":
      return (
        <SampleLimitEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "info":
      return (
        <InfoEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "logger":
      return <LoggerEventView event={node.event} className={className} />;

    case "model":
      return (
        <ModelEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "score":
      return (
        <ScoreEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "state":
      return (
        <StateEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "step":
      return (
        <StepEventView
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          children={node.children}
          scrollRef={scrollRef}
          className={className}
        />
      );

    case "store":
      return (
        <StateEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
          isStore={true}
        />
      );

    case "subtask":
      return (
        <SubtaskEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
          depth={node.depth}
        />
      );

    case "tool":
      return (
        <ToolEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
          depth={node.depth}
        />
      );

    case "input":
      return (
        <InputEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "error":
      return (
        <ErrorEventView
          id={id}
          event={node.event}
          eventState={eventState}
          setEventState={setEventState}
          className={className}
        />
      );

    case "approval":
      return <ApprovalEventView event={node.event} className={className} />;

    case "sandbox":
      return (
        <SandboxEventView
          id={id}
          event={node.event}
          className={className}
          eventState={eventState}
          setEventState={setEventState}
        />
      );

    default:
      return null;
  }
};

/**
 * Normalizes event content
 */
const fixupEventStream = (events: Events) => {
  const initEventIndex = events.findIndex((e) => {
    return e.event === "sample_init";
  });
  const initEvent = events[initEventIndex];

  // Filter pending events
  const finalEvents = events.filter((e) => !e.pending);

  // See if the find an init step
  const hasInitStep =
    events.findIndex((e) => {
      return e.event === "step" && e.name === "init";
    }) !== -1;

  const fixedUp = [...finalEvents];
  if (!hasInitStep && initEvent) {
    fixedUp.splice(initEventIndex, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "begin",
      type: null,
      name: "sample_init",
      pending: false,
      working_start: 0,
    });

    fixedUp.splice(initEventIndex + 2, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "end",
      type: null,
      name: "sample_init",
      pending: false,
      working_start: 0,
    });
  }

  return fixedUp;
};

/**
 * Gathers events into a hierarchy of EventNodes.
 */
function treeifyEvents(events: Events, depth: number): EventNode[] {
  const rootNodes: EventNode[] = [];
  const stack: EventNode[] = [];

  const pushNode = (event: EventType): EventNode => {
    const node = new EventNode(event, stack.length + depth);
    if (stack.length > 0) {
      const parentNode = stack[stack.length - 1];
      parentNode.children.push(node);
    } else {
      rootNodes.push(node);
    }
    return node;
  };

  events.forEach((event) => {
    if (event.event === "step" && event.action === "begin") {
      // Starting a new step
      const node = pushNode(event);
      stack.push(node);
    } else if (event.event === "step" && event.action === "end") {
      // An ending step
      if (stack.length > 0) {
        stack.pop();
      }
    } else {
      // An event
      pushNode(event);
    }
  });

  return rootNodes;
}
