import React, { FC, useEffect, useMemo, useRef } from "react";
import { VirtuosoHandle } from "react-virtuoso";
import { useSearchParams } from "react-router-dom";
import { EvalSample } from "../../../@types/log";
import { NoContentsPanel } from "../../../components/NoContentsPanel";
import {
  kSampleJsonTabId,
  kSampleMessagesTabId,
  kSampleMetdataTabId,
  kSampleScoringTabId,
  kSampleTranscriptTabId,
} from "../../../constants";
import { useSampleData } from "../../../state/hooks";
import { useStore } from "../../../state/store";
import { useLoadSample } from "../../../state/useLoadSample";
import { usePollSample } from "../../../state/usePollSample";
import { formatDateTime, formatTime } from "../../../utils/format";
import { useLogRouteParams } from "../../routing/url";
import { printHeadingHtml } from "../../utils/print";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { Card, CardBody, CardHeader } from "../../../components/Card";
import { ModelTokenTable } from "../../usage/ModelTokenTable";
import { ChatView } from "../chat/ChatView";
import { SampleScoresView } from "../scores/SampleScoresView";
import { SampleJSONView } from "../SampleJSONView";
import { TranscriptVirtualListComponent } from "../transcript/TranscriptVirtualListComponent";
import { useEventNodes } from "../transcript/transform/hooks";
import { flatTree } from "../transcript/transform/flatten";
import styles from "./SamplePrintView.module.css";

/**
 * Print route page component.
 * Renders sample content without virtualization for printing.
 * URL pattern: /logs/<logPath>/samples/sample/<id>/<epoch>/print?view=<tab>
 */
export const SamplePrintView: FC = () => {
  const { logPath, sampleId, epoch } = useLogRouteParams();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? kSampleTranscriptTabId;

  // Load sample data (depends on selectedLogFile and selectedSampleHandle being set)
  useLoadSample();
  usePollSample();

  // Initialize log and sample loading (same pattern as LogSampleDetailView)
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const selectSample = useStore((state) => state.logActions.selectSample);

  useEffect(() => {
    const loadLogAndSample = async () => {
      if (logPath && sampleId && epoch) {
        await initLogDir();
        setSelectedLogFile(logPath);
        void syncLogs();

        const targetEpoch = parseInt(epoch, 10);
        if (!isNaN(targetEpoch)) {
          selectSample(sampleId, targetEpoch, logPath);
        }
      }
    };
    void loadLogAndSample();
  }, [
    logPath,
    sampleId,
    epoch,
    initLogDir,
    setSelectedLogFile,
    syncLogs,
    selectSample,
  ]);

  // Get sample data
  const sampleData = useSampleData();
  const sample = useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);

  const evalSpec = useStore((state) => state.log.selectedLogDetails?.eval);

  // Transcript: process events through the same pipeline, all expanded
  const sampleEvents = sample?.events || [];
  const { eventNodes } = useEventNodes(sampleEvents, false);
  const flattenedNodes = useMemo(() => {
    return flatTree(eventNodes, null);
  }, [eventNodes]);
  const listHandle = useRef<VirtuosoHandle | null>(null);

  // Auto-print once content has finished rendering.
  // Uses a MutationObserver to detect when the DOM stops changing,
  // then triggers print after a settling period.
  const contentRef = useRef<HTMLDivElement>(null);
  const hasPrinted = useRef(false);
  useEffect(() => {
    if (!sample || hasPrinted.current || !contentRef.current) return;

    let timer: ReturnType<typeof setTimeout>;
    const triggerPrint = () => {
      if (hasPrinted.current) return;
      hasPrinted.current = true;
      observer.disconnect();
      window.focus();
      window.print();
      window.close();
    };

    const observer = new MutationObserver(() => {
      // Reset the timer every time the DOM changes
      clearTimeout(timer);
      timer = setTimeout(triggerPrint, 500);
    });

    observer.observe(contentRef.current, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    // Start the initial timer (in case nothing mutates, e.g. empty content)
    timer = setTimeout(triggerPrint, 1000);

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [sample]);

  if (!sample) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Loading sample data...</div>
      </div>
    );
  }

  const sampleMessages = sample.messages || [];
  const headingHtml = printHeadingHtml(evalSpec);

  return (
    <div className={styles.container} ref={contentRef}>
      <div className={styles.header}>
        <div dangerouslySetInnerHTML={{ __html: headingHtml }} />
        {sampleId && epoch && (
          <div className={styles.sampleInfo}>
            Sample {sampleId} (Epoch {epoch})
          </div>
        )}
      </div>

      {view === kSampleTranscriptTabId && (
        <TranscriptVirtualListComponent
          id="print-transcript"
          listHandle={listHandle}
          eventNodes={flattenedNodes}
          disableVirtualization={true}
        />
      )}

      {view === kSampleMessagesTabId && (
        <ChatView
          id="print-messages"
          messages={sampleMessages}
          indented={true}
        />
      )}

      {view === kSampleScoringTabId && (
        <SampleScoresView sample={sample} scrollRef={contentRef} />
      )}

      {view === kSampleMetdataTabId && <PrintMetadata sample={sample} />}

      {view === kSampleJsonTabId && <SampleJSONView sample={sample} />}
    </div>
  );
};

/**
 * Renders sample metadata using MetadataGrid (non-virtualized)
 * instead of RecordTree for print-friendly output.
 */
const PrintMetadata: FC<{ sample: EvalSample }> = ({ sample }) => {
  const sampleMetadatas: React.JSX.Element[] = [];

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
      <Card key="print-invalidation">
        <CardHeader label="Invalidation" />
        <CardBody>
          <MetaDataGrid entries={invalidationRecord} />
        </CardBody>
      </Card>,
    );
  }

  if (sample.model_usage && Object.keys(sample.model_usage).length > 0) {
    sampleMetadatas.push(
      <Card key="print-usage">
        <CardHeader label="Usage" />
        <CardBody>
          <ModelTokenTable model_usage={sample.model_usage} />
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
      <Card key="print-time">
        <CardHeader label="Time" />
        <CardBody>
          <MetaDataGrid
            entries={{
              Working: formatTime(sample.working_time),
              Total: formatTime(sample.total_time),
            }}
          />
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.metadata).length > 0) {
    sampleMetadatas.push(
      <Card key="print-metadata">
        <CardHeader label="Metadata" />
        <CardBody>
          <MetaDataGrid entries={sample?.metadata as Record<string, unknown>} />
        </CardBody>
      </Card>,
    );
  }

  if (Object.keys(sample?.store).length > 0) {
    sampleMetadatas.push(
      <Card key="print-store">
        <CardHeader label="Store" />
        <CardBody>
          <MetaDataGrid entries={sample?.store as Record<string, unknown>} />
        </CardBody>
      </Card>,
    );
  }

  if (sampleMetadatas.length === 0) {
    return <NoContentsPanel text="No sample metadata available" />;
  }

  return <div>{sampleMetadatas}</div>;
};
