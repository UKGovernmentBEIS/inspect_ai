import { highlightElement } from "prismjs";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Events } from "../@types/log";
import {
  createEvalDescriptor,
  createSamplesDescriptor,
} from "../app/samples/descriptor/samplesDescriptor";
import { filterSamples } from "../app/samples/sample-tools/filters";
import {
  byEpoch,
  bySample,
  sortSamples,
} from "../app/samples/sample-tools/SortFilter";
import { SampleSummary } from "../client/api/types";
import { kEpochAscVal, kSampleAscVal, kScoreAscVal } from "../constants";
import { createLogger } from "../utils/logger";
import { getAvailableScorers, getDefaultScorer } from "./scoring";
import { useStore } from "./store";
import { mergeSampleSummaries } from "./utils";

const log = createLogger("hooks");

export const useEvalSpec = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  return selectedLogSummary?.eval;
};

export const useRefreshLog = () => {
  const setAppStatus = useStore((state) => state.appActions.setStatus);
  const refreshLog = useStore((state) => state.logActions.refreshLog);
  const resetFiltering = useStore((state) => state.logActions.resetFiltering);

  return useCallback(() => {
    try {
      setAppStatus({ loading: true, error: undefined });

      refreshLog();
      resetFiltering();

      setAppStatus({ loading: false, error: undefined });
    } catch (e) {
      // Show an error
      console.log(e);
      setAppStatus({ loading: false, error: e as Error });
    }
  }, [refreshLog, resetFiltering, setAppStatus]);
};

// Fetches all samples summaries (both completed and incomplete)
// without applying any filtering
export const useSampleSummaries = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const pendingSampleSummaries = useStore(
    (state) => state.log.pendingSampleSummaries,
  );

  return useMemo(() => {
    return mergeSampleSummaries(
      selectedLogSummary?.sampleSummaries || [],
      pendingSampleSummaries?.samples || [],
    );
  }, [selectedLogSummary, pendingSampleSummaries]);
};

// Counts the total number of unfiltered sample summaries (both complete and incomplete)
export const useTotalSampleCount = () => {
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return sampleSummaries.length;
  }, [sampleSummaries]);
};

// Provides the currently selected score for this eval, providing a default
// based upon the configuration (eval + summaries) if no scorer has been
// selected
export const useScore = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  const score = useStore((state) => state.log.score);
  return useMemo(() => {
    if (score) {
      return score;
    } else if (selectedLogSummary) {
      return getDefaultScorer(selectedLogSummary, sampleSummaries);
    } else {
      return undefined;
    }
  }, [selectedLogSummary, sampleSummaries, score]);
};

// Provides the list of available scorers. Will inspect the eval or samples
// to determine scores (even for in progress evals that don't yet have final
// metrics)
export const useScores = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    if (!selectedLogSummary) {
      return [];
    }

    const result =
      getAvailableScorers(selectedLogSummary, sampleSummaries) || [];
    return result;
  }, [selectedLogSummary, sampleSummaries]);
};

// Provides the eval descriptor
export const useEvalDescriptor = () => {
  const scores = useScores();
  const sampleSummaries = useSampleSummaries();
  return useMemo(() => {
    return scores ? createEvalDescriptor(scores, sampleSummaries) : null;
  }, [scores, sampleSummaries]);
};

// Provides the sampls descriptor
export const useSampleDescriptor = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const score = useScore();
  return useMemo(() => {
    return evalDescriptor
      ? createSamplesDescriptor(sampleSummaries, evalDescriptor, score)
      : undefined;
  }, [evalDescriptor, sampleSummaries, score]);
};

// Provides the list of filtered samples
// (applying sorting, grouping, and filtering)
export const useFilteredSamples = () => {
  const evalDescriptor = useEvalDescriptor();
  const sampleSummaries = useSampleSummaries();
  const filter = useStore((state) => state.log.filter);
  const setFilterError = useStore((state) => state.logActions.setFilterError);
  const clearFilterError = useStore(
    (state) => state.logActions.clearFilterError,
  );

  const epoch = useStore((state) => state.log.epoch);
  const sort = useStore((state) => state.log.sort);
  const samplesDescriptor = useSampleDescriptor();
  const score = useScore();

  return useMemo(() => {
    // Apply filters
    const { result, error, allErrors } =
      evalDescriptor && filter
        ? filterSamples(evalDescriptor, sampleSummaries, filter)
        : { result: sampleSummaries, error: undefined, allErrors: false };

    if (error && allErrors) {
      setFilterError(error);
    } else {
      clearFilterError();
    }

    const prefiltered =
      error === undefined || !allErrors ? result : sampleSummaries;

    // Filter epochs
    const filtered =
      epoch && epoch !== "all"
        ? prefiltered.filter((sample) => epoch === String(sample.epoch))
        : prefiltered;

    // Sort samples
    const sorted = samplesDescriptor
      ? sortSamples(sort, filtered, samplesDescriptor, score)
      : filtered;

    return [...sorted];
  }, [
    evalDescriptor,
    sampleSummaries,
    filter,
    setFilterError,
    clearFilterError,
    epoch,
    sort,
    samplesDescriptor,
    score,
  ]);
};

// Computes the group by to use given a particular sort
export const useGroupBy = () => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const sort = useStore((state) => state.log.sort);
  const epoch = useStore((state) => state.log.epoch);
  return useMemo(() => {
    const epochs = selectedLogSummary?.eval?.config?.epochs || 1;
    if (epochs > 1) {
      if (byEpoch(sort) || epoch !== "all") {
        return "epoch";
      } else if (bySample(sort)) {
        return "sample";
      }
    }

    return "none";
  }, [selectedLogSummary, sort, epoch]);
};

// Computes the ordering for groups based upon the sort
export const useGroupByOrder = () => {
  const sort = useStore((state) => state.log.sort);
  return useMemo(() => {
    return sort === kSampleAscVal ||
      sort === kEpochAscVal ||
      sort === kScoreAscVal
      ? "asc"
      : "desc";
  }, [sort]);
};

// Provides the currently selected sample summary
export const useSelectedSampleSummary = (): SampleSummary | undefined => {
  const filteredSamples = useFilteredSamples();
  const selectedIndex = useStore((state) => state.log.selectedSampleIndex);
  return useMemo(() => {
    return filteredSamples[selectedIndex];
  }, [filteredSamples, selectedIndex]);
};

export const useSampleData = () => {
  const sampleStatus = useStore((state) => state.sample.sampleStatus);
  const sampleError = useStore((state) => state.sample.sampleError);
  const selectedSample = useStore((state) => state.sample.selectedSample);
  const runningEvents = useStore(
    (state) => state.sample.runningEvents,
  ) as Events;
  return useMemo(() => {
    return {
      status: sampleStatus,
      error: sampleError,
      sample: selectedSample,
      running: runningEvents,
    };
  }, [sampleStatus, sampleError, selectedSample, runningEvents]);
};

export const useLogSelection = () => {
  const selectedSampleSummary = useSelectedSampleSummary();
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );
  const loadedLog = useStore((state) => state.log.loadedLog);

  return useMemo(() => {
    return {
      logFile: selectedLogFile,
      loadedLog: loadedLog,
      sample: selectedSampleSummary,
    };
  }, [selectedLogFile, selectedSampleSummary]);
};

export const useCollapsedState = (
  id: string,
  defaultValue?: boolean,
): [boolean, (value: boolean) => void] => {
  const collapsed = useStore((state) =>
    state.appActions.getCollapsed(id, defaultValue),
  );
  const setCollapsed = useStore((state) => state.appActions.setCollapsed);
  return useMemo(() => {
    const set = (value: boolean) => {
      log.debug("Set collapsed", id, value);
      setCollapsed(id, value);
    };
    return [collapsed, set];
  }, [collapsed, setCollapsed]);
};

export const useMessageVisibility = (
  id: string,
  scope: "sample" | "eval",
): [boolean, (visible: boolean) => void] => {
  const visible = useStore((state) =>
    state.appActions.getMessageVisible(id, true),
  );
  const setVisible = useStore((state) => state.appActions.setMessageVisible);
  const clearVisible = useStore(
    (state) => state.appActions.clearMessageVisible,
  );

  // Track if this is the first render (rehydrate)
  const isFirstRender = useRef(true);

  // Reset state if the eval changes, but not during initialization
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );
  useEffect(() => {
    // Skip the first effect run
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }

    log.debug("clear message (eval)", id);
    clearVisible(id);
  }, [selectedLogFile, clearVisible, id]);

  // Maybe reset state if sample changes
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  useEffect(() => {
    // Skip the first effect run for sample changes too
    if (isFirstRender.current) {
      return;
    }

    if (scope === "sample") {
      log.debug("clear message (sample)", id);
      clearVisible(id);
    }
  }, [selectedSampleIndex, clearVisible, id, scope]);

  return useMemo(() => {
    log.debug("visibility", id, visible);
    const set = (visible: boolean) => {
      log.debug("set visiblity", id);
      setVisible(id, visible);
    };
    return [visible, set];
  }, [visible, setVisible, id]);
};

export function useProperty<T>(
  id: string,
  propertyName: string,
  options?: {
    defaultValue?: T;
    cleanup?: boolean;
  },
): [T, (value: T) => void, () => void] {
  options = options || { cleanup: true };
  const setPropertyValue = useStore(
    (state) => state.appActions.setPropertyValue,
  );
  const removePropertyValue = useStore(
    (state) => state.appActions.removePropertyValue,
  );
  const propertyValue = useStore(
    useCallback(
      (state) =>
        state.appActions.getPropertyValue(
          id,
          propertyName,
          options.defaultValue,
        ),
      [id, propertyName, options.defaultValue],
    ),
  );

  const setValue = useCallback(
    (value: T) => {
      setPropertyValue(id, propertyName, value);
    },
    [id, propertyName, setPropertyValue],
  );

  const removeValue = useCallback(() => {
    removePropertyValue(id, propertyName);
  }, [id, propertyName, removePropertyValue]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (options.cleanup) {
        removePropertyValue(id, propertyName);
      }
    };
  }, [id, propertyName, removePropertyValue]);

  return [propertyValue, setValue, removeValue];
}

export const usePrevious = <T>(value: T) => {
  const ref = useRef<T | undefined>(undefined);

  useEffect(() => {
    ref.current = value;
  }, [value]);

  return ref.current;
};

// Syntax highlighting strings larger than this is too slow
const kPrismRenderMaxSize = 250000;

export const usePrismHighlight = (toolCallContent?: string) => {
  const toolViewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (
      toolCallContent &&
      toolViewRef.current &&
      toolCallContent.length <= kPrismRenderMaxSize
    ) {
      requestAnimationFrame(() => {
        const codeBlocks = toolViewRef.current?.querySelectorAll("pre code");
        codeBlocks?.forEach((block) => {
          if (block.className.includes("language-")) {
            block.classList.add("sourceCode");
            highlightElement(block as HTMLElement);
          }
        });
      });
    }
  }, [toolCallContent]);

  return toolViewRef;
};

export const useSetSelectedLogIndex = () => {
  const setSelectedLogIndex = useStore(
    (state) => state.logsActions.setSelectedLogIndex,
  );
  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );
  const clearSelectedLogSummary = useStore(
    (state) => state.logActions.clearSelectedLogSummary,
  );

  return useCallback(
    (index: number) => {
      clearSelectedSample();
      clearSelectedLogSummary();
      setSelectedLogIndex(index);
    },
    [setSelectedLogIndex, clearSelectedLogSummary, clearSelectedSample],
  );
};
