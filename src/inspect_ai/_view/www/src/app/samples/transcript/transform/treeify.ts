import { Events, SpanBeginEvent } from "../../../../@types/log";
import { EventNode, EventType } from "../types";

// Special name for task grouping spans
export const kTaskGroupName = "task-group";

// Group events by Task id
export function groupEventsByTaskId(events: EventNode[]): EventNode[] {
  if (!events || events.length === 0) {
    return events;
  }

  // Gather events into task groups
  const taskGroups = new Map<number, EventNode[]>();
  const untaskedEvents: EventNode[] = [];

  for (const event of events) {
    const taskId = event.event.task_id;

    // Keep track of events without a task_id
    if (taskId === null || taskId === undefined) {
      untaskedEvents.push(event);
      continue;
    }

    // Add this event to the task group
    if (!taskGroups.has(taskId)) {
      taskGroups.set(taskId, []);
    }
    taskGroups.get(taskId)?.push(event);
  }

  // If we have no task groups or only a single task group,
  // return the original events as the task grouping doesn't really
  // add anything
  if (taskGroups.size === 0 || taskGroups.size === 1) {
    return events;
  }

  // Create artificial spans for each task group
  const result: EventNode[] = [];

  // Then add a span for each task group
  for (const taskId of taskGroups.keys()) {
    const events = taskGroups.get(taskId);
    if (!events || events?.length === 0) {
      // empty task
      continue;
    }

    const firstEvent = events[0];
    const spanBeginEvent: SpanBeginEvent = {
      event: "span_begin",
      id: `task-group-${taskId}`,
      parent_id: null,
      type: kTaskGroupName,
      name: `Task ${taskId}`,
      span_id: null,
      task_id: taskId as number, // Ensure it's non-null
      timestamp: firstEvent.event.timestamp,
      working_start: firstEvent.event.working_start,
      pending: false,
    };
    const spanNode = new EventNode(spanBeginEvent, firstEvent.depth);
    spanNode.children = events.sort((a, b) => {
      return a.event.timestamp.localeCompare(b.event.timestamp);
    });
    result.push(spanNode);
  }

  // Add the ungrouped events last
  result.push(...untaskedEvents);

  return result;
}

/**
 * Gathers events into a hierarchy of EventNodes.
 */
export function treeifyEvents(events: Events, depth: number): EventNode[] {
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
    switch (event.event) {
      case "step":
        if (event.action === "begin") {
          // Starting a new step
          const node = pushNode(event);
          stack.push(node);
        } else {
          // An ending step
          if (stack.length > 0) {
            stack.pop();
          }
        }
        break;
      case "span_begin": {
        const node = pushNode(event);
        stack.push(node);
        break;
      }
      case "span_end": {
        // group child events by task
        const parentNode = stack[stack.length - 1];
        const groupedEvents = groupEventsByTaskId(parentNode.children);
        parentNode.children = groupedEvents;

        if (stack.length > 0) {
          stack.pop();
        }
        break;
      }
      default:
        // An event
        pushNode(event);
        break;
    }
  });

  return rootNodes;
}
