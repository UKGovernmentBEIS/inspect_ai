import {
  CSSProperties,
  FC,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";

import { EventNode } from "../types";

import clsx from "clsx";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { useVirtuosoState } from "../../../../state/scrolling";
import { useStore } from "../../../../state/store";
import { flatTree } from "../transform/treeify";

import { useSampleDetailNavigation } from "../../../routing/navigationHooks";
import { kSandboxSignalName } from "../transform/fixups";
import { OutlineRow } from "./OutlineRow";
import styles from "./TranscriptOutline.module.css";
import {
  collapseTurns,
  makeTurns,
  noScorerChildren,
  removeNodeVisitor,
  removeStepSpanNameVisitor,
} from "./tree-visitors";

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

  const selectedOutlineId = useStore((state) => state.sample.selectedOutlineId);
  const setSelectedOutlineId = useStore(
    (state) => state.sampleActions.setSelectedOutlineId,
  );
  const sampleDetailNavigation = useSampleDetailNavigation();

  useEffect(() => {
    if (sampleDetailNavigation.event) {
      setSelectedOutlineId(sampleDetailNavigation.event);
    }
  }, [sampleDetailNavigation.event]);

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
        removeNodeVisitor("sandbox"),

        // Strip the sandbox wrapper (and children)
        removeStepSpanNameVisitor(kSandboxSignalName),

        // Remove child events for scorers
        noScorerChildren(),
      ],
    );

    return collapseTurns(makeTurns(nodeList));
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

  const outlineIds = flattenedNodes.map((n) => n.id);

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
          <OutlineRow
            collapseScope={kCollapseScope}
            node={node}
            key={node.id}
            running={running && index === flattenedNodes.length - 1}
            selected={
              selectedOutlineId ? selectedOutlineId === node.id : index === 0
            }
          />
        );
      }
    },
    [flattenedNodes, running, selectedOutlineId],
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
