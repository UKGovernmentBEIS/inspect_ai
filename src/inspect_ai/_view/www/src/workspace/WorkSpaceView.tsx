import clsx from "clsx";
import { Fragment, MouseEvent, RefObject, useCallback, useMemo } from "react";
import { SampleSummary } from "../api/types";
import { EmptyPanel } from "../components/EmptyPanel";
import { TabPanel, TabSet } from "../components/TabSet";
import { EvalDescriptor } from "../samples/descriptor/types";
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

import styles from "./WorkSpaceView.module.css";

interface WorkSpaceViewProps {
  logFileName?: string;
  evalSpec: EvalSpec;
  evalPlan?: EvalPlan;
  evalResults?: EvalResults;
  evalStats?: EvalStats;
  samples?: SampleSummary[];
  evalDescriptor?: EvalDescriptor;
  status?: Status;
  showToggle: boolean;
  tabs: Record<string, TabDescriptor>;
  selectedTab: string;
  setSelectedTab: (tab: string) => void;
  divRef: RefObject<HTMLDivElement | null>;
  offcanvas: boolean;
  setOffcanvas: (offcanvas: boolean) => void;
  workspaceTabScrollPositionRef: RefObject<Record<string, number>>;
  setWorkspaceTabScrollPosition: (tab: string, pos: number) => void;
}

export const WorkSpaceView: React.FC<WorkSpaceViewProps> = ({
  logFileName,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  evalDescriptor,
  status,
  showToggle,
  selectedTab,
  tabs,
  setSelectedTab,
  divRef,
  offcanvas,
  setOffcanvas,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition,
}) => {
  const debouncedScroll = useMemo(() => {
    return debounce((id, position) => {
      setWorkspaceTabScrollPosition(id, position);
    }, 100);
  }, [setWorkspaceTabScrollPosition]);

  const onScroll = useCallback(
    (id: string, position: number) => {
      debouncedScroll(id, position);
    },
    [debouncedScroll],
  );

  const onSelected = useCallback(
    (e: MouseEvent<HTMLElement>) => {
      const id = e.currentTarget?.id;
      if (id) {
        setSelectedTab(id);
      }
    },
    [setSelectedTab],
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
          evalStats={evalStats}
          samples={samples}
          evalDescriptor={evalDescriptor}
          status={status}
          file={logFileName}
          showToggle={showToggle}
          offcanvas={offcanvas}
          setOffcanvas={setOffcanvas}
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
                    setScrollPosition={useCallback(
                      (position: number) => {
                        onScroll(tab.id, position);
                      },
                      [onScroll],
                    )}
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
