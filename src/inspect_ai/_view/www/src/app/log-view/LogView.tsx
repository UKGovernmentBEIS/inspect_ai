import clsx from "clsx";
import {
  createElement,
  FC,
  Fragment,
  MouseEvent,
  useCallback,
  useRef,
} from "react";
import { EmptyPanel } from "../../components/EmptyPanel";
import { TabPanel, TabSet } from "../../components/TabSet";
import { Navbar } from "./navbar/Navbar";

import { useEvalSpec, useRefreshLog } from "../../state/hooks";
import { useStore } from "../../state/store";
import { useLogNavigation } from "../routing/logNavigation";
import styles from "./LogView.module.css";
import { useInfoTabConfig } from "./tabs/InfoTab";
import { useJsonTabConfig } from "./tabs/JsonTab";
import { useModelsTab } from "./tabs/ModelsTab";
import { useSamplesTabConfig } from "./tabs/SamplesTab";
import { useTaskTabConfig } from "./tabs/TaskTab";
import { TabDescriptor } from "./types";

export const LogView: FC = () => {
  const divRef = useRef<HTMLDivElement>(null);

  const refreshLog = useRefreshLog();
  const navigation = useLogNavigation();

  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const evalSpec = useEvalSpec();
  const runningMetrics = useStore(
    (state) => state.log.pendingSampleSummaries?.metrics,
  );
  const logs = useStore((state) => state.logs.logs);
  const showToggle = logs.files.length > 1 || !!logs.log_dir || false;

  // Use individual tab config hooks
  const samplesTabConfig = useSamplesTabConfig(
    selectedLogSummary?.status,
    refreshLog,
  );

  const configTabConfig = useInfoTabConfig(
    evalSpec,
    selectedLogSummary?.plan,
    selectedLogSummary?.error,
    selectedLogSummary?.results,
  );

  const taskTabConfig = useTaskTabConfig(evalSpec, selectedLogSummary?.stats);

  const modelsTabConfig = useModelsTab(
    evalSpec,
    selectedLogSummary?.stats,
    selectedLogSummary?.status,
  );

  const jsonTabConfig = useJsonTabConfig(
    selectedLogSummary?.version,
    selectedLogSummary?.status,
    evalSpec,
    selectedLogSummary?.plan,
    selectedLogSummary?.error,
    selectedLogSummary?.results,
    selectedLogSummary?.stats,
  );

  const tabs: Record<string, TabDescriptor<any>> = {
    ...(samplesTabConfig ? { samples: samplesTabConfig } : {}),
    task: taskTabConfig,
    model: modelsTabConfig,
    config: configTabConfig,
    json: jsonTabConfig,
  };

  const selectedTab = useStore((state) => state.app.tabs.workspace);
  const setSelectedTab = useStore((state) => state.appActions.setWorkspaceTab);

  const onSelected = useCallback(
    (e: MouseEvent<HTMLElement>) => {
      const id = e.currentTarget?.id;
      if (id) {
        setSelectedTab(id);
        navigation.selectTab(id);
      }
    },
    [setSelectedTab, navigation.selectTab],
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
          evalPlan={selectedLogSummary?.plan}
          evalResults={selectedLogSummary?.results}
          runningMetrics={runningMetrics}
          evalStats={selectedLogSummary?.stats}
          status={selectedLogSummary?.status}
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
                    className={clsx(tab.className)}
                    style={{ height: tab.scrollable ? "100%" : undefined }}
                  >
                    {createElement(tab.component, tab.componentProps)}
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
