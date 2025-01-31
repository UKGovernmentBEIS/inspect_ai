import { ApplicationIcons } from "../appearance/icons";
import { ToolButton } from "../components/ToolButton";
import { SampleTools } from "../samples/SamplesTools";
import { JsonTab } from "./tabs/JsonTab";
import { SamplesTab } from "./tabs/SamplesTab";

import clsx from "clsx";
import { MouseEvent, RefObject, useEffect, useMemo, useRef } from "react";
import { SampleSummary } from "../api/types.ts";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kJsonWorkspaceTabId,
} from "../constants";
import { SamplesDescriptor } from "../samples/descriptor/samplesDescriptor";
import {
  Capabilities,
  CurrentLog,
  SampleMode,
  ScoreFilter,
  ScoreLabel,
} from "../types.ts";
import {
  Epochs,
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
  log?: CurrentLog;
  samples?: SampleSummary[];
  sampleMode: SampleMode;
  groupBy: "none" | "epoch" | "sample";
  groupByOrder: "asc" | "desc";
  selectedSample?: EvalSample;
  sampleStatus: string;
  sampleError?: Error;
  showToggle: boolean;
  refreshLog: () => Promise<void>;
  capabilities: Capabilities;
  selectedSampleIndex: number;
  samplesDescriptor?: SamplesDescriptor;
  setSelectedSampleIndex: (index: number) => void;
  selectedSampleTab?: string;
  setSelectedSampleTab: (tab: string) => void;
  sort: string;
  setSort: (sort: string) => void;
  epochs?: Epochs;
  epoch: string;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  setEpoch: (epoch: string) => void;
  filter: ScoreFilter;
  setFilter: (filter: ScoreFilter) => void;
  score?: ScoreLabel;
  setScore: (score: ScoreLabel) => void;
  scores: ScoreLabel[];
  offcanvas: boolean;
  setOffcanvas: (offcanvas: boolean) => void;
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
export const WorkSpace: React.FC<WorkSpaceProps> = (props) => {
  const {
    task_id,
    evalStatus,
    logFileName,
    evalSpec,
    evalPlan,
    evalStats,
    evalResults,
    samples,
    showToggle,
    offcanvas,
    setOffcanvas,
    samplesDescriptor,
    selectedTab,
    setSelectedTab,
    workspaceTabScrollPositionRef,
    setWorkspaceTabScrollPosition,
  } = props;
  if (!evalSpec) {
    return null;
  }

  const divRef = useRef<HTMLDivElement>(null);

  // Display the log
  useEffect(() => {
    if (divRef.current) {
      divRef.current.scrollTop = 0;
    }
  }, [task_id]);

  const resolvedTabs = useResolvedTabs(props);

  return (
    <WorkSpaceView
      logFileName={logFileName}
      divRef={divRef}
      evalSpec={evalSpec}
      evalPlan={evalPlan}
      evalResults={evalResults}
      evalStats={evalStats}
      samples={samples}
      evalDescriptor={samplesDescriptor?.evalDescriptor}
      status={evalStatus}
      tabs={resolvedTabs}
      selectedTab={selectedTab}
      showToggle={showToggle}
      offcanvas={offcanvas}
      setSelectedTab={setSelectedTab}
      workspaceTabScrollPositionRef={workspaceTabScrollPositionRef}
      setWorkspaceTabScrollPosition={setWorkspaceTabScrollPosition}
      setOffcanvas={setOffcanvas}
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
  groupBy,
  groupByOrder,
  selectedSampleIndex,
  setSelectedSampleIndex,
  samplesDescriptor,
  selectedSampleTab,
  setSelectedSampleTab,
  filter,
  sort,
  epoch,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  epochs,
  setEpoch,
  setFilter,
  setSort,
  score,
  setScore,
  scores,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  evalError,
  logFileName,
  capabilities,
  selectedTab,
  refreshLog,
}: WorkSpaceProps) => {
  const sampleTabScrollRef = useRef<HTMLDivElement>(null);

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
              sampleStatus={sampleStatus}
              sampleError={sampleError}
              showingSampleDialog={showingSampleDialog}
              setShowingSampleDialog={setShowingSampleDialog}
              samples={samples}
              sampleMode={sampleMode}
              groupBy={groupBy}
              groupByOrder={groupByOrder}
              selectedSampleIndex={selectedSampleIndex}
              setSelectedSampleIndex={setSelectedSampleIndex}
              sampleDescriptor={samplesDescriptor}
              selectedSampleTab={selectedSampleTab}
              setSelectedSampleTab={setSelectedSampleTab}
              filter={filter}
              epoch={epoch}
              sampleScrollPositionRef={sampleScrollPositionRef}
              setSampleScrollPosition={setSampleScrollPosition}
              sampleTabScrollRef={sampleTabScrollRef}
            />
          ),
          tools: () =>
            sampleMode === "single" || !samplesDescriptor
              ? undefined
              : [
                  <SampleTools
                    key="sample-tools"
                    epoch={epoch}
                    epochs={epochs || 1}
                    setEpoch={setEpoch}
                    scoreFilter={filter}
                    setScoreFilter={setFilter}
                    sort={sort}
                    setSort={setSort}
                    score={score}
                    setScore={setScore}
                    scores={scores}
                    sampleDescriptor={samplesDescriptor}
                  />,
                  evalStatus === "started" && (
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
          capabilities={capabilities}
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
