import { TabPanel, TabSet } from "../components/TabSet";
import { MetaDataView } from "../metadata/MetaDataView";

import { escapeSelector } from "../utils/html";
import { isVscode } from "../utils/vscode";

import { ApplicationIcons } from "../appearance/icons";
import { ANSIDisplay } from "../components/AnsiDisplay";
import { ToolButton } from "../components/ToolButton";

import clsx from "clsx";
import {
  FC,
  Fragment,
  MouseEvent,
  RefObject,
  useCallback,
  useMemo,
} from "react";
import { SampleSummary } from "../api/types";
import { Card, CardBody, CardHeader } from "../components/Card";
import { JSONPanel } from "../components/JsonPanel";
import { NoContentsPanel } from "../components/NoContentsPanel";
import {
  kSampleErrorTabId,
  kSampleJsonTabId,
  kSampleMessagesTabId,
  kSampleMetdataTabId,
  kSampleScoringTabId,
  kSampleTranscriptTabId,
} from "../constants";
import { useSampleSummaries } from "../state/hooks";
import { useStore } from "../state/store";
import { EvalSample, Events } from "../types/log";
import { ModelTokenTable } from "../usage/ModelTokenTable";
import { formatTime } from "../utils/format";
import { printHeadingHtml, printHtml } from "../utils/print";
import { ChatViewVirtualList } from "./chat/ChatViewVirtualList";
import { messagesFromEvents } from "./chat/messages";
import styles from "./SampleDisplay.module.css";
import { SampleSummaryView } from "./SampleSummaryView";
import { SampleScoresView } from "./scores/SampleScoresView";
import { TranscriptVirtualList } from "./transcript/TranscriptView";

interface SampleDisplayProps {
  id: string;
  sample?: EvalSample;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  scrollRef: RefObject<HTMLDivElement | null>;
  runningEvents?: Events;
}

/**
 * Component to display a sample with relevant context and visibility control.
 */
export const SampleDisplay: FC<SampleDisplayProps> = ({
  id,
  sample,
  selectedTab,
  setSelectedTab,
  scrollRef,
  runningEvents: runningSampleData,
}) => {
  // Tab ids
  const baseId = `sample-dialog`;
  const sampleSummaries = useSampleSummaries();
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );

  const sampleSummary = sampleSummaries[selectedSampleIndex];

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

  // Tab selection
  const onSelectedTab = (e: MouseEvent<HTMLElement>) => {
    const el = e.currentTarget as HTMLElement;
    const id = el.id;
    setSelectedTab(id);
    return false;
  };

  const sampleMetadatas = metadataViewsForSample(`${baseId}-${id}`, sample);

  const tabsetId = `task-sample-details-tab-${id}`;
  const targetId = `${tabsetId}-content`;

  const handlePrintClick = useCallback(() => {
    printSample(id, targetId);
  }, [printSample, id, targetId]);

  const tools = [];
  if (!isVscode()) {
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
  const running = isRunning(sampleSummary, runningSampleData);

  return (
    <Fragment>
      {sample || sampleSummary ? (
        <SampleSummaryView parent_id={id} sample={sample || sampleSummary} />
      ) : undefined}
      <TabSet
        id={tabsetId}
        tabControlsClassName={clsx("text-size-base")}
        tabPanelsClassName={clsx(styles.tabPanel)}
        tools={tools}
      >
        <TabPanel
          key={kSampleTranscriptTabId}
          id={kSampleTranscriptTabId}
          className="sample-tab"
          title="Transcript"
          onSelected={onSelectedTab}
          selected={
            selectedTab === kSampleTranscriptTabId || selectedTab === undefined
          }
          scrollable={false}
        >
          <TranscriptVirtualList
            key={`${baseId}-transcript-display-${id}`}
            id={`${baseId}-transcript-display-${id}`}
            events={sampleEvents || []}
            running={running}
            scrollRef={scrollRef}
          />
        </TabPanel>
        <TabPanel
          key={kSampleMessagesTabId}
          id={kSampleMessagesTabId}
          className={clsx("sample-tab", styles.fullWidth, styles.chat)}
          title="Messages"
          onSelected={onSelectedTab}
          selected={selectedTab === kSampleMessagesTabId}
          scrollable={false}
        >
          <ChatViewVirtualList
            key={`${baseId}-chat-${id}`}
            id={`${baseId}-chat-${id}`}
            messages={sampleMessages}
            indented={true}
            scrollRef={scrollRef}
            toolCallStyle="complete"
            running={running}
          />
        </TabPanel>
        <TabPanel
          key={kSampleScoringTabId}
          id={kSampleScoringTabId}
          className="sample-tab"
          title="Scoring"
          onSelected={onSelectedTab}
          selected={selectedTab === kSampleScoringTabId}
        >
          <SampleScoresView sample={sample} />
        </TabPanel>
        <TabPanel
          id={kSampleMetdataTabId}
          className={clsx("sample-tab")}
          title="Metadata"
          onSelected={onSelectedTab}
          selected={selectedTab === kSampleMetdataTabId}
        >
          {sampleMetadatas.length > 0 ? (
            <div className={clsx(styles.metadataPanel)}>{sampleMetadatas}</div>
          ) : (
            <NoContentsPanel text="No metadata" />
          )}
        </TabPanel>
        {sample?.error ? (
          <TabPanel
            id={kSampleErrorTabId}
            className="sample-tab"
            title="Error"
            onSelected={onSelectedTab}
            selected={selectedTab === kSampleErrorTabId}
          >
            <div className={clsx(styles.padded)}>
              <ANSIDisplay
                output={sample.error.traceback_ansi}
                className={clsx("text-size-small", styles.ansi)}
              />
            </div>
          </TabPanel>
        ) : null}
        <TabPanel
          id={kSampleJsonTabId}
          className={"sample-tab"}
          title="JSON"
          onSelected={onSelectedTab}
          selected={selectedTab === kSampleJsonTabId}
        >
          {!sample ? (
            <NoContentsPanel text="JSON not available" />
          ) : sample.messages.length > 100 ? (
            <NoContentsPanel text="JSON too large too display" />
          ) : (
            <div className={clsx(styles.padded, styles.fullWidth)}>
              <JSONPanel
                data={sample}
                simple={true}
                className={clsx("text-size-small")}
              />
            </div>
          )}
        </TabPanel>
      </TabSet>
    </Fragment>
  );
};

const metadataViewsForSample = (id: string, sample?: EvalSample) => {
  if (!sample) {
    return [];
  }
  const sampleMetadatas = [];

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
        <CardBody>
          <div className={clsx(styles.timePanel, "text-size-smaller")}>
            <div className={clsx("text-style-label", "text-style-secondary")}>
              Working
            </div>
            <div>{formatTime(sample.working_time)}</div>
            <div className={clsx("text-style-label", "text-style-secondary")}>
              Total
            </div>
            <div>{formatTime(sample.total_time)}</div>
          </div>
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.metadata).length > 0) {
    sampleMetadatas.push(
      <Card key={`sample-metadata-${id}`}>
        <CardHeader label="Metadata" />
        <CardBody>
          <MetaDataView
            id="task-sample-metadata-${id}"
            entries={sample?.metadata as Record<string, unknown>}
            className={clsx("tab-pane", styles.noTop)}
          />
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.store).length > 0) {
    sampleMetadatas.push(
      <Card key={`sample-store-${id}`}>
        <CardHeader label="Store" />
        <CardBody>
          <MetaDataView
            id="task-sample-store-${id}"
            entries={sample?.store as Record<string, unknown>}
            className={clsx("tab-pane", styles.noTop)}
          />
        </CardBody>
      </Card>,
    );
  }

  return sampleMetadatas;
};
const printSample = (id: string, targetId: string) => {
  // The active tab
  const targetTabEl = document.querySelector(
    `#${escapeSelector(targetId)} .sample-tab.tab-pane.show.active`,
  );
  if (targetTabEl) {
    // The target element
    const targetEl = targetTabEl.firstElementChild;
    if (targetEl) {
      // Get the sample heading to include
      const headingId = `sample-heading-${id}`;
      const headingEl = document.getElementById(headingId);

      // Print the document
      const headingHtml = printHeadingHtml();
      const css = `
      html { font-size: 9pt }
      /* Allow content to break anywhere without any forced page breaks */
      * {
        break-inside: auto;  /* Let elements break anywhere */
        page-break-inside: auto;  /* Legacy support */
        break-before: auto;
        page-break-before: auto;
        break-after: auto;
        page-break-after: auto;
      }
      /* Specifically disable all page breaks for divs */
      div {
        break-inside: auto;
        page-break-inside: auto;
      }
      body > .transcript-step {
        break-inside: avoid;
      }
      body{
        -webkit-print-color-adjust:exact !important;
        print-color-adjust:exact !important;
      }
      /* Allow preformatted text and code blocks to break across pages */
      pre, code {
          white-space: pre-wrap; /* Wrap long lines instead of keeping them on one line */
          overflow-wrap: break-word; /* Ensure long words are broken to fit within the page */
          break-inside: auto; /* Allow page breaks inside the element */
          page-break-inside: auto; /* Older equivalent */
      }

      /* Additional control for long lines within code/preformatted blocks */
      pre {
          word-wrap: break-word; /* Break long words if needed */
      }    
          
      `;
      printHtml(
        [headingHtml, headingEl?.outerHTML, targetEl.innerHTML].join("\n"),
        css,
      );
    }
  }
};

const isRunning = (
  sampleSummary?: SampleSummary,
  runningSampleData?: Events,
): boolean => {
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
