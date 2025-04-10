import { ApplicationIcons } from "../appearance/icons";
import { ToolButton } from "../components/ToolButton";
import { SampleTools, ScoreFilterTools } from "../samples/SamplesTools";
import { JsonTab } from "./tabs/JsonTab";
import { SamplesTab } from "./tabs/SamplesTab";

import clsx from "clsx";
import { FC, MouseEvent, useEffect, useMemo, useRef } from "react";
import { RunningMetric } from "../api/types.ts";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kJsonWorkspaceTabId,
} from "../constants";
import {
  useFilteredSamples,
  useSampleDescriptor,
  useTotalSampleCount,
} from "../state/hooks.ts";
import { useStore } from "../state/store.ts";
import { CurrentLog } from "../types.ts";
import {
  EvalError,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
  Status,
} from "../types/log";
import { InfoTab } from "./tabs/InfoTab.tsx";
import { WorkSpaceView } from "./WorkSpaceView.tsx";

interface WorkSpaceProps {
  task_id?: string;
  evalError?: EvalError;
  evalStatus?: Status;
  evalVersion?: number;
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  log?: CurrentLog;
  showToggle: boolean;
  refreshLog: () => void;
}

/**
 * Renders the Main Application
 */
export const WorkSpace: FC<WorkSpaceProps> = (props) => {
  const {
    task_id,
    evalStatus,
    evalSpec,
    evalPlan,
    evalStats,
    evalResults,
    runningMetrics,
    showToggle,
  } = props;

  const divRef = useRef<HTMLDivElement>(null);

  // Display the log
  useEffect(() => {
    if (divRef.current) {
      divRef.current.scrollTop = 0;
    }
  }, [task_id]);

  const resolvedTabs = useResolvedTabs(props);

  if (!evalSpec) {
    return undefined;
  }

  return (
    <WorkSpaceView
      divRef={divRef}
      evalSpec={evalSpec}
      evalPlan={evalPlan}
      evalResults={evalResults}
      runningMetrics={runningMetrics}
      evalStats={evalStats}
      status={evalStatus}
      tabs={resolvedTabs}
      showToggle={showToggle}
    />
  );
};

// Helper function for copy feedback
const copyFeedback = (e: MouseEvent<HTMLElement>) => {
  const textEl = e.currentTarget.querySelector(".task-btn-copy-content");
  const iconEl = e.currentTarget.querySelector("i.bi");
  if (textEl) {
    const htmlEl = textEl as HTMLElement;
    const htmlIconEl = iconEl as HTMLElement;
    const oldText = htmlEl.innerText;
    const oldIconClz = htmlIconEl.className;
    htmlEl.innerText = "Copied!";
    htmlIconEl.className = `${ApplicationIcons.confirm}`;
    setTimeout(() => {
      window.getSelection()?.removeAllRanges();
    }, 50);
    setTimeout(() => {
      htmlEl.innerText = oldText;
      htmlIconEl.className = oldIconClz;
    }, 1250);
  }
};

// Individual hook for Samples tab
export const useSamplesTabConfig = (
  evalStatus: Status | undefined,
  refreshLog: () => void,
) => {
  const totalSampleCount = useTotalSampleCount();
  const samplesDescriptor = useSampleDescriptor();
  const sampleSummaries = useFilteredSamples();
  const streamSamples = useStore((state) => state.capabilities.streamSamples);

  return useMemo(() => {
    return {
      id: kEvalWorkspaceTabId,
      scrollable: false,
      label: totalSampleCount > 1 ? "Samples" : "Sample",
      component: SamplesTab,
      componentProps: {
        running: evalStatus === "started",
      },
      tools: () =>
        !samplesDescriptor
          ? undefined
          : totalSampleCount === 1
            ? [<ScoreFilterTools />]
            : [
                <SampleTools
                  samples={sampleSummaries || []}
                  key="sample-tools"
                />,
                evalStatus === "started" && !streamSamples && (
                  <ToolButton
                    key="refresh"
                    label="Refresh"
                    icon={ApplicationIcons.refresh}
                    onClick={refreshLog}
                  />
                ),
              ],
    };
  }, [
    evalStatus,
    refreshLog,
    sampleSummaries,
    samplesDescriptor,
    totalSampleCount,
  ]);
};

// Individual hook for Info tab
export const useInfoTabConfig = (
  evalSpec: EvalSpec | undefined,
  evalPlan: EvalPlan | undefined,
  evalError: EvalError | undefined,
  evalResults: EvalResults | undefined,
  evalStats: EvalStats | undefined,
) => {
  const totalSampleCount = useTotalSampleCount();
  return useMemo(() => {
    return {
      id: kInfoWorkspaceTabId,
      label: "Info",
      scrollable: true,
      component: InfoTab,
      componentProps: {
        evalSpec,
        evalPlan,
        evalError,
        evalResults,
        evalStats,
        sampleCount: totalSampleCount,
      },
    };
  }, [evalSpec, evalPlan, evalError, evalResults, evalStats, totalSampleCount]);
};

// Individual hook for JSON tab
export const useJsonTabConfig = (
  evalVersion: number | undefined,
  evalStatus: Status | undefined,
  evalSpec: EvalSpec | undefined,
  evalPlan: EvalPlan | undefined,
  evalError: EvalError | undefined,
  evalResults: EvalResults | undefined,
  evalStats: EvalStats | undefined,
) => {
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );
  const selectedTab = useStore((state) => state.app.tabs.workspace);

  return useMemo(() => {
    const evalHeader = {
      version: evalVersion,
      status: evalStatus,
      eval: evalSpec,
      plan: evalPlan,
      error: evalError,
      results: evalResults,
      stats: evalStats,
    };

    return {
      id: kJsonWorkspaceTabId,
      label: "JSON",
      scrollable: true,
      component: JsonTab,
      componentProps: {
        logFile: selectedLogFile,
        json: JSON.stringify(evalHeader, null, 2),
        selected: selectedTab === kJsonWorkspaceTabId,
      },
      tools: () => [
        <ToolButton
          key="copy-json"
          label="Copy JSON"
          icon={ApplicationIcons.copy}
          className={clsx("task-btn-json-copy", "clipboard-button")}
          data-clipboard-target="#task-json-contents"
          onClick={copyFeedback}
        />,
      ],
    };
  }, [
    selectedLogFile,
    evalVersion,
    evalStatus,
    evalSpec,
    evalPlan,
    evalError,
    evalResults,
    evalStats,
    selectedTab,
  ]);
};

// Main hook combining all tab configs
export const useResolvedTabs = (props: WorkSpaceProps) => {
  const {
    evalVersion,
    evalStatus,
    evalSpec,
    evalPlan,
    evalResults,
    evalStats,
    evalError,
    refreshLog,
  } = props;

  // Use individual tab config hooks
  const samplesTabConfig = useSamplesTabConfig(evalStatus, refreshLog);

  const configTabConfig = useInfoTabConfig(
    evalSpec,
    evalPlan,
    evalError,
    evalResults,
    evalStats,
  );

  const jsonTabConfig = useJsonTabConfig(
    evalVersion,
    evalStatus,
    evalSpec,
    evalPlan,
    evalError,
    evalResults,
    evalStats,
  );

  // Combine all tab configs
  return useMemo(
    () => ({
      ...(samplesTabConfig ? { samples: samplesTabConfig } : {}),
      config: configTabConfig,
      json: jsonTabConfig,
    }),
    [samplesTabConfig, configTabConfig, jsonTabConfig],
  );
};
