import { FC, JSX, memo, RefObject, useMemo } from "react";
import { Events } from "../../../@types/log";
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
import { EventNode } from "./types";

import clsx from "clsx";
import { SpanEventView } from "./SpanEventView";
import styles from "./TranscriptView.module.css";
import { TranscriptVirtualListComponent } from "./TranscriptVirtualListComponent";
import { fixupEventStream } from "./transform/fixups";
import { treeifyEvents } from "./transform/treeify";

interface TranscriptViewProps {
  id: string;
  events: Events;
  depth: number;
}

/**
 * Renders the TranscriptView component.
 */
export const TranscriptView: FC<TranscriptViewProps> = ({
  id,
  events,
  depth,
}) => {
  // Normalize Events themselves
  const resolvedEvents = fixupEventStream(events);
  const eventNodes = treeifyEvents(
    resolvedEvents,
    depth !== undefined ? depth : 0,
  );
  return <TranscriptComponent id={id} eventNodes={eventNodes} />;
};

interface TranscriptVirtualListProps {
  id: string;
  events: Events;
  depth?: number;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptVirtualList: FC<TranscriptVirtualListProps> = memo(
  (props) => {
    let { id, scrollRef, events, depth, running } = props;

    // Normalize Events themselves
    const eventNodes = useMemo(() => {
      const resolvedEvents = fixupEventStream(events, !running);
      const eventNodes = treeifyEvents(resolvedEvents, depth || 0);
      return eventNodes;
    }, [events, depth]);

    return (
      <TranscriptVirtualListComponent
        id={id}
        eventNodes={eventNodes}
        scrollRef={scrollRef}
        running={running}
      />
    );
  },
);

interface TranscriptComponentProps {
  id: string;
  eventNodes: EventNode[];
}
/**
 * Renders the Transcript component.
 */
export const TranscriptComponent: FC<TranscriptComponentProps> = memo(
  ({ id, eventNodes }) => {
    const rows: JSX.Element[] = [];

    let attached = false;
    for (let i = 0; i < eventNodes.length; i++) {
      const eventNode = eventNodes[i];
      const clz = [styles.eventNode];
      const containerClz = [];

      if (eventNode.event.event !== "tool") {
        attached = false;
      }

      // Special handling for toggling color
      if (eventNode.depth % 2 == 0) {
        clz.push(styles.darkenBg);
      }

      // Note last node
      if (i === eventNodes.length - 1) {
        clz.push(styles.lastNode);
      }

      if (attached) {
        containerClz.push(styles.attached);
      }

      const eventId = `${id}|event|${i}`;
      const row = (
        <div
          key={eventId}
          className={clsx(
            styles.eventNodeContainer,
            i === eventNodes.length - 1 ? styles.noBottom : undefined,
            containerClz,
          )}
        >
          <RenderedEventNode
            id={eventId}
            node={eventNode}
            className={clsx(clz)}
          />
        </div>
      );
      rows.push(row);

      if (eventNode.event.event === "model") {
        attached = true;
      }
    }

    return (
      <div
        id={id}
        className={clsx("text-size-small", styles.transcriptComponent)}
      >
        {rows}
      </div>
    );
  },
);

interface RenderedEventNodeProps {
  id: string;
  node: EventNode;
  className?: string | string[];
}
/**
 * Renders the event based on its type.
 */
export const RenderedEventNode: FC<RenderedEventNodeProps> = memo(
  ({ id, node, className }) => {
    switch (node.event.event) {
      case "sample_init":
        return (
          <SampleInitEventView
            id={id}
            event={node.event}
            className={className}
          />
        );

      case "sample_limit":
        return (
          <SampleLimitEventView
            id={id}
            event={node.event}
            className={className}
          />
        );

      case "info":
        return (
          <InfoEventView id={id} event={node.event} className={className} />
        );

      case "logger":
        return <LoggerEventView event={node.event} className={className} />;

      case "model":
        return (
          <ModelEventView id={id} event={node.event} className={className} />
        );

      case "score":
        return (
          <ScoreEventView id={id} event={node.event} className={className} />
        );

      case "state":
        return (
          <StateEventView id={id} event={node.event} className={className} />
        );

      case "span_begin":
        return (
          <SpanEventView
            id={id}
            event={node.event}
            children={node.children}
            className={className}
          />
        );

      case "step":
        return (
          <StepEventView
            id={id}
            event={node.event}
            children={node.children}
            className={className}
          />
        );

      case "store":
        return (
          <StateEventView
            id={id}
            event={node.event}
            className={className}
            isStore={true}
          />
        );

      case "subtask":
        return (
          <SubtaskEventView
            id={id}
            event={node.event}
            className={className}
            depth={node.depth}
          />
        );

      case "tool":
        return (
          <ToolEventView
            id={id}
            event={node.event}
            className={className}
            children={node.children}
          />
        );

      case "input":
        return (
          <InputEventView id={id} event={node.event} className={className} />
        );

      case "error":
        return (
          <ErrorEventView id={id} event={node.event} className={className} />
        );

      case "approval":
        return <ApprovalEventView event={node.event} className={className} />;

      case "sandbox":
        return (
          <SandboxEventView id={id} event={node.event} className={className} />
        );

      default:
        return null;
    }
  },
);
