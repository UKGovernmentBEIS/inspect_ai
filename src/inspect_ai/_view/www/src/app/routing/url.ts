export const sampleUrl = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
  logTabId?: string,
  sampleTabId?: string,
) => {
  if (sampleId !== undefined && sampleEpoch !== undefined) {
    return `/logs/${encodeURIComponent(logPath)}/${logTabId || "samples"}/sample/${encodeURIComponent(sampleId)}/${sampleEpoch}/${sampleTabId || ""}`;
  } else {
    return `/logs/${encodeURIComponent(logPath)}/${logTabId || "samples"}/${sampleTabId || ""}`;
  }
};
