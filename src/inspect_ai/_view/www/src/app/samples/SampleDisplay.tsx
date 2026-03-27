import { TabPanel, TabSet } from "../../components/TabSet";

import { isVscode } from "../../utils/vscode";

import { ANSIDisplay } from "../../components/AnsiDisplay";
import { ToolButton } from "../../components/ToolButton";
import { ToolDropdownButton } from "../../components/ToolDropdownButton";
import { ApplicationIcons } from "../appearance/icons";

import clsx from "clsx";
import {
  FC,
  Fragment,
  MouseEvent,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { EvalSample, Events } from "../../@types/log";
import { SampleSummary } from "../../client/api/types";
import { ActivityBar } from "../../components/ActivityBar";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { NoContentsPanel } from "../../components/NoContentsPanel";
import {
  kSampleErrorTabId,
  kSampleJsonTabId,
  kSampleMessagesTabId,
  kSampleMetdataTabId,
  kSampleScoringTabId,
  kSampleTranscriptTabId,
} from "../../constants";
import {
  useDocumentTitle,
  useSampleData,
  useSelectedSampleSummary,
} from "../../state/hooks";
import { useStore } from "../../state/store";
import { formatDateTime, formatTime } from "../../utils/format";
import { RecordTree } from "../content/RecordTree";
import { useSampleDetailNavigation } from "../routing/sampleNavigation";
import {
  printSampleUrl,
  useLogOrSampleRouteParams,
  useSampleUrlBuilder,
} from "../routing/url";
import { messagesToStr } from "../shared/messages";
import { ModelTokenTable } from "../usage/ModelTokenTable";
import { ChatViewVirtualList } from "./chat/ChatViewVirtualList";
import { messagesFromEvents } from "./chat/messages";
import styles from "./SampleDisplay.module.css";
import { SampleSummaryView } from "./SampleSummaryView";
import { SampleJSONView } from "./SampleJSONView";
import { SampleScoresView } from "./scores/SampleScoresView";
import { useTranscriptFilter } from "./transcript/hooks";
import { TranscriptFilterPopover } from "./transcript/TranscriptFilter";
import { TranscriptPanel } from "./transcript/TranscriptPanel";

interface SampleDisplayProps {
  id: string;
  scrollRef: RefObject<HTMLDivElement | null>;
  showActivity: boolean;
  progress?: number;
  focusOnLoad?: boolean;
}

/**
 * Component to display a sample with relevant context and visibility control.
 */
export const SampleDisplay: FC<SampleDisplayProps> = ({
  id,
  scrollRef,
  showActivity,
  progress,
  focusOnLoad,
}) => {
  // Tab ids
  const baseId = `sample-display`;

  const sampleData = useSampleData();
  const sample = useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);
  const eventsCleared = sampleData.eventsCleared;

  const runningSampleData = sampleData.running;

  const evalSpec = useStore((state) => state.log.selectedLogDetails?.eval);
  const { setDocumentTitle } = useDocumentTitle();
  useEffect(() => {
    setDocumentTitle({ evalSpec, sample });
  }, [setDocumentTitle, sample, evalSpec]);

  // Selected tab handling
  const selectedTab = useStore((state) => state.app.tabs.sample);
  const setSelectedTab = useStore((state) => state.appActions.setSampleTab);

  // Get sample tab from URL if available
  const { sampleTabId } = useParams<{ sampleTabId?: string }>();

  // Use sampleTabId from URL if available, otherwise use the one from state
  const effectiveSelectedTab = sampleTabId || selectedTab;

  // Navigation hook for URL updates
  const navigate = useNavigate();

  // Ref for samples tabs (used to measure for offset)
  const tabsRef: RefObject<HTMLUListElement | null> = useRef(null);
  const [tabsHeight, setTabsHeight] = useState(-1);

  useEffect(() => {
    const updateHeight = () => {
      if (tabsRef.current) {
        const height = tabsRef.current.getBoundingClientRect().height;
        setTabsHeight(height);
      }
    };
    updateHeight();

    window.addEventListener("resize", updateHeight);
    return () => window.removeEventListener("resize", updateHeight);
  }, []);

  const selectedSampleSummary = useSelectedSampleSummary();

  // Consolidate the events and messages into the proper list
  // whether running or not
  const sampleEvents = sample?.events || runningSampleData;
  const sampleMessages = useMemo(() => {
    if (sample?.messages) {
      return sample.messages;
    } else if (runningSampleData) {
      return messagesFromEvents(runningSampleData);
    } else {
      return [];
    }
  }, [sample?.messages, runningSampleData]);

  const hasSampleData =
    sample !== undefined ||
    sampleEvents !== undefined ||
    sampleMessages !== undefined;

  // Get all URL parameters at component level
  const {
    logPath: urlLogPath,
    id: urlSampleId,
    epoch: urlEpoch,
  } = useLogOrSampleRouteParams();

  // Focus the panel when it loads
  useEffect(() => {
    setTimeout(() => {
      if (focusOnLoad) {
        scrollRef.current?.focus();
      }
    }, 10);
  }, [focusOnLoad, scrollRef]);

  // Tab selection
  const sampleUrlBuilder = useSampleUrlBuilder();
  const onSelectedTab = useCallback(
    (e: MouseEvent<HTMLElement>) => {
      const el = e.currentTarget as HTMLElement;
      const id = el.id;
      setSelectedTab(id);

      // Use navigation hook to update URL with tab
      if (id !== sampleTabId && urlLogPath) {
        const url = sampleUrlBuilder(urlLogPath, urlSampleId, urlEpoch, id);
        navigate(url);
      }
    },
    [
      setSelectedTab,
      sampleTabId,
      urlLogPath,
      sampleUrlBuilder,
      urlSampleId,
      urlEpoch,
      navigate,
    ],
  );

  const sampleMetadatas = metadataViewsForSample(
    `${baseId}-${id}`,
    scrollRef,
    sample,
  );

  const tabsetId = `task-sample-details-tab-${id}`;

  const isShowing = useStore((state) => state.app.dialogs.transcriptFilter);
  const setShowing = useStore(
    (state) => state.appActions.setShowingTranscriptFilterDialog,
  );

  const displayMode = useStore((state) => state.app.displayMode);
  const setDisplayMode = useStore((state) => state.appActions.setDisplayMode);

  const filterRef = useRef<HTMLButtonElement | null>(null);
  const optionsRef = useRef<HTMLButtonElement | null>(null);

  // Fall back to store state for single-file mode where URL doesn't contain sample ID/epoch
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );
  const printLogPath = urlLogPath || selectedLogFile;
  const printSampleId = urlSampleId || selectedSampleHandle?.id?.toString();
  const printEpoch = urlEpoch || selectedSampleHandle?.epoch?.toString();

  const handlePrintClick = useCallback(() => {
    if (printLogPath && printSampleId && printEpoch) {
      const printUrl = printSampleUrl(
        printLogPath,
        printSampleId,
        printEpoch,
        effectiveSelectedTab,
      );
      window.open(`#${printUrl}`, "_blank");
    }
  }, [printLogPath, printSampleId, printEpoch, effectiveSelectedTab]);

  // Intercept Cmd+P / Ctrl+P to use custom print route
  useEffect(() => {
    if (isVscode() || !printLogPath || !printSampleId || !printEpoch) return;

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        e.stopPropagation();
        handlePrintClick();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [handlePrintClick, printLogPath, printSampleId, printEpoch]);

  const toggleFilter = useCallback(() => {
    setShowing(!isShowing);
  }, [setShowing, isShowing]);

  const toggleDisplayMode = useCallback(() => {
    setDisplayMode(displayMode === "rendered" ? "raw" : "rendered");
  }, [displayMode, setDisplayMode]);

  const collapsedMode = useStore((state) => state.sample.collapsedMode);
  const setCollapsedMode = useStore(
    (state) => state.sampleActions.setCollapsedMode,
  );

  const isCollapsed = (mode: "collapsed" | "expanded" | null) => {
    return mode === "collapsed"; //null is expanded
  };

  const toggleCollapsedMode = useCallback(() => {
    setCollapsedMode(isCollapsed(collapsedMode) ? "expanded" : "collapsed");
  }, [collapsedMode, setCollapsedMode]);

  const { isDebugFilter, isDefaultFilter, isNoneFilter } =
    useTranscriptFilter();

  const api = useStore((state) => state.api);
  const downloadFiles = useStore((state) => state.capabilities.downloadFiles);

  const tools = [];
  const [icon, setIcon] = useState(ApplicationIcons.copy);

  tools.push(
    <ToolDropdownButton
      key="sample-copy"
      label="Copy"
      icon={icon}
      items={{
        UUID: () => {
          if (sample?.uuid) {
            navigator.clipboard.writeText(sample.uuid);
            setIcon(ApplicationIcons.confirm);
            setTimeout(() => {
              setIcon(ApplicationIcons.copy);
            }, 1250);
          }
        },
        Transcript: () => {
          if (sample?.messages) {
            navigator.clipboard.writeText(messagesToStr(sample.messages));
            setIcon(ApplicationIcons.confirm);
            setTimeout(() => {
              setIcon(ApplicationIcons.copy);
            }, 1250);
          }
        },
      }}
    />,
  );

  if (downloadFiles && sample && api?.download_file) {
    const sampleId = sample.id ?? "sample";
    tools.push(
      <ToolDropdownButton
        key="sample-download"
        label="Download"
        icon={ApplicationIcons.downloadLog}
        items={{
          "Sample JSON": () => {
            api.download_file(
              `${sampleId}.json`,
              JSON.stringify(sample, null, 2),
            );
          },
          Transcript: () => {
            api.download_file(
              `${sampleId}-transcript.txt`,
              messagesToStr(sample.messages ?? []),
            );
          },
        }}
      />,
    );
  }

  if (selectedTab === kSampleTranscriptTabId) {
    const label = isNoneFilter
      ? "None"
      : isDebugFilter
        ? "Debug"
        : isDefaultFilter
          ? "Default"
          : "Custom";

    tools.push(
      <ToolButton
        key="sample-filter-transcript"
        label={`Events: ${label}`}
        icon={ApplicationIcons.filter}
        onClick={toggleFilter}
        ref={filterRef}
      />,
    );

    tools.push(
      <ToolButton
        key="sample-collapse-transcript"
        label={isCollapsed(collapsedMode) ? "Expand" : "Collapse"}
        icon={
          isCollapsed(collapsedMode)
            ? ApplicationIcons.expand.all
            : ApplicationIcons.collapse.all
        }
        onClick={toggleCollapsedMode}
      />,
    );
  }

  tools.push(
    <ToolButton
      key="options-button"
      label={"Raw"}
      icon={ApplicationIcons.display}
      onClick={toggleDisplayMode}
      ref={optionsRef}
      latched={displayMode === "raw"}
    />,
  );

  if (!isVscode() && printLogPath && printSampleId && printEpoch) {
    tools.push(
      <ToolButton
        key="sample-print-tool"
        label="Print"
        icon={ApplicationIcons.copy}
        onClick={handlePrintClick}
      />,
    );
  }

  // Is the sample running?
  const running = useMemo(() => {
    return isRunning(
      selectedSampleSummary,
      runningSampleData,
      sampleData.status,
    );
  }, [selectedSampleSummary, runningSampleData, sampleData.status]);

  const sampleDetailNavigation = useSampleDetailNavigation();

  return (
    <Fragment>
      {selectedSampleSummary ? (
        <SampleSummaryView parent_id={id} sample={selectedSampleSummary} />
      ) : undefined}
      <ActivityBar animating={showActivity} progress={progress} />

      {hasSampleData && (
        <TabSet
          id={tabsetId}
          tabsRef={tabsRef}
          className={clsx(styles.tabControls)}
          tabControlsClassName={clsx("text-size-base")}
          tabPanelsClassName={clsx(styles.tabPanel)}
          tools={tools}
        >
          <TabPanel
            key={kSampleTranscriptTabId}
            id={kSampleTranscriptTabId}
            className={clsx(
              "sample-tab",
              styles.transcriptContainer,
              styles.overflowVisible,
            )}
            title="Transcript"
            onSelected={onSelectedTab}
            selected={
              effectiveSelectedTab === kSampleTranscriptTabId ||
              effectiveSelectedTab === undefined
            }
            scrollable={false}
          >
            <TranscriptFilterPopover
              showing={isShowing}
              setShowing={setShowing}
              positionEl={filterRef.current}
            />

            <TranscriptPanel
              key={`${baseId}-transcript-display-${id}`}
              id={`${baseId}-transcript-display-${id}`}
              events={sampleEvents || []}
              eventsCleared={eventsCleared}
              initialEventId={sampleDetailNavigation.event}
              topOffset={tabsHeight}
              running={running}
              scrollRef={scrollRef}
            />
          </TabPanel>
          <TabPanel
            key={kSampleMessagesTabId}
            id={kSampleMessagesTabId}
            className={clsx(
              "sample-tab",
              styles.fullWidth,
              styles.chat,
              styles.overflowVisible,
            )}
            title="Messages"
            onSelected={onSelectedTab}
            selected={effectiveSelectedTab === kSampleMessagesTabId}
            scrollable={false}
          >
            <ChatViewVirtualList
              key={`${baseId}-chat-${id}`}
              id={`${baseId}-chat-${id}`}
              messages={sampleMessages}
              initialMessageId={sampleDetailNavigation.message}
              topOffset={tabsHeight}
              indented={true}
              scrollRef={scrollRef}
              toolCallStyle="complete"
              running={running}
              className={styles.fullWidth}
            />
          </TabPanel>
          <TabPanel
            key={kSampleScoringTabId}
            id={kSampleScoringTabId}
            className="sample-tab"
            title="Scoring"
            onSelected={onSelectedTab}
            selected={effectiveSelectedTab === kSampleScoringTabId}
          >
            <SampleScoresView
              sample={sample}
              className={styles.padded}
              scrollRef={scrollRef}
            />
          </TabPanel>
          <TabPanel
            id={kSampleMetdataTabId}
            className={clsx("sample-tab")}
            title="Metadata"
            onSelected={onSelectedTab}
            selected={effectiveSelectedTab === kSampleMetdataTabId}
          >
            {sampleMetadatas.length > 0 ? (
              <div className={clsx(styles.padded, styles.fullWidth)}>
                {sampleMetadatas}
              </div>
            ) : (
              <NoContentsPanel text="No sample metadata available" />
            )}
          </TabPanel>
          {sample?.error ||
          (sample?.error_retries && sample?.error_retries.length > 0) ? (
            <TabPanel
              id={kSampleErrorTabId}
              className="sample-tab"
              title="Errors"
              onSelected={onSelectedTab}
              selected={effectiveSelectedTab === kSampleErrorTabId}
            >
              <div className={clsx(styles.error)}>
                {sample?.error ? (
                  <Card key={`sample-error}`}>
                    <CardHeader label={`Sample Error`} />
                    <CardBody>
                      <ANSIDisplay
                        output={sample.error.traceback_ansi}
                        className={clsx("text-size-small", styles.ansi)}
                        style={{
                          fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
                          margin: "0.5em 0",
                        }}
                      />
                    </CardBody>
                  </Card>
                ) : undefined}
                {sample.error_retries?.map((retry, index) => {
                  return (
                    <Card key={`sample-retry-error-${index}`}>
                      <CardHeader label={`Attempt ${index + 1}`} />
                      <CardBody>
                        <ANSIDisplay
                          output={retry.traceback_ansi}
                          className={clsx("text-size-small", styles.ansi)}
                          style={{
                            fontSize: "clamp(0.3rem, 1.1vw, 0.8rem)",
                            margin: "0.5em 0",
                          }}
                        />
                      </CardBody>
                    </Card>
                  );
                })}
              </div>
            </TabPanel>
          ) : null}
          <TabPanel
            id={kSampleJsonTabId}
            className={"sample-tab"}
            title="JSON"
            onSelected={onSelectedTab}
            selected={effectiveSelectedTab === kSampleJsonTabId}
          >
            {!sample ? (
              <NoContentsPanel text="JSON not available" />
            ) : (
              <div className={clsx(styles.padded, styles.fullWidth)}>
                <SampleJSONView
                  sample={sample}
                  className={clsx("text-size-small")}
                />
              </div>
            )}
          </TabPanel>
        </TabSet>
      )}
    </Fragment>
  );
};

const metadataViewsForSample = (
  id: string,
  scrollRef: RefObject<HTMLDivElement | null>,
  sample?: EvalSample,
) => {
  if (!sample) {
    return [];
  }
  const sampleMetadatas = [];

  // Show invalidation details prominently if sample is invalidated
  if (sample.invalidation) {
    const formatTimestamp = (timestamp: string) => {
      try {
        return formatDateTime(new Date(timestamp));
      } catch {
        return timestamp;
      }
    };

    const invalidationRecord: Record<string, unknown> = {};
    if (sample.invalidation.author) {
      invalidationRecord["Author"] = sample.invalidation.author;
    }
    if (sample.invalidation.timestamp) {
      invalidationRecord["Timestamp"] = formatTimestamp(
        sample.invalidation.timestamp,
      );
    }
    if (sample.invalidation.reason) {
      invalidationRecord["Reason"] = sample.invalidation.reason;
    }
    if (
      sample.invalidation.metadata &&
      Object.keys(sample.invalidation.metadata).length > 0
    ) {
      invalidationRecord["Metadata"] = sample.invalidation.metadata;
    }

    sampleMetadatas.push(
      <Card key={`sample-invalidation-${id}`}>
        <CardHeader label="Invalidation" />
        <CardBody padded={false}>
          <RecordTree
            id={`task-sample-invalidation-${id}`}
            record={invalidationRecord}
            className={clsx("tab-pane", styles.noTop)}
            scrollRef={scrollRef}
          />
        </CardBody>
      </Card>,
    );
  }

  if (sample.model_usage && Object.keys(sample.model_usage).length > 0) {
    sampleMetadatas.push(
      <Card key={`sample-usage-${id}`}>
        <CardHeader label="Usage" />
        <CardBody>
          <ModelTokenTable
            model_usage={sample.model_usage}
            className={clsx(styles.noTop)}
          />
        </CardBody>
      </Card>,
    );
  }

  if (
    sample.total_time !== undefined &&
    sample.total_time !== null &&
    sample.working_time !== undefined &&
    sample.working_time !== null
  ) {
    sampleMetadatas.push(
      <Card key={`sample-time-${id}`}>
        <CardHeader label="Time" />
        <CardBody padded={false}>
          <RecordTree
            id={`task-sample-time-${id}`}
            record={{
              Working: formatTime(sample.working_time),
              Total: formatTime(sample.total_time),
            }}
            className={clsx("tab-pane", styles.noTop)}
            scrollRef={scrollRef}
          />
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.metadata).length > 0) {
    sampleMetadatas.push(
      <Card key={`sample-metadata-${id}`}>
        <CardHeader label="Metadata" />
        <CardBody padded={false}>
          <RecordTree
            id={`task-sample-metadata-${id}`}
            record={sample?.metadata as Record<string, unknown>}
            className={clsx("tab-pane", styles.noTop)}
            scrollRef={scrollRef}
          />
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.store).length > 0) {
    sampleMetadatas.push(
      <Card key={`sample-store-${id}`}>
        <CardHeader label="Store" />
        <CardBody padded={false}>
          <RecordTree
            id={`task-sample-store-${id}`}
            record={sample?.store as Record<string, unknown>}
            className={clsx("tab-pane", styles.noTop)}
            scrollRef={scrollRef}
            processStore={true}
          />
        </CardBody>
      </Card>,
    );
  }

  return sampleMetadatas;
};

const isRunning = (
  sampleSummary?: SampleSummary,
  runningSampleData?: Events,
  sampleStatus?: string,
): boolean => {
  // If a completed sample has been loaded, it's not running
  if (sampleStatus === "ok") {
    return false;
  }

  if (sampleSummary && sampleSummary.completed === false) {
    // An explicitly incomplete sample summary
    return true;
  }

  if (
    !sampleSummary &&
    (!runningSampleData || runningSampleData.length === 0)
  ) {
    // No sample summary yet and no running samples, must've just started
    return true;
  }

  if (runningSampleData && runningSampleData.length > 0) {
    // There are running samples
    return true;
  }

  return false;
};
