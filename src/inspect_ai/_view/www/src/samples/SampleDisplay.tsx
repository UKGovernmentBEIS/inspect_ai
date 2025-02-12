import { TabPanel, TabSet } from "../components/TabSet";
import { MetaDataView } from "../metadata/MetaDataView";

import { escapeSelector } from "../utils/html";
import { isVscode } from "../utils/vscode";

import { ApplicationIcons } from "../appearance/icons";
import { ANSIDisplay } from "../components/AnsiDisplay";
import { ToolButton } from "../components/ToolButton";
import { SampleScoreView } from "./scores/SampleScoreView";

import clsx from "clsx";
import { Fragment, MouseEvent, RefObject } from "react";
import { Card, CardBody, CardHeader } from "../components/Card";
import { EmptyPanel } from "../components/EmptyPanel";
import { JSONPanel } from "../components/JsonPanel";
import {
  kSampleErrorTabId,
  kSampleJsonTabId,
  kSampleMessagesTabId,
  kSampleMetdataTabId,
  kSampleScoringTabId,
  kSampleTranscriptTabId,
} from "../constants";
import { EvalSample } from "../types/log";
import { ModelTokenTable } from "../usage/ModelTokenTable";
import { printHeadingHtml, printHtml } from "../utils/print";
import { ChatViewVirtualList } from "./chat/ChatViewVirtualList";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";
import styles from "./SampleDisplay.module.css";
import { SampleSummaryView } from "./SampleSummaryView";
import { SampleTranscript } from "./transcript/SampleTranscript";

interface SampleDisplayProps {
  id: string;
  sample?: EvalSample;
  sampleDescriptor: SamplesDescriptor;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Component to display a sample with relevant context and visibility control.
 */
export const SampleDisplay: React.FC<SampleDisplayProps> = ({
  id,
  sample,
  sampleDescriptor,
  selectedTab,
  setSelectedTab,
  scrollRef,
}) => {
  // Tab ids
  const baseId = `sample-dialog`;

  if (!sample) {
    // Placeholder
    return <EmptyPanel />;
  }

  // Tab selection
  const onSelectedTab = (e: MouseEvent<HTMLElement>) => {
    const el = e.currentTarget as HTMLElement;
    const id = el.id;
    setSelectedTab(id);
    return false;
  };

  const scorerNames = Object.keys(sample.scores || {});
  const sampleMetadatas = metadataViewsForSample(`${baseId}-${id}`, sample);

  const tabsetId = `task-sample-details-tab-${id}`;
  const targetId = `${tabsetId}-content`;

  const tools = [];
  if (!isVscode()) {
    tools.push(
      <ToolButton
        key="sample-print-tool"
        label="Print"
        icon={ApplicationIcons.copy}
        onClick={() => {
          printSample(id, targetId);
        }}
      />,
    );
  }

  return (
    <Fragment>
      <SampleSummaryView
        parent_id={id}
        sample={sample}
        sampleDescriptor={sampleDescriptor}
      />
      <TabSet
        id={tabsetId}
        tabControlsClassName={clsx("text-size-base")}
        tabPanelsClassName={clsx(styles.tabPanel)}
        tools={tools}
      >
        {sample.events && sample.events.length > 0 ? (
          <TabPanel
            key={kSampleTranscriptTabId}
            id={kSampleTranscriptTabId}
            className="sample-tab"
            title="Transcript"
            onSelected={onSelectedTab}
            selected={
              selectedTab === kSampleTranscriptTabId ||
              selectedTab === undefined
            }
            scrollable={false}
          >
            <SampleTranscript
              key={`${baseId}-transcript-display-${id}`}
              id={`${baseId}-transcript-display-${id}`}
              evalEvents={sample.events}
              scrollRef={scrollRef}
            />
          </TabPanel>
        ) : null}
        <TabPanel
          key={kSampleMessagesTabId}
          id={kSampleMessagesTabId}
          className={clsx("sample-tab", styles.fullWidth)}
          title="Messages"
          onSelected={onSelectedTab}
          selected={selectedTab === kSampleMessagesTabId}
          scrollable={false}
        >
          <ChatViewVirtualList
            key={`${baseId}-chat-${id}`}
            id={`${baseId}-chat-${id}`}
            messages={sample.messages}
            indented={true}
            scrollRef={scrollRef}
            toolCallStyle="complete"
          />
        </TabPanel>
        {scorerNames.length === 1 ? (
          <TabPanel
            key={kSampleScoringTabId}
            id={kSampleScoringTabId}
            className="sample-tab"
            title="Scoring"
            onSelected={onSelectedTab}
            selected={selectedTab === kSampleScoringTabId}
          >
            <SampleScoreView
              sample={sample}
              sampleDescriptor={sampleDescriptor}
              scorer={scorerNames[0]}
            />
          </TabPanel>
        ) : (
          <>
            {Object.keys(sample.scores || {}).map((scorer) => {
              const tabId = `score-${scorer}`;
              return (
                <TabPanel
                  key={tabId}
                  id={tabId}
                  className="sample-tab"
                  title={scorer}
                  onSelected={onSelectedTab}
                  selected={selectedTab === tabId}
                >
                  <SampleScoreView
                    sample={sample}
                    sampleDescriptor={sampleDescriptor}
                    scorer={scorer}
                  />
                </TabPanel>
              );
            })}
          </>
        )}
        {sampleMetadatas.length > 0 ? (
          <TabPanel
            id={kSampleMetdataTabId}
            className="sample-tab"
            title="Metadata"
            onSelected={onSelectedTab}
            selected={selectedTab === kSampleMetdataTabId}
          >
            <div className={clsx(styles.metadataPanel)}>{sampleMetadatas}</div>
          </TabPanel>
        ) : null}
        {sample.error ? (
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
        {sample.messages.length < 100 ? (
          <TabPanel
            id={kSampleJsonTabId}
            className={"sample-tab"}
            title="JSON"
            onSelected={onSelectedTab}
            selected={selectedTab === kSampleJsonTabId}
          >
            <div className={clsx(styles.padded, styles.fullWidth)}>
              <JSONPanel data={sample} simple={true} />
            </div>
          </TabPanel>
        ) : null}
      </TabSet>
    </Fragment>
  );
};

const metadataViewsForSample = (id: string, sample: EvalSample) => {
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
