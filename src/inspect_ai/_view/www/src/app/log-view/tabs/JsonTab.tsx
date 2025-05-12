import { filename } from "../../../utils/path";

import clsx from "clsx";
import { FC, MouseEvent, useMemo } from "react";
import {
  EvalError,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
  Status,
} from "../../../@types/log";
import { DownloadPanel } from "../../../components/DownloadPanel";
import { JSONPanel } from "../../../components/JsonPanel";
import { ToolButton } from "../../../components/ToolButton";
import { kLogViewJsonTabId } from "../../../constants";
import { useStore } from "../../../state/store";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./JsonTab.module.css";

const kJsonMaxSize = 10000000;

// Individual hook for JSON tab
export const useJsonTabConfig = (
  evalVersion: number | undefined,
  evalStatus: Status | undefined,
  evalSpec: EvalSpec | undefined,
  evalPlan: EvalPlan | undefined,
  evalError: EvalError | undefined | null,
  evalResults: EvalResults | undefined | null,
  evalStats: EvalStats | undefined,
) => {
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
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
      id: kLogViewJsonTabId,
      label: "JSON",
      scrollable: true,
      component: JsonTab,
      componentProps: {
        logFile: selectedLogFile,
        json: JSON.stringify(evalHeader, null, 2),
        selected: selectedTab === kLogViewJsonTabId,
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

interface JsonTabProps {
  logFile?: string;
  selected: boolean;
  json: string;
}

/**
 * Renders JSON tab
 */
export const JsonTab: FC<JsonTabProps> = ({ logFile, json }) => {
  const downloadFiles = useStore((state) => state.capabilities.downloadFiles);
  if (logFile && json.length > kJsonMaxSize && downloadFiles) {
    // This JSON file is so large we can't really productively render it
    // we should instead just provide a DL link
    const file = `${filename(logFile)}.json`;
    return (
      <div className={styles.jsonTab}>
        <DownloadPanel
          message="The JSON for this log file is too large to render."
          buttonLabel="Download JSON File"
          fileName={file}
          fileContents={json}
        />
      </div>
    );
  } else {
    return (
      <div className={styles.jsonTab}>
        <JSONPanel id="task-json-contents" json={json} simple={true} />
      </div>
    );
  }
};
