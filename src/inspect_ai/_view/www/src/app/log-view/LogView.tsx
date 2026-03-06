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

import { useEvalSpec, useRefreshLog } from "../../state/hooks";
import { useStore } from "../../state/store";
import { useLogNavigation } from "../routing/logNavigation";
import styles from "./LogView.module.css";
import { useErrorTabConfig } from "./tabs/ErrorTab";
import { useInfoTabConfig } from "./tabs/InfoTab";
import { useJsonTabConfig } from "./tabs/JsonTab";
import { useModelsTab } from "./tabs/ModelsTab";
import { useSamplesTabConfig } from "./tabs/SamplesTab";
import { useTaskTabConfig } from "./tabs/TaskTab";
import { TitleView } from "./title-view/TitleView";
import { TabDescriptor } from "./types";

export const LogView: FC = () => {
  const divRef = useRef<HTMLDivElement>(null);

  const refreshLog = useRefreshLog();
  const navigation = useLogNavigation();

  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const evalSpec = useEvalSpec();
  const runningMetrics = useStore(
    (state) => state.log.pendingSampleSummaries?.metrics,
  );

  // Use individual tab config hooks
  const samplesTabConfig = useSamplesTabConfig(
    selectedLogDetails?.status,
    refreshLog,
  );

  const intoTabConfig = useInfoTabConfig(
    evalSpec,
    selectedLogDetails?.plan,
    selectedLogDetails?.error,
    selectedLogDetails?.results,
    selectedLogDetails?.status,
  );

  const errorTabConfig = useErrorTabConfig(selectedLogDetails?.error);

  const taskTabConfig = useTaskTabConfig(
    evalSpec,
    selectedLogDetails?.stats,
    selectedLogDetails?.results?.early_stopping,
  );

  const modelsTabConfig = useModelsTab(
    evalSpec,
    selectedLogDetails?.stats,
    selectedLogDetails?.status,
  );

  const jsonTabConfig = useJsonTabConfig(
    selectedLogDetails?.version,
    selectedLogDetails?.status,
    evalSpec,
    selectedLogDetails?.plan,
    selectedLogDetails?.error,
    selectedLogDetails?.results,
    selectedLogDetails?.stats,
  );

  const tabs: Record<string, TabDescriptor<any>> = {
    ...(samplesTabConfig ? { samples: samplesTabConfig } : {}),
    task: taskTabConfig,
    model: modelsTabConfig,
    config: intoTabConfig,
    ...(selectedLogDetails?.error ? { error: errorTabConfig } : {}),
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
    [setSelectedTab, navigation],
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
        <TitleView
          evalSpec={evalSpec}
          evalPlan={selectedLogDetails?.plan}
          evalResults={selectedLogDetails?.results}
          runningMetrics={runningMetrics}
          evalStats={selectedLogDetails?.stats}
          status={selectedLogDetails?.status}
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
