import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { kSampleMessagesTabId, kSampleTranscriptTabId } from "../../constants";
import { useStore } from "../../state/store";
import { directoryRelativeUrl } from "../../utils/uri";

export const kLogRouteUrlPattern = "/logs/:logPath/:tabId?/:sampleTabId?";
export const kSampleRouteUrlPattern =
  "/logs/:logPath/samples/sample/:sampleId/:epoch?/:sampleTabId?";

export const baseUrl = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  if (sampleId !== undefined && sampleEpoch !== undefined) {
    return sampleUrl(logPath, sampleId, sampleEpoch);
  } else {
    return logUrl(logPath);
  }
};

export const sampleUrl = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
  sampleTabId?: string,
) => {
  if (sampleId !== undefined && sampleEpoch !== undefined) {
    return `/logs/${encodeURIComponent(logPath)}/samples/sample/${encodeURIComponent(sampleId)}/${sampleEpoch}/${sampleTabId || ""}`;
  } else {
    return `/logs/${encodeURIComponent(logPath)}/samples/${sampleTabId || ""}`;
  }
};

export const sampleEventUrl = (
  eventId: string,
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const baseUrl = sampleUrl(
    logPath,
    sampleId,
    sampleEpoch,
    kSampleTranscriptTabId,
  );

  return `${baseUrl}?event=${eventId}`;
};

export const useSampleMessageUrl = (
  messageId: string | null,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const {
    logPath: urlLogPath,
    sampleId: urlSampleId,
    epoch: urlEpoch,
  } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const log_file = useStore((state) => state.logs.selectedLogFile);
  const log_dir = useStore((state) => state.logs.logs.log_dir);

  let targetLogPath = urlLogPath;
  if (!targetLogPath && log_file) {
    targetLogPath = makeLogPath(log_file, log_dir);
  }

  const eventUrl = useMemo(() => {
    return messageId && targetLogPath
      ? sampleMessageUrl(
          messageId,
          targetLogPath,
          sampleId || urlSampleId,
          sampleEpoch || urlEpoch,
        )
      : undefined;
  }, [targetLogPath, messageId, sampleId, urlSampleId, sampleEpoch, urlEpoch]);
  return eventUrl;
};

export const useSampleEventUrl = (
  eventId: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const {
    logPath: urlLogPath,
    sampleId: urlSampleId,
    epoch: urlEpoch,
  } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const log_file = useStore((state) => state.logs.selectedLogFile);
  const log_dir = useStore((state) => state.logs.logs.log_dir);

  let targetLogPath = urlLogPath;
  if (!targetLogPath && log_file) {
    targetLogPath = makeLogPath(log_file, log_dir);
  }

  const eventUrl = useMemo(() => {
    return targetLogPath
      ? sampleEventUrl(
          eventId,
          targetLogPath,
          sampleId || urlSampleId,
          sampleEpoch || urlEpoch,
        )
      : undefined;
  }, [targetLogPath, eventId, sampleId, urlSampleId, sampleEpoch, urlEpoch]);
  return eventUrl;
};

export const sampleMessageUrl = (
  messageId: string,
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const baseUrl = sampleUrl(
    logPath,
    sampleId,
    sampleEpoch,
    kSampleMessagesTabId,
  );

  return `${baseUrl}?message=${messageId}`;
};

export const logUrl = (log_file: string, log_dir?: string, tabId?: string) => {
  return logUrlRaw(makeLogPath(log_file, log_dir), tabId);
};

export const makeLogPath = (log_file: string, log_dir?: string) => {
  const pathSegment = directoryRelativeUrl(log_file, log_dir);
  return pathSegment;
};

export const logUrlRaw = (log_segment: string, tabId?: string) => {
  if (tabId) {
    return `/logs/${encodeURIComponent(log_segment)}/${tabId}`;
  } else {
    return `/logs/${encodeURIComponent(log_segment)}`;
  }
};

export const supportsLinking = () => {
  return (
    //location.hostname !== "localhost" &&
    location.hostname !== "127.0.0.1" && location.protocol !== "vscode-webview:"
  );
};

export const toFullUrl = (path: string) => {
  return `${window.location.origin}${window.location.pathname}#${path}`;
};
