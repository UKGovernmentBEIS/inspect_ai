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
import { TabDescriptor } from "./types.ts";
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
export const WorkSpace: React.FC<WorkSpaceProps> = ({
  task_id,
  evalStatus,
  logFileName,
  evalError,
  evalSpec,
  evalVersion,
  evalPlan,
  evalStats,
  evalResults,
  samples,
  sampleMode,
  selectedSample,
  groupBy,
  groupByOrder,
  showToggle,
  refreshLog,
  capabilities,
  offcanvas,
  setOffcanvas,
  samplesDescriptor,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleStatus,
  sampleError,
  sort,
  setSort,
  epochs,
  epoch,
  setEpoch,
  filter,
  setFilter,
  score,
  setScore,
  scores,
  selectedTab,
  setSelectedTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition,
}) => {
  if (!evalSpec) {
    return "";
  }

  const divRef = useRef<HTMLDivElement>(null);
  const sampleTabScrollRef = useRef<HTMLDivElement>(null);

  // Display the log
  useEffect(() => {
    if (divRef.current) {
      divRef.current.scrollTop = 0;
    }
  }, [divRef, task_id]);

  const resolvedTabs = useMemo<Record<string, TabDescriptor>>(() => {
    // Tabs that are available within the app
    // Include the tab contents as well as any tools that the tab provides
    // when it is displayed
    const resolvedTabs: Record<string, TabDescriptor> = {};

    // The samples tab
    // Currently only appears when the result is successful
    if (sampleMode !== "none") {
      resolvedTabs.samples = {
        id: kEvalWorkspaceTabId,
        scrollable: samples?.length === 1,
        scrollRef: sampleTabScrollRef,
        label: (samples || []).length > 1 ? "Samples" : "Sample",
        content: () => {
          return (
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
          );
        },
        tools: () => {
          // Don't show tools if there is a single sample
          if (sampleMode === "single" || !samplesDescriptor) {
            return undefined;
          }
          const sampleTools = [
            <SampleTools
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
          ];
          if (evalStatus === "started") {
            sampleTools.push(
              <ToolButton
                label={"Refresh"}
                icon="{ApplicationIcons.refresh}"
                onClick={refreshLog}
              />,
            );
          }

          return sampleTools;
        },
      };
    }

    // The info tab
    resolvedTabs.config = {
      id: kInfoWorkspaceTabId,
      label: "Info",
      scrollable: true,
      content: () => {
        return (
          <InfoTab
            evalSpec={evalSpec}
            evalPlan={evalPlan}
            evalError={evalError}
            evalResults={evalResults}
            evalStats={evalStats}
            samples={samples}
          />
        );
      },
    };

    // The JSON Tab
    resolvedTabs.json = {
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
        const json = JSON.stringify(evalHeader, null, 2);
        return (
          <JsonTab
            logFile={logFileName}
            json={json}
            capabilities={capabilities}
            selected={selectedTab === kJsonWorkspaceTabId}
          />
        );
      },
      tools: () => {
        return [
          <ToolButton
            label={<span className="task-btn-copy-content">Copy JSON</span>}
            icon={ApplicationIcons.copy}
            className={clsx("task-btn-json-copy", "clipboard-button")}
            data-clipboard-target="#task-json-contents"
            onClick={copyFeedback}
          />,
        ];
      },
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

    return resolvedTabs;
  }, [
    evalStatus,
    sampleMode,
    samples,
    task_id,
    score,
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
  ]);

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
