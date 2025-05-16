import { FC, memo, RefObject, useEffect, useMemo } from "react";
import {
  ApprovalEvent,
  ErrorEvent,
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
import { EventNode, kTranscriptCollapseScope } from "./types";

import { useStore } from "../../../state/store";
import { SpanEventView } from "./SpanEventView";
import { TranscriptVirtualListComponent } from "./TranscriptVirtualListComponent";
import { flatTree } from "./transform/treeify";

interface TranscriptVirtualListProps {
  id: string;
  eventNodes: EventNode[];
  defaultCollapsedIds: Record<string, boolean>;
  initialEventId: string | null;
  offsetTop?: number;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
  className?: string | string[];
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptVirtualList: FC<TranscriptVirtualListProps> = memo(
  (props) => {
    let {
      id,
      scrollRef,
      eventNodes,
      defaultCollapsedIds,
      running,
      initialEventId,
      offsetTop,
      className,
    } = props;

    // The list of events that have been collapsed
    const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
    const setCollapsedEvents = useStore(
      (state) => state.sampleActions.setCollapsedEvents,
    );

    const flattenedNodes = useMemo(() => {
      // flattten the event tree
      return flatTree(
        eventNodes,
        (collapsedEvents
          ? collapsedEvents[kTranscriptCollapseScope]
          : undefined) || defaultCollapsedIds,
      );
    }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

    // Update the collapsed events when the default collapsed IDs change
    // This effect only depends on defaultCollapsedIds, not eventNodes
    useEffect(() => {
      // Only initialize collapsedEvents if it's empty
      if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
        setCollapsedEvents(kTranscriptCollapseScope, defaultCollapsedIds);
      }
    }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);

    return (
      <TranscriptVirtualListComponent
        id={id}
        eventNodes={flattenedNodes}
        initialEventId={initialEventId}
        offsetTop={offsetTop}
        scrollRef={scrollRef}
        running={running}
        className={className}
      />
    );
  },
);

interface RenderedEventNodeProps {
  node: EventNode;
  className?: string | string[];
}
/**
 * Renders the event based on its type.
 */
export const RenderedEventNode: FC<RenderedEventNodeProps> = memo(
  ({ node, className }) => {
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
            children={node.children}
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
