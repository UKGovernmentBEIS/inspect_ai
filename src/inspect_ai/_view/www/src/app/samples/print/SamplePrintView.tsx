import { FC, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { JSONPanel } from "../../../components/JsonPanel";
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
import { estimateSize } from "../../../utils/json";
import { useLogRouteParams } from "../../routing/url";
import { printHeadingHtml } from "../../utils/print";
import { metadataViewsForSample } from "../SampleDisplay";
import { ChatView } from "../chat/ChatView";
import { SampleScoresView } from "../scores/SampleScoresView";
import { PrintTranscript } from "./PrintTranscript";
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
      window.print();
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

  const sampleEvents = sample.events || [];
  const sampleMessages = sample.messages || [];
  const headingHtml = printHeadingHtml(evalSpec);
  const sampleMetadatas = metadataViewsForSample("print", contentRef, sample);

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
        <PrintTranscript events={sampleEvents} />
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

      {view === kSampleMetdataTabId &&
        (sampleMetadatas.length > 0 ? (
          <div>{sampleMetadatas}</div>
        ) : (
          <NoContentsPanel text="No sample metadata available" />
        ))}

      {view === kSampleJsonTabId &&
        (estimateSize(sample.events) > 25 * 1024 * 1024 ? (
          <NoContentsPanel text="JSON too large to display" />
        ) : (
          <JSONPanel data={sample} simple={true} />
        ))}
    </div>
  );
};
