import { ApplicationIcons } from "../appearance/icons";
import { ToolButton } from "../components/ToolButton";
import { SampleTools } from "../samples/SamplesTools";
import { JsonTab } from "./tabs/JsonTab";
import { SamplesTab } from "./tabs/SamplesTab";

import clsx from "clsx";
import { FC, MouseEvent, RefObject, useEffect, useMemo, useRef } from "react";
import { RunningMetric, SampleSummary } from "../api/types.ts";
import { useAppContext } from "../AppContext.tsx";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kJsonWorkspaceTabId,
} from "../constants";
import { useLogContext } from "../LogContext.tsx";
import { CurrentLog, RunningSampleData, SampleMode } from "../types.ts";
import {
  EvalError,
  EvalPlan,
  EvalResults,
  EvalSample,
  EvalSpec,
  EvalStats,
  Status,
} from "../types/log";
import { InfoTab } from "./tabs/InfoTab.tsx";
import { WorkSpaceView } from "./WorkSpaceView.tsx";

interface WorkSpaceProps {
  task_id?: string;
  logFileName?: string;
  evalError?: EvalError;
  evalStatus?: Status;
  evalVersion?: number;
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  log?: CurrentLog;
  samples?: SampleSummary[];
  sampleMode: SampleMode;
  selectedSample?: EvalSample;
  sampleStatus: string;
  sampleError?: Error;
  showToggle: boolean;
  refreshLog: () => void;
  runningSampleData?: RunningSampleData;
  selectedSampleTab?: string;
  setSelectedSampleTab: (tab: string) => void;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  selectedTab: string;
  setSelectedTab: (id: string) => void;
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
  workspaceTabScrollPositionRef: RefObject<Record<string, number>>;
  setWorkspaceTabScrollPosition: (tab: string, position: number) => void;
}

/**
 * Renders the Main Application
 */
export const WorkSpace: FC<WorkSpaceProps> = (props) => {
  const {
    task_id,
    evalStatus,
    logFileName,
    evalSpec,
    evalPlan,
    evalStats,
    evalResults,
    runningMetrics,
    samples,
    showToggle,
    selectedTab,
    setSelectedTab,
    workspaceTabScrollPositionRef,
    setWorkspaceTabScrollPosition,
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
      logFileName={logFileName}
      divRef={divRef}
      evalSpec={evalSpec}
      evalPlan={evalPlan}
      evalResults={evalResults}
      runningMetrics={runningMetrics}
      evalStats={evalStats}
      samples={samples}
      status={evalStatus}
      tabs={resolvedTabs}
      selectedTab={selectedTab}
      showToggle={showToggle}
      setSelectedTab={setSelectedTab}
      workspaceTabScrollPositionRef={workspaceTabScrollPositionRef}
      setWorkspaceTabScrollPosition={setWorkspaceTabScrollPosition}
    />
  );
};

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

const useResolvedTabs = ({
  evalVersion,
  evalStatus,
  sampleMode,
  samples,
  selectedSample,
  sampleStatus,
  sampleError,
  showingSampleDialog,
  setShowingSampleDialog,
  runningSampleData,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  evalError,
  logFileName,
  selectedTab,
  refreshLog,
}: WorkSpaceProps) => {
  const sampleTabScrollRef = useRef<HTMLDivElement>(null);
  const appContext = useAppContext();
  const logContext = useLogContext();

  const samplesTab =
    sampleMode !== "none"
      ? {
          id: kEvalWorkspaceTabId,
          scrollable: samples?.length === 1,
          scrollRef: sampleTabScrollRef,
          label: (samples || []).length > 1 ? "Samples" : "Sample",
          content: () => (
            <SamplesTab
              sample={selectedSample}
              runningSampleData={runningSampleData}
              sampleStatus={sampleStatus}
              sampleError={sampleError}
              running={evalStatus === "started"}
              showingSampleDialog={showingSampleDialog}
              setShowingSampleDialog={setShowingSampleDialog}
              samples={samples}
              sampleMode={sampleMode}
              selectedSampleTab={selectedSampleTab}
              setSelectedSampleTab={setSelectedSampleTab}
              sampleScrollPositionRef={sampleScrollPositionRef}
              setSampleScrollPosition={setSampleScrollPosition}
              sampleTabScrollRef={sampleTabScrollRef}
            />
          ),
          tools: () =>
            sampleMode === "single" || !logContext.samplesDescriptor
              ? undefined
              : [
                  <SampleTools samples={samples || []} key="sample-tools" />,
                  evalStatus === "started" &&
                    !appContext.capabilities.streamSamples && (
                      <ToolButton
                        key="refresh"
                        label="Refresh"
                        icon={ApplicationIcons.refresh}
                        onClick={refreshLog}
                      />
                    ),
                ].filter(Boolean),
        }
      : null;

  const configTab = {
    id: kInfoWorkspaceTabId,
    label: "Info",
    scrollable: true,
    content: () => (
      <InfoTab
        evalSpec={evalSpec}
        evalPlan={evalPlan}
        evalError={evalError}
        evalResults={evalResults}
        evalStats={evalStats}
        samples={samples}
      />
    ),
  };

  const jsonTab = {
    id: kJsonWorkspaceTabId,
    label: "JSON",
    scrollable: true,
    content: () => {
      const evalHeader = {
        version: evalVersion,
        status: evalStatus,
        eval: evalSpec,
        plan: evalPlan,
        error: evalError,
        results: evalResults,
        stats: evalStats,
      };
      return (
        <JsonTab
          logFile={logFileName}
          json={JSON.stringify(evalHeader, null, 2)}
          selected={selectedTab === kJsonWorkspaceTabId}
        />
      );
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

  return useMemo(
    () => ({
      ...(samplesTab ? { samples: samplesTab } : {}),
      config: configTab,
      json: jsonTab,
    }),
    [samplesTab, configTab, jsonTab],
  );
};
