import clsx from "clsx";
import { FC, memo, RefObject, useMemo } from "react";
import { Events } from "../../../@types/log";
import { StickyScroll } from "../../../components/StickyScroll";
import { useCollapsedState } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { ApplicationIcons } from "../../appearance/icons";
import { useLogRouteParams } from "../../routing/url";
import { TranscriptOutline } from "./outline/TranscriptOutline";
import styles from "./TranscriptPanel.module.css";
import { TranscriptVirtualList } from "./TranscriptVirtualList";
import { useEventNodes } from "./transform/hooks";

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

  const { logPath } = useLogRouteParams();

  const [collapsed, setCollapsed] = useCollapsedState(
    `transcript-panel-${logPath || "na"}`,
    false,
  );

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
        eventNodes={eventNodes}
        defaultCollapsedIds={defaultCollapsedIds}
        scrollRef={scrollRef}
        running={running}
        initialEventId={initialEventId === undefined ? null : initialEventId}
        offsetTop={topOffset}
        className={styles.listContainer}
      />
    </div>
  );
});
