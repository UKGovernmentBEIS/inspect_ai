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
import { EarlyStoppingSummary } from "../../../@types/log";
import { ScoreLabel } from "../../../app/types";
import {
  useDocumentTitle,
  useProperty,
  useSampleDescriptor,
  useScores,
  useSelectedScores,
} from "../../../state/hooks";
import { useVirtuosoState } from "../../../state/scrolling";
import { useStore } from "../../../state/store";
import { useSampleNavigation } from "../../routing/sampleNavigation";
import { sampleIdsEqual } from "../../shared/sample";
import { SampleFooter } from "./SampleFooter";
import { SampleHeader } from "./SampleHeader";
import styles from "./SampleList.module.css";

const kSampleHeight = 88;
const kSeparatorHeight = 24;

interface SampleListProps {
  items: ListItem[];
  earlyStopping?: EarlyStoppingSummary | null;
  totalItemCount: number;
  running: boolean;
  className?: string | string[];
  listHandle: RefObject<VirtuosoHandle | null>;
}

export const kSampleFollowProp = "sample-list";

export const SampleList: FC<SampleListProps> = memo((props) => {
  const {
    items,
    earlyStopping,
    totalItemCount,
    running,
    className,
    listHandle,
  } = props;

  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const { getRestoreState, isScrolling } = useVirtuosoState(
    listHandle,
    `sample-list-${selectedLogFile}`,
  );

  useEffect(() => {
    listHandle.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [listHandle, selectedLogFile]);

  // Get sample navigation utilities
  const sampleNavigation = useSampleNavigation();

  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );
  const samplesDescriptor = useSampleDescriptor();
  const [followOutput, setFollowOutput] = useProperty(
    kSampleFollowProp,
    "follow",
    {
      defaultValue: !!running,
    },
  );

  const evalSpec = useStore((state) => state.log.selectedLogDetails?.eval);
  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({ evalSpec });
  }, [setDocumentTitle, evalSpec]);

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
  }, [running, followOutput, listHandle, setFollowOutput]);

  const loaded = useRef(false);
  const handleAtBottomStateChange = useCallback(
    (atBottom: boolean) => {
      if (loaded.current && running) {
        setFollowOutput(atBottom);
      }
      loaded.current = true;
    },
    [running, setFollowOutput],
  );

  const onkeydown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      switch (e.key) {
        case "ArrowUp":
          if (e.metaKey || e.ctrlKey) {
            sampleNavigation.firstSample();
            listHandle.current?.scrollToIndex({
              index: 0,
              align: "start",
              behavior: "auto",
            });
          } else {
            sampleNavigation.previousSample();
          }

          e.preventDefault();
          e.stopPropagation();
          break;
        case "ArrowDown":
          if (e.metaKey || e.ctrlKey) {
            sampleNavigation.lastSample();
            listHandle.current?.scrollToIndex({
              index: items.length - 1,
              align: "end",
              behavior: "auto",
            });
          } else {
            sampleNavigation.nextSample();
          }

          e.preventDefault();
          e.stopPropagation();
          break;
        case "Enter": {
          const item = items.find((item) => {
            if (item.type === "sample") {
              return (
                sampleIdsEqual(item.sampleId, selectedSampleHandle?.id) &&
                item.sampleEpoch === selectedSampleHandle?.epoch
              );
            }
          });

          if (item && item.type === "sample") {
            sampleNavigation.showSample(item.data.id, item.data.epoch);
            e.preventDefault();
            e.stopPropagation();
          }
          break;
        }
      }
    },
    [
      sampleNavigation,
      listHandle,
      items,
      selectedSampleHandle?.id,
      selectedSampleHandle?.epoch,
    ],
  );

  const selectedScores = useSelectedScores();

  const scores = useScores();

  const gridColumnsTemplate = useMemo(() => {
    return gridColumnsValue(samplesDescriptor);
  }, [samplesDescriptor]);

  const renderRow = useCallback(
    (_index: number, item: ListItem) => {
      if (item.type === "sample") {
        return (
          <SampleRow
            id={`${item.number}`}
            sample={item.data}
            height={kSampleHeight}
            answer={item.answer}
            completed={item.completed}
            scoresRendered={item.scoresRendered}
            gridColumnsTemplate={gridColumnsTemplate}
            sampleUrl={sampleNavigation.getSampleUrl(
              item.data.id,
              item.data.epoch,
            )}
            selected={
              sampleIdsEqual(selectedSampleHandle?.id, item.sampleId) &&
              selectedSampleHandle?.epoch === item.sampleEpoch
            }
            showSample={() => {
              sampleNavigation.showSample(item.data.id, item.data.epoch);
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
    [
      gridColumnsTemplate,
      sampleNavigation,
      selectedSampleHandle?.epoch,
      selectedSampleHandle?.id,
    ],
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

  const warnings = [];
  if (errorCount > 0) {
    warnings.push({
      type: "info",
      msg: `INFO: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.`,
    });
  }
  if (limitCount > 0) {
    warnings.push({
      type: "info",
      msg: `INFO: ${limitCount} of ${sampleCount} samples (${formatNoDecimal(percentLimit)}%) completed due to exceeding a limit.`,
    });
  }
  if (earlyStopping?.early_stops && earlyStopping?.early_stops?.length > 0) {
    warnings.push({
      type: "info",
      msg: `Skipped ${earlyStopping.early_stops.length} samples due to early stopping (${earlyStopping.manager}). `,
    });
  }

  return (
    <div className={styles.mainLayout}>
      {warnings.map((warning, index) => (
        <MessageBand
          id={`sample-warning-message-${index}`}
          message={warning.msg}
          type={warning.type as "info" | "warning" | "error"}
          key={`sample-warning-message-${index}`}
        />
      ))}
      <SampleHeader
        input={input !== "0"}
        target={target !== "0"}
        answer={answer !== "0"}
        limit={limit !== "0"}
        retries={retries !== "0em"}
        scoreLabels={scoreHeaders(selectedScores, scores)}
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
  const { input, target, answer, limit, retries, id, scores } =
    gridColumns(sampleDescriptor);
  const result = `${id} ${input} ${target} ${answer} ${limit} ${retries} ${scores.join(" ")}`;
  return result;
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

  const scoresRaw = sampleDescriptor?.messageShape.raw.scores || [];
  const scoreSizes = scoresRaw.map((size) => Math.max(3, size));
  const scores =
    scoreSizes.length > 0 ? scoreSizes.map((size) => `${size / 2}rem`) : [];

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
    scores,
  };
};

const scoreHeaders = (
  selectedScores?: ScoreLabel[],
  availableScores?: ScoreLabel[],
): string[] => {
  if (!selectedScores || selectedScores.length === 0) {
    return [];
  }
  if (availableScores && availableScores.length === 1) {
    return ["Score"];
  }
  return selectedScores.map((s) => s.name);
};
