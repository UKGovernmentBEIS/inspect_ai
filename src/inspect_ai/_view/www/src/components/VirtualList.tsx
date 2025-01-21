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

interface VirtualListRef {
  focus: () => void;
  scrollToIndex: (index: number, direction?: "up" | "down") => void;
}

interface VirtualListProps<T> {
  data: T[];
  renderRow: (item: T, index: number) => React.ReactNode;
  overscanCount?: number;
  estimatedRowHeight?: number;
  sync?: boolean;
  scrollRef?: React.RefObject<HTMLElement>;
  className?: string;
  style?: React.CSSProperties;
}

interface ListMetrics {
  rowHeights: Map<number, number>;
  totalHeight: number;
}

export const VirtualList = forwardRef(
  <T,>(
    {
      data,
      renderRow,
      overscanCount = 15,
      estimatedRowHeight = 50,
      sync = false,
      scrollRef,
      ...props
    }: VirtualListProps<T>,
    ref: React.Ref<VirtualListRef>,
  ) => {
    const [height, setHeight] = useState(0);
    const [offset, setOffset] = useState(0);
    const [listMetrics, setListMetrics] = useState<ListMetrics>({
      rowHeights: new Map(),
      totalHeight: data.length * estimatedRowHeight,
    });

    const baseRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const rowRefs = useRef<Map<number, HTMLElement>>(new Map());

    const getRowHeight = (index: number): number => {
      return listMetrics.rowHeights.get(index) || estimatedRowHeight;
    };

    const rowPositions = useMemo(() => {
      let currentPosition = 0;
      const positions = new Map<number, number>();

      for (let i = 0; i < data.length; i++) {
        positions.set(i, currentPosition);
        currentPosition += getRowHeight(i);
      }

      return positions;
    }, [listMetrics.rowHeights, data.length, getRowHeight]);

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

          // Get position and height of target row
          const rowTop = rowPositions.get(index) || 0;
          const rowHeight = getRowHeight(index);
          const rowBottom = rowTop + rowHeight;

          // If this is already visible, don't scroll
          const isVisible =
            rowTop >= currentScrollTop &&
            rowBottom <= currentScrollTop + viewportHeight;
          if (isVisible) return;

          // Calculate new scroll position based on direction
          let newScrollTop: number;
          if (direction === "up") {
            // Align top of element with top of viewport
            newScrollTop = rowTop;
          } else {
            // Align bottom of element with bottom of viewport
            newScrollTop = rowBottom - viewportHeight;
          }

          // Clamp scroll position to valid range
          newScrollTop = Math.max(
            0,
            Math.min(newScrollTop, listMetrics.totalHeight - viewportHeight),
          );
          scrollElement.scrollTop = newScrollTop;
        },
      }),
      [rowPositions, data.length],
    );

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

      let newTotalHeight = 0;
      for (let i = 0; i < data.length; i++) {
        newTotalHeight += newHeights.get(i) || estimatedRowHeight;
      }

      setListMetrics({
        rowHeights: newHeights,
        totalHeight: newTotalHeight,
      });
    };

    // Handle container resize
    const resize = () => {
      const scrollElement = scrollRef?.current || baseRef.current;
      if (scrollElement && height !== scrollElement.offsetHeight) {
        setHeight(scrollElement.offsetHeight);
      }
    };

    // Handle scroll with throttling
    const handleScroll = throttle(() => {
      const scrollElement = scrollRef?.current || baseRef.current;
      if (scrollElement) {
        setOffset(scrollElement.scrollTop);
      }
      if (sync) {
        setOffset((prev) => prev);
      }
    }, 100);

    // Setup scroll and resize listeners
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

    // Measure rows after render
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

    // Calculate range of rows to render including overscan
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

    // only attach scroll handler if there isn't a scroll ref
    const scrollProps = scrollRef ? {} : { onScroll: handleScroll };

    return (
      <div ref={baseRef} {...props} {...scrollProps}>
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
  },
);

// Throttle utility function
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
