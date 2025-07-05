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
import { useScrollTrack, useVirtuosoState } from "../../../../state/scrolling";
import { useStore } from "../../../../state/store";
import { flatTree } from "../transform/treeify";

import { useSampleDetailNavigation } from "../../../routing/sampleNavigation";
import { kSandboxSignalName } from "../transform/fixups";
import { OutlineRow } from "./OutlineRow";
import styles from "./TranscriptOutline.module.css";
import {
  collapseScoring,
  collapseTurns,
  makeTurns,
  noScorerChildren,
  removeNodeVisitor,
  removeStepSpanNameVisitor,
} from "./tree-visitors";

const kCollapseScope = "transcript-outline";
const kFramesToStabilize = 10;

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
    uuid: null,
    metadata: null,
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

  // Flag to indicate programmatic scrolling is in progress
  const isProgrammaticScrolling = useRef(false);
  // Last position to check for scroll stabilization
  const lastScrollPosition = useRef<number | null>(null);
  // Frame count for detecting scroll stabilization
  const stableFrameCount = useRef(0);

  useEffect(() => {
    if (sampleDetailNavigation.event) {
      // Set the flag to indicate we're in programmatic scrolling
      isProgrammaticScrolling.current = true;
      lastScrollPosition.current = null;
      stableFrameCount.current = 0;

      setSelectedOutlineId(sampleDetailNavigation.event);

      // Start monitoring to detect when scrolling has stabilized
      const checkScrollStabilized = () => {
        if (!isProgrammaticScrolling.current) return;

        const currentPosition = scrollRef?.current?.scrollTop ?? null;

        if (currentPosition === lastScrollPosition.current) {
          stableFrameCount.current++;

          // If position has been stable for a few frames, consider scrolling complete
          if (stableFrameCount.current >= kFramesToStabilize) {
            isProgrammaticScrolling.current = false;
            return;
          }
        } else {
          // Reset stability counter if position changed
          stableFrameCount.current = 0;
          lastScrollPosition.current = currentPosition;
        }

        // Continue checking until scrolling stabilizes
        requestAnimationFrame(checkScrollStabilized);
      };

      // Start the RAF loop to detect scroll stabilization
      requestAnimationFrame(checkScrollStabilized);
    }
  }, [sampleDetailNavigation.event, setSelectedOutlineId, scrollRef]);

  const outlineNodeList = useMemo(() => {
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

    return collapseScoring(collapseTurns(makeTurns(nodeList)));
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

  // Event node, for scroll tracking
  const allNodesList = useMemo(() => {
    return flatTree(eventNodes, null);
  }, [eventNodes]);

  const elementIds = allNodesList.map((node) => node.id);
  const findNearestOutlineAbove = useCallback(
    (targetId: string): EventNode | null => {
      const targetIndex = allNodesList.findIndex(
        (node) => node.id === targetId,
      );
      if (targetIndex === -1) return null;

      const outlineIds = new Set(outlineNodeList.map((node) => node.id));

      // Search backwards from target position (inclusive)
      for (let i = targetIndex; i >= 0; i--) {
        if (outlineIds.has(allNodesList[i].id)) {
          return allNodesList[i];
        }
      }

      return null;
    },
    [allNodesList, outlineNodeList],
  );

  useScrollTrack(
    elementIds,
    (id: string) => {
      if (!isProgrammaticScrolling.current) {
        // If the ID is not in the list, return
        const parentNode = findNearestOutlineAbove(id);
        if (parentNode) {
          setSelectedOutlineId(parentNode.id);
        }
      }
    },
    scrollRef,
  );

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
        return (
          <div
            className={styles.eventPadding}
            key={node.id}
            style={{ height: "2em" }}
          ></div>
        );
      } else {
        return (
          <OutlineRow
            collapseScope={kCollapseScope}
            node={node}
            key={node.id}
            running={running && index === outlineNodeList.length - 1}
            selected={
              selectedOutlineId ? selectedOutlineId === node.id : index === 0
            }
          />
        );
      }
    },
    [outlineNodeList, running, selectedOutlineId],
  );

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      id={id}
      style={{ ...style }}
      data={[...outlineNodeList, EventPaddingNode]}
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
