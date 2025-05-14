import { useMemo } from "react";
import {
  Events,
  SpanBeginEvent,
  StepEvent,
  SubtaskEvent,
  ToolEvent,
} from "../../../../@types/log";
import { EventNode } from "../types";
import { fixupEventStream, kSandboxSignalName } from "./fixups";
import { treeifyEvents } from "./treeify";

export const useEventNodes = (events: Events, running: boolean) => {
  // Normalize Events in a flattened filtered list
  const { eventTree, defaultCollapsedIds } = useMemo((): {
    eventTree: EventNode[];
    defaultCollapsedIds: Record<string, true>;
  } => {
    // Apply fixups to the event string
    const resolvedEvents = fixupEventStream(events, !running);

    // Build the event tree
    const eventTree = treeifyEvents(resolvedEvents, 0);

    // Apply collapse filters to the event tree
    const defaultCollapsedIds: Record<string, true> = {};
    const findCollapsibleEvents = (nodes: EventNode[]) => {
      for (const node of nodes) {
        if (
          (node.event.event === "step" ||
            node.event.event === "span_begin" ||
            node.event.event === "tool" ||
            node.event.event === "subtask") &&
          collapseFilters.some((filter) =>
            filter(
              node.event as
                | StepEvent
                | SpanBeginEvent
                | ToolEvent
                | SubtaskEvent,
            ),
          )
        ) {
          defaultCollapsedIds[node.id] = true;
        }

        // Recursively check children
        findCollapsibleEvents(node.children);
      }
    };
    findCollapsibleEvents(eventTree);

    return { eventTree, defaultCollapsedIds };
  }, [events, running]);

  return { eventNodes: eventTree, defaultCollapsedIds };
};

const collapseFilters: Array<
  (event: StepEvent | SpanBeginEvent | ToolEvent | SubtaskEvent) => boolean
> = [
  (event: StepEvent | SpanBeginEvent | ToolEvent | SubtaskEvent) =>
    event.type === "solver" && event.name === "system_message",
  (event: StepEvent | SpanBeginEvent | ToolEvent | SubtaskEvent) => {
    if (event.event === "step" || event.event === "span_begin") {
      return (
        event.name === kSandboxSignalName ||
        event.name === "init" ||
        event.name === "sample_init"
      );
    }
    return false;
  },
  (event: StepEvent | SpanBeginEvent | ToolEvent | SubtaskEvent) =>
    event.event === "tool" && !event.agent && !event.failed,
  (event: StepEvent | SpanBeginEvent | ToolEvent | SubtaskEvent) =>
    event.event === "subtask",
];
