import clsx from "clsx";
import { FC, memo, RefObject, useEffect, useMemo, useRef } from "react";
import { VirtuosoHandle } from "react-virtuoso";
import { Events } from "../../../@types/log";
import { StickyScroll } from "../../../components/StickyScroll";
import { useCollapsedState } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { ApplicationIcons } from "../../appearance/icons";
import { useLogRouteParams } from "../../routing/url";
import { TranscriptOutline } from "./outline/TranscriptOutline";
import styles from "./TranscriptPanel.module.css";
import { TranscriptVirtualList } from "./TranscriptVirtualList";
import { flatTree as flattenTree } from "./transform/flatten";
import { useEventNodes } from "./transform/hooks";
import { hasSpans } from "./transform/utils";
import { kTranscriptCollapseScope } from "./types";

interface TranscriptPanelProps {
  id: string;
  events: Events;
  scrollRef: RefObject<HTMLDivElement | null>;
  running?: boolean;
  initialEventId?: string | null;
  topOffset?: number;
}

/**
 * Renders the Transcript Virtual List.
 */
export const TranscriptPanel: FC<TranscriptPanelProps> = memo((props) => {
  let { id, scrollRef, events, running, initialEventId, topOffset } = props;

  // Sort out any types that are filtered out
  const filteredEventTypes = useStore(
    (state) => state.sample.eventFilter.filteredTypes,
  );

  // Apply the filter
  const filteredEvents = useMemo(() => {
    if (filteredEventTypes.length === 0) {
      return events;
    }
    return events.filter((event) => {
      return !filteredEventTypes.includes(event.event);
    });
  }, [events, filteredEventTypes]);

  // Convert to nodes
  const { eventNodes, defaultCollapsedIds } = useEventNodes(
    filteredEvents,
    running === true,
  );

  // The list of events that have been collapsed
  const collapsedEvents = useStore((state) => state.sample.collapsedEvents);
  const setCollapsedEvents = useStore(
    (state) => state.sampleActions.setCollapsedEvents,
  );

  const flattenedNodes = useMemo(() => {
    // flattten the event tree
    return flattenTree(
      eventNodes,
      (collapsedEvents
        ? collapsedEvents[kTranscriptCollapseScope]
        : undefined) || defaultCollapsedIds,
    );
  }, [eventNodes, collapsedEvents, defaultCollapsedIds]);

  // Update the collapsed events when the default collapsed IDs change
  // This effect only depends on defaultCollapsedIds, not eventNodes

  const collapsedMode = useStore((state) => state.sample.collapsedMode);

  useEffect(() => {
    if (events.length <= 0 || collapsedMode !== null) {
      return;
    }

    if (!collapsedEvents && Object.keys(defaultCollapsedIds).length > 0) {
      setCollapsedEvents(kTranscriptCollapseScope, defaultCollapsedIds);
    }
  }, [defaultCollapsedIds, collapsedEvents, setCollapsedEvents]);

  const allNodesList = useMemo(() => {
    return flattenTree(eventNodes, null);
  }, [eventNodes]);

  useEffect(() => {
    if (events.length <= 0 || collapsedMode === null) {
      return;
    }

    const collapseIds: Record<string, boolean> = {};
    const collapsed = collapsedMode === "collapsed";

    allNodesList.forEach((node) => {
      if (
        node.event.uuid &&
        ((collapsed && !hasSpans(node.children.map((child) => child.event))) ||
          !collapsed)
      ) {
        collapseIds[node.event.uuid] = collapsedMode === "collapsed";
      }
    });

    setCollapsedEvents(kTranscriptCollapseScope, collapseIds);
  }, [collapsedMode, events, allNodesList]);

  const { logPath } = useLogRouteParams();
  const [collapsed, setCollapsed] = useCollapsedState(
    `transcript-panel-${logPath || "na"}`,
    false,
  );

  const listHandle = useRef<VirtuosoHandle | null>(null);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        if (event.key === "ArrowUp") {
          listHandle.current?.scrollToIndex({ index: 0, align: "center" });
          event.preventDefault();
        } else if (event.key === "ArrowDown") {
          listHandle.current?.scrollToIndex({
            index: Math.max(flattenedNodes.length - 5, 0),
            align: "center",
            behavior: "auto",
          });

          // This is needed to allow measurement to complete before finding
          // the last item to scroll to it properly. The timing isn't magical sadly
          // it is just a heuristic.
          setTimeout(() => {
            listHandle.current?.scrollToIndex({
              index: Math.max(flattenedNodes.length - 1, 0),
              align: "end",
              behavior: "auto",
            });
          }, 250);
        }
      }
    };

    const scrollElement = scrollRef.current;
    if (scrollElement) {
      scrollElement.addEventListener("keydown", handleKeyDown);
      // Make the element focusable so it can receive keyboard events
      if (!scrollElement.hasAttribute("tabIndex")) {
        scrollElement.setAttribute("tabIndex", "0");
      }

      return () => {
        scrollElement.removeEventListener("keydown", handleKeyDown);
      };
    }
  }, [scrollRef, flattenedNodes]);

  return (
    <div
      className={clsx(
        styles.container,
        collapsed ? styles.collapsed : undefined,
      )}
    >
      <StickyScroll
        scrollRef={scrollRef}
        className={styles.treeContainer}
        offsetTop={topOffset}
      >
        <TranscriptOutline
          className={clsx(styles.outline)}
          eventNodes={eventNodes}
          running={running}
          defaultCollapsedIds={defaultCollapsedIds}
          scrollRef={scrollRef}
        />
        <div
          className={styles.outlineToggle}
          onClick={() => setCollapsed(!collapsed)}
        >
          <i className={ApplicationIcons.sidebar} />
        </div>
      </StickyScroll>
      <TranscriptVirtualList
        id={id}
        listHandle={listHandle}
        eventNodes={flattenedNodes}
        scrollRef={scrollRef}
        running={running}
        initialEventId={initialEventId === undefined ? null : initialEventId}
        offsetTop={topOffset}
        className={styles.listContainer}
      />
    </div>
  );
});
