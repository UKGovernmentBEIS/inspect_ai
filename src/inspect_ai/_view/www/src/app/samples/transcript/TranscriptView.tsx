import { FC, JSX, memo, RefObject, useEffect, useMemo } from "react";
import {
  ApprovalEvent,
  ErrorEvent,
  Events,
  InfoEvent,
  InputEvent,
  LoggerEvent,
  ModelEvent,
  SampleInitEvent,
  SampleLimitEvent,
  SandboxEvent,
  ScoreEvent,
  SpanBeginEvent,
  StateEvent,
  StepEvent,
  StoreEvent,
  SubtaskEvent,
  ToolEvent,
} from "../../../@types/log";
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
import { useStore } from "../../../state/store";
import { SpanEventView } from "./SpanEventView";
import styles from "./TranscriptView.module.css";
import { TranscriptVirtualListComponent } from "./TranscriptVirtualListComponent";
import { fixupEventStream, kSandboxSignalName } from "./transform/fixups";
import { flatTree, treeifyEvents } from "./transform/treeify";

interface TranscriptVirtualListProps {
  id: string;
  events: Events;
  initialEventId: string | null;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptVirtualList: FC<TranscriptVirtualListProps> = memo(
  (props) => {
    let { id, scrollRef, events, running, initialEventId } = props;

    // The list of events that have been collapsed
    const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
    const setCollapsedEvents = useStore(
      (state) => state.sampleActions.setCollapsedEvents,
    );

    // Normalize Events in a flattened filtered list
    const { eventNodes, defaultCollapsedIds } = useMemo(() => {
      // Apply fixups to the event string
      const resolvedEvents = fixupEventStream(events, !running);

      // Build the event tree
      const eventTree = treeifyEvents(resolvedEvents, 0);

      // Apply collapse filters to the event tree
      const defaultCollapsedIds = new Set<string>();
      const findCollapsibleEvents = (nodes: EventNode[]) => {
        for (const node of nodes) {
          if (
            (node.event.event === "step" ||
              node.event.event === "span_begin") &&
            collapseFilters.some((filter) =>
              filter(node.event as StepEvent | SpanBeginEvent),
            )
          ) {
            defaultCollapsedIds.add(node.id);
          }

          // Recursively check children
          findCollapsibleEvents(node.children);
        }
      };
      findCollapsibleEvents(eventTree);

      // flattten the event tree
      const eventNodes = flatTree(
        eventTree,
        collapsedEvents || defaultCollapsedIds,
      );

      return { eventNodes, defaultCollapsedIds };
    }, [events, running, collapsedEvents]);

    // Update the collapsed events when the default collapsed IDs change
    // This effect only depends on defaultCollapsedIds, not eventNodes
    useEffect(() => {
      // Only initialize collapsedEvents if it's empty
      if (!collapsedEvents && defaultCollapsedIds.size > 0) {
        setCollapsedEvents(defaultCollapsedIds);
      }
    }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);

    return (
      <TranscriptVirtualListComponent
        id={id}
        eventNodes={eventNodes}
        initialEventId={initialEventId}
        scrollRef={scrollRef}
        running={running}
      />
    );
  },
);

const collapseFilters: Array<(event: StepEvent | SpanBeginEvent) => boolean> = [
  (event: StepEvent | SpanBeginEvent) => {
    if (event.type === "solver" && event.name === "system_message") {
      return true;
    } else if (kSandboxSignalName === event.name) {
      return true;
    } else if (event.name === "init" || event.name === "sample_init") {
      return true;
    }
    return false;
  },
];

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
          style={{ paddingLeft: `${eventNode.depth * 1}em` }}
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
            eventNode={node as EventNode<SampleInitEvent>}
            className={className}
          />
        );

      case "sample_limit":
        return (
          <SampleLimitEventView
            eventNode={node as EventNode<SampleLimitEvent>}
            className={className}
          />
        );

      case "info":
        return (
          <InfoEventView
            eventNode={node as EventNode<InfoEvent>}
            className={className}
          />
        );

      case "logger":
        return (
          <LoggerEventView
            eventNode={node as EventNode<LoggerEvent>}
            className={className}
          />
        );

      case "model":
        return (
          <ModelEventView
            eventNode={node as EventNode<ModelEvent>}
            className={className}
          />
        );

      case "score":
        return (
          <ScoreEventView
            eventNode={node as EventNode<ScoreEvent>}
            className={className}
          />
        );

      case "state":
        return (
          <StateEventView
            eventNode={node as EventNode<StateEvent>}
            className={className}
          />
        );

      case "span_begin":
        return (
          <SpanEventView
            eventNode={node as EventNode<SpanBeginEvent>}
            children={node.children}
            className={className}
          />
        );

      case "step":
        return (
          <StepEventView
            eventNode={node as EventNode<StepEvent>}
            children={node.children}
            className={className}
          />
        );

      case "store":
        return (
          <StateEventView
            eventNode={node as EventNode<StoreEvent>}
            className={className}
          />
        );

      case "subtask":
        return (
          <SubtaskEventView
            eventNode={node as EventNode<SubtaskEvent>}
            className={className}
          />
        );

      case "tool":
        return (
          <ToolEventView
            eventNode={node as EventNode<ToolEvent>}
            className={className}
            children={node.children}
          />
        );

      case "input":
        return (
          <InputEventView
            eventNode={node as EventNode<InputEvent>}
            className={className}
          />
        );

      case "error":
        return (
          <ErrorEventView
            eventNode={node as EventNode<ErrorEvent>}
            className={className}
          />
        );

      case "approval":
        return (
          <ApprovalEventView
            eventNode={node as EventNode<ApprovalEvent>}
            className={className}
          />
        );

      case "sandbox":
        return (
          <SandboxEventView
            eventNode={node as EventNode<SandboxEvent>}
            className={className}
          />
        );

      default:
        return null;
    }
  },
);
