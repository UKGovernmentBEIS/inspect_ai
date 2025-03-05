import clsx from "clsx";
import { FC, Fragment, MouseEvent, RefObject, useCallback } from "react";
import { RunningMetric } from "../api/types";
import { EmptyPanel } from "../components/EmptyPanel";
import { TabPanel, TabSet } from "../components/TabSet";
import {
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
  Status,
} from "../types/log";
import { debounce } from "../utils/sync";
import { Navbar } from "./navbar/Navbar";
import { TabDescriptor } from "./types";

import { useStore } from "../state/store";
import styles from "./WorkSpaceView.module.css";

interface WorkSpaceViewProps {
  evalSpec: EvalSpec;
  evalPlan?: EvalPlan;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  evalStats?: EvalStats;
  status?: Status;
  showToggle: boolean;
  tabs: Record<string, TabDescriptor>;
  divRef: RefObject<HTMLDivElement | null>;
  workspaceTabScrollPositionRef: RefObject<Record<string, number>>;
  setWorkspaceTabScrollPosition: (tab: string, pos: number) => void;
}

export const WorkSpaceView: FC<WorkSpaceViewProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  runningMetrics,
  evalStats,
  status,
  showToggle,
  tabs,
  divRef,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition,
}) => {
  const selectedTab = useStore((state) => state.app.tabs.workspace);
  const setSelectedTab = useStore((state) => state.appActions.setWorkspaceTab);

  const onSelected = useCallback(
    (e: MouseEvent<HTMLElement>) => {
      const id = e.currentTarget?.id;
      if (id) {
        setSelectedTab(id);
      }
    },
    [setSelectedTab],
  );

  const handleScroll = useCallback(
    debounce((tabId: string, position: number) => {
      setWorkspaceTabScrollPosition(tabId, position);
    }, 100),
    [setWorkspaceTabScrollPosition],
  );

  if (evalSpec === undefined) {
    return <EmptyPanel />;
  } else {
    const tabTools = Object.keys(tabs)
      .map((key) => {
        const tab = tabs[key];
        return tab;
      })
      .filter((tab) => {
        return tab.id === selectedTab;
      })
      .map((tab) => {
        if (tab.tools) {
          const tools = tab.tools();
          return tools;
        } else {
          return null;
        }
      });

    return (
      <Fragment>
        <Navbar
          evalSpec={evalSpec}
          evalPlan={evalPlan}
          evalResults={evalResults}
          runningMetrics={runningMetrics}
          evalStats={evalStats}
          status={status}
          showToggle={showToggle}
        />
        <div ref={divRef} className={clsx("workspace", styles.workspace)}>
          <div className={clsx("log-detail", styles.tabContainer)}>
            <TabSet
              id="log-details"
              tools={tabTools}
              type="pills"
              className={clsx(styles.tabSet, "text-size-smaller")}
              tabControlsClassName={clsx(styles.tabs, "text-size-smaller")}
              tabPanelsClassName={clsx(styles.tabPanels)}
            >
              {Object.keys(tabs).map((key) => {
                const tab = tabs[key];
                return (
                  <TabPanel
                    key={tab.id}
                    id={tab.id}
                    title={tab.label}
                    onSelected={onSelected}
                    selected={selectedTab === tab.id}
                    scrollable={!!tab.scrollable}
                    scrollRef={tab.scrollRef}
                    scrollPosition={
                      workspaceTabScrollPositionRef.current?.[tab.id]
                    }
                    setScrollPosition={(position: number) => {
                      handleScroll(tab.id, position);
                    }}
                  >
                    {tab.content()}
                  </TabPanel>
                );
              })}
            </TabSet>
          </div>
        </div>
      </Fragment>
    );
  }
};
