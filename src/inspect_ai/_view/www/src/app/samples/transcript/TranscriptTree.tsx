import { FC, RefObject, useCallback, useEffect, useMemo, useRef } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { EventNode } from "./types";

import clsx from "clsx";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { useCollapseSampleEvent } from "../../../state/hooks";
import { useVirtuosoState } from "../../../state/scrolling";
import { useStore } from "../../../state/store";
import { flatTree } from "./transform/treeify";

import styles from "./TranscriptTree.module.css";
import { kSandboxSignalName } from "./transform/fixups";

interface TranscriptTreeProps {
  eventNodes: EventNode[];
  defaultCollapsedIds: Record<string, boolean>;
  className?: string | string[];
  scrollRef?: RefObject<HTMLDivElement | null>;
}

export const TranscriptTree: FC<TranscriptTreeProps> = ({
  eventNodes,
  defaultCollapsedIds,
  className,
  scrollRef,
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
      collapsedEvents || defaultCollapsedIds,
      [
        noLogVisitor(),
        noInfoVisitor(),
        noSandboxVisitor(),
        noStateVisitor(),
        noStoreVisitor(),
        collapseTurnsVisitor(),
      ],
    );

    return nodeList;
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

  // Update the collapsed events when the default collapsed IDs change
  // This effect only depends on defaultCollapsedIds, not eventNodes
  useEffect(() => {
    // Only initialize collapsedEvents if it's empty
    if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
      setCollapsedEvents(defaultCollapsedIds);
    }
  }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);

  const renderRow = useCallback((index: number, node: EventNode) => {
    return <EventRow node={node} key={node.id} />;
  }, []);

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      id={id}
      style={{ height: "100%" }}
      data={flattenedNodes}
      defaultItemHeight={50}
      itemContent={renderRow}
      atBottomThreshold={30}
      increaseViewportBy={{ top: 300, bottom: 300 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      className={clsx(className, "samples-list")}
      skipAnimationFrameInResizeObserver={true}
      restoreStateFrom={getRestoreState()}
      tabIndex={0}
    />
  );
};

interface EventRowProps {
  node: EventNode;
}
const EventRow: FC<EventRowProps> = ({ node }) => {
  const [collapsed, setCollapsed] = useCollapseSampleEvent(node.id);
  const icon = iconForNode(node, collapsed);
  return (
    <div
      className={clsx(styles.eventRow, "text-size-smaller")}
      onClick={() => {
        setCollapsed(!collapsed);
      }}
    >
      <div className={clsx(styles.toggle)}>
        {icon ? <i className={clsx(icon)} /> : undefined}
      </div>
      <div
        data-depth={node.depth}
        style={{ paddingLeft: `${node.depth * 0.4}em` }}
      >
        {labelForNode(node)}
      </div>
    </div>
  );
};

const iconForNode = (
  node: EventNode,
  collapsed: boolean,
): string | undefined => {
  return node.children.length > 0
    ? collapsed
      ? ApplicationIcons.chevron.right
      : ApplicationIcons.chevron.down
    : undefined;
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

const noLogVisitor = () => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "logger") {
        return [];
      }
      return [node];
    },
  };
};

const noInfoVisitor = () => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "info") {
        return [];
      }
      return [node];
    },
  };
};

const noSandboxVisitor = () => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (
        (node.event.event === "step" || node.event.event === "span_begin") &&
        node.event.name === kSandboxSignalName
      ) {
        return [];
      }
      return [node];
    },
  };
};

const noStateVisitor = () => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "state") {
        return [];
      }
      return [node];
    },
  };
};

const noStoreVisitor = () => {
  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "store") {
        return [];
      }
      return [node];
    },
  };
};

const collapseTurnsVisitor = () => {
  let startTurn: EventNode | null = null;
  let turnCount = 1;
  let currentDepth = 0;

  return {
    visit: (node: EventNode): EventNode[] => {
      if (node.event.event === "tool") {
        console.log({ currentDepth, scope: node.event.span_id });
      }
      if (currentDepth !== node.depth) {
        turnCount = 1;
      }
      currentDepth = node.depth;

      const result: EventNode[] = [];
      if (node.event.event === "model") {
        if (startTurn) {
          result.push(startTurn);
        }
        startTurn = node;
      } else if (
        startTurn &&
        node.event.event === "tool" &&
        startTurn.depth === node.depth
      ) {
        result.push(
          new EventNode(
            startTurn.id,
            {
              id: startTurn.id,
              event: "span_begin",
              type: "turn",
              name: `turn ${turnCount++}`,
              pending: false,
              working_start: startTurn.event.working_start,
              timestamp: startTurn.event.timestamp,
              parent_id: null,
              span_id: startTurn.event.span_id,
            },
            startTurn.depth,
          ),
        );
        startTurn = null;
      } else {
        if (startTurn) {
          result.push(startTurn);
          startTurn = null;
        }
        result.push(node);
      }
      return result;
    },
  };
};
