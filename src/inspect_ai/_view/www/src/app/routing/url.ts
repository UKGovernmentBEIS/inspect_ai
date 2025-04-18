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

export const logUrl = (log_file: string, log_dir?: string, tabId?: string) => {
  const pathSegment = directoryRelativeUrl(log_file, log_dir);
  return logUrlRaw(pathSegment, tabId);
};

export const logUrlRaw = (log_segment: string, tabId?: string) => {
  if (tabId) {
    return `/logs/${encodeURIComponent(log_segment)}/${tabId}`;
  } else {
    return `/logs/${encodeURIComponent(log_segment)}`;
  }
};
