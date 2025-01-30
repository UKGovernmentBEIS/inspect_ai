import clsx from "clsx";
import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import styles from "./VirtualList.module.css";

export interface VirtualListRef {
  focus: () => void;
  scrollToIndex: (index: number, direction?: "up" | "down") => void;
}

interface VirtualListProps<T> {
  data: T[];
  renderRow: (item: T, index: number) => React.ReactNode;
  overscanCount?: number;
  initialEstimatedRowHeight?: number;
  sync?: boolean;
  scrollRef?: React.RefObject<HTMLElement | null>;
  className?: string;
  style?: React.CSSProperties;
  tabIndex?: number;
  onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}

interface ListMetrics {
  rowHeights: Map<number, number>;
  totalHeight: number;
  estimatedRowHeight: number;
}

export const VirtualList = forwardRef(function VirtualList<T>(
  {
    data,
    renderRow,
    overscanCount = 15,
    initialEstimatedRowHeight = 50,
    sync = false,
    scrollRef,
    onKeyDown,
    ...props
  }: VirtualListProps<T>,
  ref: React.Ref<VirtualListRef>,
) {
  const [height, setHeight] = useState(0);
  const [offset, setOffset] = useState(0);
  const [listMetrics, setListMetrics] = useState<ListMetrics>({
    rowHeights: new Map(),
    totalHeight: data.length * initialEstimatedRowHeight,
    estimatedRowHeight: initialEstimatedRowHeight,
  });

  const baseRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<Map<number, HTMLElement>>(new Map());

  const getRowHeight = (index: number): number => {
    return listMetrics.rowHeights.get(index) || listMetrics.estimatedRowHeight;
  };

  // Calculate new estimated height based on measured rows
  const calculateEstimatedHeight = (heights: Map<number, number>): number => {
    if (heights.size === 0) return listMetrics.estimatedRowHeight;

    // Calculate average of measured heights
    let sum = 0;
    heights.forEach((height) => {
      sum += height;
    });

    // Use exponential moving average to smooth transitions
    const alpha = 0.2; // Smoothing factor
    const newEstimate = sum / heights.size;
    return Math.round(
      alpha * newEstimate + (1 - alpha) * listMetrics.estimatedRowHeight,
    );
  };

  const rowPositions = useMemo(() => {
    let currentPosition = 0;
    const positions = new Map<number, number>();

    for (let i = 0; i < data.length; i++) {
      positions.set(i, currentPosition);
      currentPosition += getRowHeight(i);
    }

    return positions;
  }, [listMetrics.rowHeights, listMetrics.estimatedRowHeight, data.length]);

  // Measure rendered rows and update heights if needed
  const measureRows = () => {
    let updates: [number, number][] = [];

    rowRefs.current.forEach((element, index) => {
      if (element) {
        const measuredHeight = element.offsetHeight;
        if (
          measuredHeight &&
          measuredHeight !== listMetrics.rowHeights.get(index)
        ) {
          updates.push([index, measuredHeight]);
        }
      }
    });

    if (updates.length === 0) return;

    const newHeights = new Map(listMetrics.rowHeights);
    updates.forEach(([index, height]) => {
      newHeights.set(index, height);
    });

    // Calculate new estimated height
    const newEstimatedHeight = calculateEstimatedHeight(newHeights);

    let newTotalHeight = 0;
    for (let i = 0; i < data.length; i++) {
      newTotalHeight += newHeights.get(i) || newEstimatedHeight;
    }

    setListMetrics({
      rowHeights: newHeights,
      totalHeight: newTotalHeight,
      estimatedRowHeight: newEstimatedHeight,
    });
  };

  useImperativeHandle(
    ref,
    () => ({
      focus: () => {
        baseRef.current?.focus();
      },
      scrollToIndex: (index: number, direction?: "up" | "down") => {
        const scrollElement = scrollRef?.current || baseRef.current;
        if (!scrollElement || index < 0 || index >= data.length) return;

        const currentScrollTop = scrollElement.scrollTop;
        const viewportHeight = scrollElement.offsetHeight;

        const rowTop = rowPositions.get(index) || 0;
        const rowHeight = getRowHeight(index);
        const rowBottom = rowTop + rowHeight;

        const isVisible =
          rowTop >= currentScrollTop &&
          rowBottom <= currentScrollTop + viewportHeight;
        if (isVisible) return;

        let newScrollTop: number;
        if (direction === "up") {
          newScrollTop = rowTop;
        } else {
          newScrollTop = rowBottom - viewportHeight;
        }

        newScrollTop = Math.max(
          0,
          Math.min(newScrollTop, listMetrics.totalHeight - viewportHeight),
        );
        scrollElement.scrollTop = newScrollTop;
      },
    }),
    [rowPositions, data.length],
  );

  const resize = () => {
    const scrollElement = scrollRef?.current || baseRef.current;
    if (scrollElement && height !== scrollElement.offsetHeight) {
      setHeight(scrollElement.offsetHeight);
    }
  };

  const handleScroll = throttle(() => {
    const scrollElement = scrollRef?.current || baseRef.current;
    if (scrollElement) {
      setOffset(scrollElement.scrollTop);
    }
    if (sync) {
      setOffset((prev) => prev);
    }
  }, 100);

  useEffect(() => {
    resize();
    const scrollElement = scrollRef?.current || baseRef.current;

    if (scrollElement) {
      scrollElement.addEventListener("scroll", handleScroll);
      window.addEventListener("resize", resize);

      return () => {
        scrollElement.removeEventListener("scroll", handleScroll);
        window.removeEventListener("resize", resize);
      };
    }
  }, [scrollRef?.current]);

  useEffect(() => {
    measureRows();
  });

  const findRowAtOffset = (targetOffset: number): number => {
    if (targetOffset <= 0) return 0;
    if (targetOffset >= listMetrics.totalHeight) return data.length - 1;

    let low = 0;
    let high = data.length - 1;
    let lastValid = 0;

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const rowStart = rowPositions.get(mid) || 0;

      if (rowStart <= targetOffset) {
        lastValid = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return lastValid;
  };

  const firstVisibleIdx = findRowAtOffset(offset);
  const lastVisibleIdx = findRowAtOffset(offset + height);

  const start = Math.max(0, firstVisibleIdx - overscanCount);
  const end = Math.min(data.length, lastVisibleIdx + overscanCount);

  const renderedRows = useMemo(() => {
    const selection = data.slice(start, end);
    return selection.map((item, index) => {
      const actualIndex = start + index;
      return (
        <div
          key={`list-item-${actualIndex}`}
          ref={(el) => {
            if (el) {
              rowRefs.current.set(actualIndex, el);
            } else {
              rowRefs.current.delete(actualIndex);
            }
          }}
        >
          {renderRow(item, actualIndex)}
        </div>
      );
    });
  }, [data, start, end, renderRow]);

  const top = rowPositions.get(start) || 0;
  const scrollProps = scrollRef ? {} : { onScroll: handleScroll };

  return (
    <div ref={baseRef} {...props} {...scrollProps} onKeyDown={onKeyDown}>
      <div
        className={clsx(
          styles.container,
          !scrollRef?.current ? styles.hidden : undefined,
        )}
        style={{ height: `${listMetrics.totalHeight}px` }}
      >
        <div
          className={styles.content}
          style={{ transform: `translateY(${top}px)` }}
          ref={containerRef}
        >
          {renderedRows}
        </div>
      </div>
    </div>
  );
}) as <T>(
  props: VirtualListProps<T> & { ref?: React.Ref<VirtualListRef> },
) => React.ReactElement;

const throttle = (func: (...args: any[]) => void, limit: number) => {
  let inThrottle: boolean;
  return function (this: any, ...args: any[]) {
    if (!inThrottle) {
      func.apply(this, args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
};
