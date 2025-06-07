import {
  FC,
  KeyboardEvent,
  memo,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { MessageBand } from "../../../components/MessageBand";
import { formatNoDecimal } from "../../../utils/format";
import { ListItem } from "../../log-view/tabs/types";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleRow } from "./SampleRow";
import { SampleSeparator } from "./SampleSeparator";

import clsx from "clsx";
import { useProperty, useSampleDescriptor } from "../../../state/hooks";
import { useVirtuosoState } from "../../../state/scrolling";
import { useStore } from "../../../state/store";
import { useSampleNavigation } from "../../routing/sampleNavigation";
import { SampleFooter } from "./SampleFooter";
import { SampleHeader } from "./SampleHeader";
import styles from "./SampleList.module.css";

const kSampleHeight = 88;
const kSeparatorHeight = 24;

interface SampleListProps {
  items: ListItem[];
  totalItemCount: number;
  running: boolean;
  className?: string | string[];
  listHandle: RefObject<VirtuosoHandle | null>;
}

export const kSampleFollowProp = "sample-list";

export const SampleList: FC<SampleListProps> = memo((props) => {
  const { items, totalItemCount, running, className, listHandle } = props;

  const selectedLogIndex = useStore((state) => state.logs.selectedLogIndex);
  const { getRestoreState, isScrolling } = useVirtuosoState(
    listHandle,
    `sample-list-${selectedLogIndex}`,
  );

  useEffect(() => {
    listHandle.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [selectedLogIndex]);

  // Get sample navigation utilities
  const sampleNavigation = useSampleNavigation();

  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  const samplesDescriptor = useSampleDescriptor();
  const [followOutput, setFollowOutput] = useProperty(
    kSampleFollowProp,
    "follow",
    {
      defaultValue: !!running,
    },
  );

  // Track whether we were previously running so we can
  // decide whether to pop up to the top
  const prevRunningRef = useRef(running);

  useEffect(() => {
    // When we finish running, if we are following output
    // then scroll up to the top
    if (
      !running &&
      prevRunningRef.current &&
      followOutput &&
      listHandle.current
    ) {
      setFollowOutput(false);
      setTimeout(() => {
        if (listHandle.current) {
          listHandle.current.scrollTo({ top: 0, behavior: "instant" });
        }
      }, 100);
    }
    prevRunningRef.current = running;
  }, [running, followOutput, listHandle]);

  const loaded = useRef(false);
  const handleAtBottomStateChange = useCallback(
    (atBottom: boolean) => {
      if (loaded.current && running) {
        setFollowOutput(atBottom);
      }
      loaded.current = true;
    },
    [running, setFollowOutput, followOutput],
  );

  const onkeydown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      switch (e.key) {
        case "ArrowUp":
          sampleNavigation.previousSample();
          e.preventDefault();
          e.stopPropagation();
          break;
        case "ArrowDown":
          sampleNavigation.nextSample();
          e.preventDefault();
          e.stopPropagation();
          break;
        case "Enter": {
          const item = items[selectedSampleIndex];
          if (item.type === "sample") {
            sampleNavigation.showSample(
              item.index,
              item.data.id,
              item.data.epoch,
            );
            e.preventDefault();
            e.stopPropagation();
          }
          break;
        }
      }
    },
    [
      selectedSampleIndex,
      sampleNavigation.nextSample,
      sampleNavigation.previousSample,
      sampleNavigation.showSample,
    ],
  );

  const gridColumnsTemplate = useMemo(() => {
    return gridColumnsValue(samplesDescriptor);
  }, [samplesDescriptor]);

  const renderRow = useCallback(
    (_index: number, item: ListItem) => {
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
            sampleUrl={sampleNavigation.getSampleUrl(
              item.data.id,
              item.data.epoch,
            )}
            showSample={() => {
              sampleNavigation.showSample(
                item.index,
                item.data.id,
                item.data.epoch,
              );
            }}
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
    [gridColumnsTemplate],
  );

  const { input, limit, answer, target, retries } =
    gridColumns(samplesDescriptor);

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
          id={"sample-warning-message"}
          message={warningMessage}
          type="info"
        />
      ) : undefined}
      <SampleHeader
        input={input !== "0"}
        target={target !== "0"}
        answer={answer !== "0"}
        limit={limit !== "0"}
        retries={retries !== "0em"}
        gridColumnsTemplate={gridColumnsTemplate}
      />
      <Virtuoso
        ref={listHandle}
        style={{ height: "100%" }}
        data={items}
        defaultItemHeight={50}
        itemContent={renderRow}
        followOutput={
          running
            ? (_atBottom: boolean) => {
                return followOutput;
              }
            : undefined
        }
        atBottomStateChange={handleAtBottomStateChange}
        atBottomThreshold={30}
        increaseViewportBy={{ top: 300, bottom: 300 }}
        overscan={{
          main: 10,
          reverse: 10,
        }}
        className={clsx(className, "samples-list")}
        onKeyDown={onkeydown}
        skipAnimationFrameInResizeObserver={true}
        isScrolling={isScrolling}
        restoreStateFrom={getRestoreState()}
        tabIndex={0}
      />
      <SampleFooter
        sampleCount={sampleCount}
        totalSampleCount={totalItemCount}
        running={running}
      />
    </div>
  );
});

const gridColumnsValue = (sampleDescriptor?: SamplesDescriptor) => {
  const { input, target, answer, limit, retries, id, score } =
    gridColumns(sampleDescriptor);
  return `${id} ${input} ${target} ${answer} ${limit} ${retries} ${score}`;
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
  const retries =
    sampleDescriptor && sampleDescriptor.messageShape.normalized.retries > 0
      ? 4
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
    retries: `${retries}em`,
    id: `${id}rem`,
    score: `${score}rem`,
  };
};
