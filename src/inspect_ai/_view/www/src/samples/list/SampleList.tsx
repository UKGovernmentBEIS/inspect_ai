import {
  FC,
  KeyboardEvent,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { MessageBand } from "../../components/MessageBand";
import { formatNoDecimal } from "../../utils/format";
import { ListItem } from "../../workspace/tabs/types";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleRow } from "./SampleRow";
import { SampleSeparator } from "./SampleSeparator";

import clsx from "clsx";
import { useSampleDescriptor } from "../../state/hooks";
import { useStore } from "../../state/store";
import { SampleFooter } from "./SampleFooter";
import { SampleHeader } from "./SampleHeader";
import styles from "./SampleList.module.css";

const kSampleHeight = 88;
const kSeparatorHeight = 24;

interface SampleListProps {
  items: ListItem[];
  running: boolean;
  nextSample: () => void;
  prevSample: () => void;
  showSample: (index: number) => void;
  className?: string | string[];
  listHandle: RefObject<VirtuosoHandle | null>;
}

export const SampleList: FC<SampleListProps> = (props) => {
  const {
    items,
    running,
    nextSample,
    prevSample,
    showSample,
    className,
    listHandle,
  } = props;

  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  const samplesDescriptor = useSampleDescriptor();
  const [followOutput, setFollowOutput] = useState(false);

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
    const listEl = listHandle.current;
    if (listEl && itemRowMapping.length > selectedSampleIndex) {
      const actualRowIndex = itemRowMapping[selectedSampleIndex];

      requestAnimationFrame(() => {
        setTimeout(() => {
          try {
            listEl.scrollToIndex(actualRowIndex);
            prevSelectedIndexRef.current = actualRowIndex;
          } catch {
            // TODO: Improve our behavior with regards to scrolling
            // Theory: calling this while following the bottom of the list isn't great
          }
        }, 25);
      });
    }
  }, [selectedSampleIndex, listHandle, itemRowMapping]);

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
          showSample(selectedSampleIndex);
          e.preventDefault();
          e.stopPropagation();
          break;
      }
    },
    [selectedSampleIndex, nextSample, prevSample, showSample],
  );

  const gridColumnsTemplate = useMemo(() => {
    return gridColumnsValue(samplesDescriptor);
  }, [samplesDescriptor]);

  const renderRow = useCallback(
    (item: ListItem) => {
      if (item.type === "sample") {
        return (
          <SampleRow
            id={`${item.number}`}
            index={item.index}
            sample={item.data}
            height={kSampleHeight}
            answer={item.answer}
            completed={item.completed}
            scoreRendered={item.scoreRendered}
            gridColumnsTemplate={gridColumnsTemplate}
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
    },
    [showSample],
  );

  const { input, limit, answer, target } = gridColumns(samplesDescriptor);

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
        gridColumnsTemplate={gridColumnsTemplate}
      />
      <Virtuoso
        ref={listHandle}
        style={{ height: "100%" }}
        data={items}
        defaultItemHeight={50}
        itemContent={(_index: number, data: ListItem) => {
          return renderRow(data);
        }}
        followOutput={followOutput}
        atBottomStateChange={(atBottom: boolean) => {
          setFollowOutput(atBottom);
        }}
        increaseViewportBy={{ top: 300, bottom: 300 }}
        overscan={{
          main: 10,
          reverse: 10,
        }}
        className={clsx(className)}
        onKeyDown={onkeydown}
        skipAnimationFrameInResizeObserver={true}
      />
      <SampleFooter sampleCount={sampleCount} running={running} />
    </div>
  );
};

const gridColumnsValue = (sampleDescriptor?: SamplesDescriptor) => {
  const { input, target, answer, limit, id, score } =
    gridColumns(sampleDescriptor);
  return `${id} ${input} ${target} ${answer} ${limit} ${score}`;
};

const gridColumns = (sampleDescriptor?: SamplesDescriptor) => {
  const input =
    sampleDescriptor && sampleDescriptor.messageShape.normalized.input > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.input)
      : 0;
  const target =
    sampleDescriptor && sampleDescriptor.messageShape.normalized.target > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.target)
      : 0;
  const answer =
    sampleDescriptor && sampleDescriptor.messageShape.normalized.answer > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.answer)
      : 0;
  const limit =
    sampleDescriptor && sampleDescriptor.messageShape.normalized.limit > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit)
      : 0;
  const id = Math.max(
    2,
    Math.min(10, sampleDescriptor?.messageShape.raw.id || 0),
  );
  const score = Math.max(
    3,
    Math.min(10, sampleDescriptor?.messageShape.raw.score || 0),
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
