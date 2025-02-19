import clsx from "clsx";
import {
  KeyboardEvent,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { EmptyPanel } from "../../components/EmptyPanel";
import { MessageBand } from "../../components/MessageBand";
import { VirtualList, VirtualListRef } from "../../components/VirtualList";
import { formatNoDecimal } from "../../utils/format";
import { ListItem } from "../../workspace/tabs/types";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleRow } from "./SampleRow";
import { SampleSeparator } from "./SampleSeparator";

import { SampleFooter } from "./SampleFooter";
import { SampleHeader } from "./SampleHeader";
import styles from "./SampleList.module.css";

const kSampleHeight = 88;
const kSeparatorHeight = 24;

interface SampleListProps {
  listRef: RefObject<VirtualListRef | null>;
  items: ListItem[];
  sampleDescriptor: SamplesDescriptor;
  selectedIndex: number;
  nextSample: () => void;
  prevSample: () => void;
  showSample: (index: number) => void;
  className?: string | string[];
}

export const SampleList: React.FC<SampleListProps> = (props) => {
  const {
    listRef,
    items,
    sampleDescriptor,
    selectedIndex,
    nextSample,
    prevSample,
    showSample,
    className,
  } = props;

  // If there are no samples, just display an empty state
  if (items.length === 0) {
    return <EmptyPanel>No Samples</EmptyPanel>;
  }

  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    setHidden(false);
  }, [items]);

  // Keep a mapping of the indexes to items (skipping separators)
  const itemRowMapping = useMemo(() => {
    const rowIndexes: number[] = [];
    items.forEach((item, index) => {
      if (item.type === "sample") {
        rowIndexes.push(index);
      }
    });
    return rowIndexes;
  }, [items]);

  const prevSelectedIndexRef = useRef<number>(null);
  useEffect(() => {
    const listEl = listRef.current;
    if (listEl) {
      const actualRowIndex = itemRowMapping[selectedIndex];

      const direction =
        actualRowIndex > (prevSelectedIndexRef.current || 0) ? "down" : "up";
      listRef.current?.scrollToIndex(actualRowIndex, direction);
      prevSelectedIndexRef.current = actualRowIndex;
    }
  }, [selectedIndex, listRef, itemRowMapping]);

  const renderRow = (item: ListItem) => {
    if (item.type === "sample") {
      return (
        <SampleRow
          id={`${item.number}`}
          index={item.index}
          sample={item.data}
          height={kSampleHeight}
          sampleDescriptor={sampleDescriptor}
          gridColumnsTemplate={gridColumnsValue(sampleDescriptor)}
          selected={selectedIndex === item.index}
          showSample={showSample}
        />
      );
    } else if (item.type === "separator") {
      return (
        <SampleSeparator
          id={`sample-group${item.number}`}
          title={item.data}
          height={kSeparatorHeight}
        />
      );
    } else {
      return null;
    }
  };

  const onkeydown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      switch (e.key) {
        case "ArrowUp":
          prevSample();
          e.preventDefault();
          e.stopPropagation();
          break;
        case "ArrowDown":
          nextSample();
          e.preventDefault();
          e.stopPropagation();
          break;
        case "Enter":
          showSample(selectedIndex);
          e.preventDefault();
          e.stopPropagation();
          break;
      }
    },
    [selectedIndex],
  );

  const { input, limit, answer, target } = gridColumns(sampleDescriptor);

  const sampleCount = items?.reduce((prev, current) => {
    if (current.type === "sample") {
      return prev + 1;
    } else {
      return prev;
    }
  }, 0);

  // Count any sample errors and display a bad alerting the user
  // to any errors
  const errorCount = items?.reduce((previous, item: ListItem) => {
    if (typeof item.data === "object" && item.data.error) {
      return previous + 1;
    }
    return previous;
  }, 0);

  // Count limits
  const limitCount = items?.reduce((previous, item) => {
    if (typeof item.data === "object" && item.data.limit) {
      return previous + 1;
    } else {
      return previous;
    }
  }, 0);

  const percentError = (errorCount / sampleCount) * 100;
  const percentLimit = (limitCount / sampleCount) * 100;
  const warningMessage =
    errorCount > 0
      ? `INFO: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.`
      : limitCount
        ? `INFO: ${limitCount} of ${sampleCount} samples (${formatNoDecimal(percentLimit)}%) completed due to exceeding a limit.`
        : undefined;

  return (
    <div className={styles.mainLayout}>
      {warningMessage ? (
        <MessageBand
          message={warningMessage}
          hidden={hidden}
          setHidden={setHidden}
          type="info"
        />
      ) : undefined}

      <SampleHeader
        input={input !== "0"}
        target={target !== "0"}
        answer={answer !== "0"}
        limit={limit !== "0"}
        gridColumnsTemplate={gridColumnsValue(sampleDescriptor)}
      />
      <VirtualList
        ref={listRef}
        data={items}
        tabIndex={0}
        renderRow={renderRow}
        onKeyDown={onkeydown}
        className={clsx(styles.list, className)}
      />
      <SampleFooter sampleCount={sampleCount} />
    </div>
  );
};

const gridColumnsValue = (sampleDescriptor: SamplesDescriptor) => {
  const { input, target, answer, limit, id, score } =
    gridColumns(sampleDescriptor);
  return `${id} ${input} ${target} ${answer} ${limit} ${score}`;
};

const gridColumns = (sampleDescriptor: SamplesDescriptor) => {
  const input =
    sampleDescriptor?.messageShape.normalized.input > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.input)
      : 0;
  const target =
    sampleDescriptor?.messageShape.normalized.target > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.target)
      : 0;
  const answer =
    sampleDescriptor?.messageShape.normalized.answer > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.answer)
      : 0;
  const limit =
    sampleDescriptor?.messageShape.normalized.limit > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit)
      : 0;
  const id = Math.max(2, Math.min(10, sampleDescriptor?.messageShape.raw.id));
  const score = Math.max(
    3,
    Math.min(10, sampleDescriptor?.messageShape.raw.score),
  );

  const frSize = (val: number) => {
    if (val === 0) {
      return "0";
    } else {
      return `${val}fr`;
    }
  };

  return {
    input: frSize(input),
    target: frSize(target),
    answer: frSize(answer),
    limit: frSize(limit),
    id: `${id}rem`,
    score: `${score}rem`,
  };
};
