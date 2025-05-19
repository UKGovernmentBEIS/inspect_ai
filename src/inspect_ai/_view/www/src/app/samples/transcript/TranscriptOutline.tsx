import {
  CSSProperties,
  FC,
  ReactNode,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";

import { ApplicationIcons } from "../../appearance/icons";
import { EventNode } from "./types";

import clsx from "clsx";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { useCollapseSampleEvent, useSamplePopover } from "../../../state/hooks";
import { useVirtuosoState } from "../../../state/scrolling";
import { useStore } from "../../../state/store";
import { flatTree } from "./transform/treeify";

import { Link, useParams } from "react-router-dom";

import { PopOver } from "../../../components/PopOver";
import { PulsingDots } from "../../../components/PulsingDots";
import { parsePackageName } from "../../../utils/python";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { sampleEventUrl } from "../../routing/url";
import styles from "./TranscriptOutline.module.css";
import { kSandboxSignalName } from "./transform/fixups";
import { TYPE_SCORER, TYPE_SCORERS } from "./transform/utils";

const kCollapseScope = "transcript-outline";

interface TranscriptOutlineProps {
  eventNodes: EventNode[];
  defaultCollapsedIds: Record<string, boolean>;
  running?: boolean;
  className?: string | string[];
  scrollRef?: RefObject<HTMLDivElement | null>;
  style?: CSSProperties;
}

// hack: add a padding node to the end of the list so
// when the tree is positioned at the bottom of the viewport
// it has some breathing room
const EventPaddingNode: EventNode = {
  id: "padding",
  event: {
    event: "info",
    source: "",
    data: "",
    timestamp: "",
    pending: false,
    working_start: 0,
    span_id: null,
  },
  depth: 0,
  children: [],
};

export const TranscriptOutline: FC<TranscriptOutlineProps> = ({
  eventNodes,
  defaultCollapsedIds,
  running,
  className,
  scrollRef,
  style,
}) => {
  const id = "transcript-tree";
  // The virtual list handle and state
  const listHandle = useRef<VirtuosoHandle | null>(null);
  const { getRestoreState } = useVirtuosoState(listHandle, id);

  // Collapse state
  // The list of events that have been collapsed
  const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
  const setCollapsedEvents = useStore(
    (state) => state.sampleActions.setCollapsedEvents,
  );

  const flattenedNodes = useMemo(() => {
    // flattten the event tree
    const nodeList = flatTree(
      eventNodes,
      (collapsedEvents ? collapsedEvents[kCollapseScope] : undefined) ||
        defaultCollapsedIds,
      [
        // Strip specific nodes
        removeNodeVisitor("logger"),
        removeNodeVisitor("info"),
        removeNodeVisitor("state"),
        removeNodeVisitor("store"),
        removeNodeVisitor("approval"),
        removeNodeVisitor("input"),

        // Strip the sandbox wrapper (and children)
        removeStepSpanNameVisitor(kSandboxSignalName),

        // Collapse model calls into turns
        collapseTurnsVisitor(),

        // Collapse turns into a single node for sequential runs
        // of turns
        collapseMultipleTurnsVisitor(),

        // Remove any leftover bare model calls that aren't in turns
        removeNodeVisitor("model"),

        // Remove child events for scorers
        noScorerChildren(),
      ],
    );

    return nodeList;
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

  // Update the collapsed events when the default collapsed IDs change
  // This effect only depends on defaultCollapsedIds, not eventNodes
  useEffect(() => {
    // Only initialize collapsedEvents if it's empty
    if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
      setCollapsedEvents(kCollapseScope, defaultCollapsedIds);
    }
  }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);

  const renderRow = useCallback(
    (index: number, node: EventNode) => {
      if (node === EventPaddingNode) {
        return <div className={styles.eventPadding} key={node.id} />;
      } else {
        return (
          <TreeNode
            node={node}
            key={node.id}
            running={running && index === flattenedNodes.length - 1}
          />
        );
      }
    },
    [flattenedNodes],
  );

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      id={id}
      style={{ ...style }}
      data={[...flattenedNodes, EventPaddingNode]}
      defaultItemHeight={50}
      itemContent={renderRow}
      atBottomThreshold={30}
      increaseViewportBy={{ top: 300, bottom: 300 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      className={clsx(className, "transcript-outline")}
      skipAnimationFrameInResizeObserver={true}
      restoreStateFrom={getRestoreState()}
      tabIndex={0}
    />
  );
};

interface TreeNodeProps {
  node: EventNode;
  running?: boolean;
}
const TreeNode: FC<TreeNodeProps> = ({ node, running }) => {
  const [collapsed, setCollapsed] = useCollapseSampleEvent(
    kCollapseScope,
    node.id,
  );
  const icon = iconForNode(node);
  const toggle = toggleIcon(node, collapsed);

  const popoverId = `${node.id}-popover`;
  const { show, hide, isShowing } = useSamplePopover(popoverId);

  const ref = useRef(null);

  // Get all URL parameters at component level
  const { logPath, sampleId, epoch } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const url = logPath
    ? sampleEventUrl(node.id, logPath, sampleId, epoch)
    : undefined;

  return (
    <>
      <div
        className={clsx(styles.eventRow, "text-size-smallest")}
        style={{ paddingLeft: `${node.depth * 0.4}em` }}
        onMouseOver={show}
        onMouseLeave={hide}
      >
        <div
          className={clsx(styles.toggle)}
          onClick={() => {
            setCollapsed(!collapsed);
          }}
        >
          {toggle ? <i className={clsx(toggle)} /> : undefined}
        </div>
        <div className={clsx(styles.label)} data-depth={node.depth}>
          {icon ? <i className={clsx(icon, styles.icon)} /> : undefined}
          {url ? (
            <Link to={url} className={clsx(styles.eventLink)} ref={ref}>
              {parsePackageName(labelForNode(node)).module}
            </Link>
          ) : (
            <span ref={ref}>{parsePackageName(labelForNode(node)).module}</span>
          )}
          {running ? (
            <PulsingDots
              size="small"
              className={clsx(styles.progress)}
              subtle={false}
            />
          ) : undefined}
        </div>
      </div>
      <PopOver
        id={`${node.id}-popover`}
        positionEl={ref.current}
        isOpen={isShowing}
        className={clsx(styles.popper)}
        placement="auto-end"
      >
        {summarizeNode(node)}
      </PopOver>
    </>
  );
};

const toggleIcon = (
  node: EventNode,
  collapsed: boolean,
): string | undefined => {
  if (node.children.length > 0) {
    return collapsed
      ? ApplicationIcons.chevron.right
      : ApplicationIcons.chevron.down;
  }
};

const iconForNode = (node: EventNode): string | undefined => {
  switch (node.event.event) {
    case "sample_limit":
      return ApplicationIcons.limits.custom;

    case "score":
      return ApplicationIcons.scorer;

    case "error":
      return ApplicationIcons.error;
  }
};

const labelForNode = (node: EventNode): string => {
  if (node.event.event === "span_begin") {
    switch (node.event.type) {
      case "solver":
        return node.event.name;
      case "tool":
        return node.event.name;
      default: {
        if (node.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node.event.name;
      }
    }
  } else {
    switch (node.event.event) {
      case "subtask":
        return node.event.name;
      case "approval":
        switch (node.event.decision) {
          case "approve":
            return "approved";
          case "reject":
            return "rejected";
          case "escalate":
            return "escalated";
          case "modify":
            return "modified";
          case "terminate":
            return "terminated";
          default:
            return node.event.decision;
        }
      case "model":
        return `model${node.event.role ? ` (${node.event.role})` : ""}`;
      case "score":
        return "scoring";
      case "step":
        if (node.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node.event.name;

      default:
        return node.event.event;
    }
  }
};

// Visitors are used to transform the event tree

const removeNodeVisitor = (event: string) => {
  return {
    visit: (node: EventNode, parent?: EventNode): EventNode[] => {
      if (node.event.event === event) {
        return removeNode(node, parent);
      }
      return [node];
    },
  };
};

const removeStepSpanNameVisitor = (name: string) => {
  return {
    visit: (node: EventNode, parent?: EventNode): EventNode[] => {
      if (
        (node.event.event === "step" || node.event.event === "span_begin") &&
        node.event.name === name
      ) {
        return removeNode(node, parent);
      }
      return [node];
    },
  };
};

const noScorerChildren = () => {
  let inScorers = false;
  let inScorer = false;
  let currentDepth = -1;
  return {
    visit: (node: EventNode, parent?: EventNode): EventNode[] => {
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
        return removeNode(node, parent);
      }
      return [node];
    },
  };
};

const summarizeNode = (node: EventNode): ReactNode => {
  const entries: Record<string, unknown> = {
    id: node.id,
    event: node.event.event,
    start: node.event.working_start,
    timestamp: node.event.timestamp,
  };
  return (
    <MetaDataGrid
      entries={entries}
      size="mini"
      className={clsx(styles.popover, "text-size-smallest")}
    />
  );
};

const kTurnType = "type";

const collapseMultipleTurnsVisitor = () => {
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

const collapseTurnsVisitor = () => {
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

const removeNode = (node: EventNode, parent?: EventNode): EventNode[] => {
  if (parent) {
    parent.children = parent.children.filter((child) => child.id !== node.id);
  }
  return [];
};
