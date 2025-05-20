import { TYPE_SCORER, TYPE_SCORERS } from "../transform/utils";
import { EventNode } from "../types";

const kTurnType = "turn";

// Visitors are used to transform the event tree
export const removeNodeVisitor = (event: string) => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === event) {
        return [];
      }
      return [node];
    },
  };
};

export const removeStepSpanNameVisitor = (name: string) => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (
        (node.event.event === "step" || node.event.event === "span_begin") &&
        node.event.name === name
      ) {
        return [];
      }
      return [node];
    },
  };
};

export const noScorerChildren = () => {
  let inScorers = false;
  let inScorer = false;
  let currentDepth = -1;
  return {
    visit: (node: EventNode): EventNode[] => {
      // Note once we're in the scorers span
      if (
        node.event.event === "span_begin" &&
        node.event.type === TYPE_SCORERS
      ) {
        inScorers = true;
        return [node];
      }

      if (
        (node.event.event === "step" || node.event.event === "span_begin") &&
        node.event.type === TYPE_SCORER
      ) {
        inScorer = true;
        currentDepth = node.depth;
        return [node];
      }

      if (inScorers && inScorer && node.depth === currentDepth + 1) {
        return [];
      }
      return [node];
    },
  };
};

export const collapseTurns = (eventNodes: EventNode[]): EventNode[] => {
  console.log({ eventNodes });
  const results: EventNode[] = [];
  const collecting: EventNode[] = [];
  const collect = () => {
    if (collecting.length > 0) {
      const numberOfTurns = collecting.length;
      const firstTurn = collecting[0];
      const turnNode = new EventNode(
        firstTurn.id,
        { ...firstTurn.event, name: `${numberOfTurns} turns` },
        firstTurn.depth,
      );
      results.push(turnNode);
      collecting.length = 0;
    }
  };

  for (const node of eventNodes) {
    if (node.event.event === "span_begin" && node.event.type === kTurnType) {
      console.log("turn", collecting.length, node.event.name);
      collecting.push(node);
    } else {
      console.log("collect", collecting.length);
      collect();
      results.push(node);
    }
  }
  // Handle any remaining collected turns
  collect();
  return results;
};

export const collapseMultipleTurnsVisitor = () => {
  const collectedTurns: EventNode[] = [];

  const gatherCollectedTurns = (): EventNode | undefined => {
    if (collectedTurns.length > 0) {
      const numberOfTurns = collectedTurns.length;
      const firstTurn = collectedTurns[0];

      // The collapsed turns
      const turnNode = new EventNode(
        firstTurn.id,
        { ...firstTurn.event, name: `${numberOfTurns} turns` },
        firstTurn.depth,
      );

      // Clear the array
      collectedTurns.length = 0;
      return turnNode;
    } else {
      return undefined;
    }
  };

  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "span_begin" && node.event.type === kTurnType) {
        collectedTurns.push(node);
        return [];
      } else {
        const collectedTurn = gatherCollectedTurns();
        if (collectedTurn) {
          return [collectedTurn, node];
        } else {
          return [node];
        }
      }
    },
    flush: (): EventNode[] => {
      const collectedTurn = gatherCollectedTurns();
      if (collectedTurn) {
        return [collectedTurn];
      }
      return [];
    },
  };
};

export const collapseTurnsVisitor = () => {
  // This visitor combines model events followed by tool events into "turns"
  let pendingModelEvent: EventNode | null = null;
  let collectingToolEvents: EventNode[] = [];
  let turnCount = 1;
  let currentDepth = 0;
  // Track if we've flushed already to avoid duplicate output
  let flushed = false;

  const makeTurn = (modelEvent: EventNode, toolEvents: EventNode[]) => {
    // Create a new "turn" node based on the model event
    const turnNode = new EventNode(
      modelEvent.id,
      {
        id: modelEvent.id,
        event: "span_begin",
        type: kTurnType,
        name: `turn ${turnCount++}`,
        pending: false,
        working_start: modelEvent.event.working_start,
        timestamp: modelEvent.event.timestamp,
        parent_id: null,
        span_id: modelEvent.event.span_id,
      },
      modelEvent.depth,
    );

    // Add the original model event and tool events as children
    turnNode.children = [modelEvent, ...toolEvents];
    return turnNode;
  };

  const shouldCreateTurn = (toolEvents: EventNode[]): boolean => {
    // Only create a turn if there are tool events
    return toolEvents.length > 0;
  };

  const processPendingModelEvents = (): EventNode[] => {
    const result: EventNode[] = [];

    if (pendingModelEvent) {
      // Only create a turn if there are tool events
      if (shouldCreateTurn(collectingToolEvents)) {
        // Create a turn from the pending model and collected tool events
        result.push(makeTurn(pendingModelEvent, collectingToolEvents));
      } else {
        // Otherwise just output the model event as-is
        result.push(pendingModelEvent);
      }

      // Clear the pending model and tools
      pendingModelEvent = null;
      collectingToolEvents = [];
    }

    return result;
  };

  return {
    visit: (node: EventNode): EventNode[] => {
      // Reset turn counter if depth changes
      if (currentDepth !== node.depth) {
        turnCount = 1;
        // Process any pending model at the previous depth
        const result = processPendingModelEvents();
        currentDepth = node.depth;

        // Handle the current node
        if (node.event.event === "model") {
          pendingModelEvent = node;
          return result;
        } else {
          return [...result, node];
        }
      }

      const result: EventNode[] = [];

      if (node.event.event === "model") {
        // If we hit a new model event while already collecting a turn
        // process any pending model event first
        result.push(...processPendingModelEvents());

        // Start collecting a new potential turn with this model event
        pendingModelEvent = node;
      } else if (
        pendingModelEvent &&
        node.event.event === "tool" &&
        pendingModelEvent.depth === node.depth
      ) {
        // We're in the middle of a potential turn and found a tool event at the same depth
        // Add it to our collection of tool events for this turn
        collectingToolEvents.push(node);
        // Don't output anything yet - we'll create the turn when we hit a non-tool/model event
        // or when we reach the end of processing
      } else {
        // We hit a non-model, non-tool event (or a tool at the wrong depth)
        result.push(...processPendingModelEvents());

        // Output the current node as-is
        result.push(node);
      }

      return result;
    },

    flush: (): EventNode[] => {
      // Only process pending events if we haven't flushed already
      if (flushed) {
        return [];
      }

      flushed = true;

      // Handle any remaining model/tools at the end of processing
      return processPendingModelEvents();
    },
  };
};
