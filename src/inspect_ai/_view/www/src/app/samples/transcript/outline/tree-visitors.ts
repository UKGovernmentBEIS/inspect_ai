import { ScoreEvent, SpanBeginEvent } from "../../../../@types/log";
import { TYPE_SCORER, TYPE_SCORERS } from "../transform/utils";
import { EventNode } from "../types";

const kTurnType = "turn";
const kTurnsType = "turns";
const kCollapsedScoring = "scorings";

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

export const makeTurns = (eventNodes: EventNode[]): EventNode[] => {
  const results: EventNode[] = [];
  let modelNode: EventNode | null = null;
  const toolNodes: EventNode[] = [];
  let turnCount = 1;

  const makeTurn = (force?: boolean) => {
    if (modelNode !== null && (force || toolNodes.length > 0)) {
      // Create a new "turn" node based on the model event
      const turnNode = new EventNode(
        modelNode.id,
        {
          id: modelNode.id,
          event: "span_begin",
          type: kTurnType,
          name: `turn ${turnCount++}`,
          pending: false,
          working_start: modelNode.event.working_start,
          timestamp: modelNode.event.timestamp,
          parent_id: null,
          span_id: modelNode.event.span_id,
          uuid: null,
          metadata: null,
        },
        modelNode.depth,
      );

      // Add the original model event and tool events as children
      turnNode.children = [modelNode, ...toolNodes];
      results.push(turnNode);
    }
    modelNode = null;
    toolNodes.length = 0;
  };

  for (const node of eventNodes) {
    if (node.event.event === "model") {
      if (modelNode !== null && toolNodes.length === 0) {
        // back to back model calls are considered a single turn
        makeTurn(true);
      } else {
        makeTurn();
        modelNode = node;
      }
    } else if (node.event.event === "tool") {
      toolNodes.push(node);
    } else {
      makeTurn();
      results.push(node);
    }
  }
  makeTurn();

  return results;
};

export const collapseTurns = (eventNodes: EventNode[]): EventNode[] => {
  const results: EventNode[] = [];
  const collecting: EventNode[] = [];
  const collect = () => {
    if (collecting.length > 0) {
      const numberOfTurns = collecting.length;
      const firstTurn = collecting[0];
      const turnNode = new EventNode(
        firstTurn.id,
        {
          ...(firstTurn.event as SpanBeginEvent),
          name: `${numberOfTurns} ${numberOfTurns === 1 ? "turn" : "turns"}`,
          type: kTurnsType,
        },
        firstTurn.depth,
      );
      results.push(turnNode);
      collecting.length = 0;
    }
  };

  for (const node of eventNodes) {
    if (node.event.event === "span_begin" && node.event.type === kTurnType) {
      // Check depth to ensure we are collecting turns at the same level
      if (collecting.length > 0 && collecting[0].depth !== node.depth) {
        collect();
      }

      collecting.push(node);
    } else {
      collect();
      results.push(node);
    }
  }
  // Handle any remaining collected turns
  collect();
  return results;
};

export const collapseScoring = (eventNodes: EventNode[]): EventNode[] => {
  const results: EventNode[] = [];
  const collecting: EventNode[] = [];
  const collect = () => {
    if (collecting.length > 0) {
      const firstScore = collecting[0];
      const turnNode = new EventNode(
        firstScore.id,
        {
          ...(firstScore.event as ScoreEvent),
          name: "scoring",
          type: kCollapsedScoring,
        },
        firstScore.depth,
      );
      results.push(turnNode);
      collecting.length = 0;
    }
  };

  for (const node of eventNodes) {
    if (node.event.event === "score") {
      collecting.push(node);
    } else {
      collect();
      results.push(node);
    }
  }

  // Handle any remaining collected turns
  collect();
  return results;
};
