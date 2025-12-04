import { useMemo } from "react";
import { useLocation, useParams } from "react-router-dom";
import {
  kSampleMessagesTabId,
  kSampleTabIds,
  kSampleTranscriptTabId,
  kWorkspaceTabs,
} from "../../constants";
import { useStore } from "../../state/store";
import { directoryRelativeUrl, encodePathParts } from "../../utils/uri";

/**
 * Decodes a URL parameter that may be URL-encoded.
 * Safely handles already decoded strings.
 */
export const decodeUrlParam = (
  param: string | undefined,
): string | undefined => {
  if (!param) return param;
  try {
    return decodeURIComponent(param);
  } catch {
    // If decoding fails, return the original string
    return param;
  }
};

/**
 * Hook that provides URL parameters with automatic decoding.
 * Use this instead of useParams when you need the actual unencoded values.
 */
export const useDecodedParams = <
  T extends Record<string, string | undefined>,
>() => {
  const params = useParams<T>();

  const decodedParams = useMemo(() => {
    const decoded = {} as T;
    Object.entries(params).forEach(([key, value]) => {
      (decoded as any)[key] = decodeUrlParam(value as string);
    });
    return decoded;
  }, [params]);

  return decodedParams;
};

export interface LogOrSampleRouteParams {
  logPath?: string;
  id?: string;
  epoch?: string;
  sampleTabId?: string;
  tabId?: string;
  uuid: string | undefined;
}

export const useLogOrSampleRouteParams = (): LogOrSampleRouteParams => {
  const location = useLocation();

  const logParams = useLogRouteParams();
  const sampleParams = useSamplesRouteParams();

  if (location.pathname.startsWith("/samples/")) {
    return {
      logPath: sampleParams.samplesPath,
      id: sampleParams.sampleId,
      epoch: sampleParams.epoch,
      sampleTabId: sampleParams.tabId,
      tabId: undefined,
      uuid: undefined,
    };
  } else {
    return {
      logPath: logParams.logPath,
      id: logParams.sampleId,
      epoch: logParams.epoch,
      tabId: logParams.tabId,
      sampleTabId: logParams.sampleTabId,
      uuid: logParams.sampleUuid,
    };
  }
};

/**
 * Hook that parses log route parameters from the splat route.
 * Handles nested paths properly by parsing the full path after /logs/
 */
export const useLogRouteParams = () => {
  const params = useParams<{
    "*": string;
    sampleUuid?: string;
    sampleId?: string;
    epoch?: string;
    sampleTabId?: string;
  }>();

  return useMemo(() => {
    const splatPath = params["*"] || "";

    // Check for sample UUID route pattern
    const sampleUuidMatch = splatPath.match(
      /^(.+?)\/samples\/sample_uuid\/([^/]+)(?:\/(.+?))?\/?\s*$/,
    );
    if (sampleUuidMatch) {
      const [, logPath, sampleUuid, sampleTabId] = sampleUuidMatch;
      return {
        logPath: decodeUrlParam(logPath),
        tabId: undefined,
        sampleTabId: decodeUrlParam(sampleTabId),
        sampleId: undefined,
        epoch: undefined,
        sampleUuid: decodeUrlParam(sampleUuid),
      };
    }

    // Check for full sample route pattern in splat path (when route params aren't populated)
    // Pattern: logPath/samples/sample/sampleId/epoch/sampleTabId (with optional trailing slash)
    const fullSampleUrlMatch = splatPath.match(
      /^(.+?)\/samples\/sample\/([^/]+)(?:\/([^/]+)(?:\/(.+?))?)?\/?\s*$/,
    );
    if (fullSampleUrlMatch) {
      const [, logPath, sampleId, epoch, sampleTabId] = fullSampleUrlMatch;
      return {
        logPath: decodeUrlParam(logPath),
        tabId: undefined,
        sampleTabId: decodeUrlParam(sampleTabId),
        sampleId: decodeUrlParam(sampleId),
        epoch: epoch ? decodeUrlParam(epoch) : undefined,
      };
    }

    // Check for sample URLs that might not match the formal route pattern
    // (this is the single sample case, where is there is now sampleid/epoch, just sampletabid)
    // Pattern: /logs/*/samples/sampleId/epoch or /logs/*/samples/sampleId or /logs/*/samples/sampleTabId
    const sampleUrlMatch = splatPath.match(
      /^(.+?)\/samples(?:\/([^/]+)(?:\/([^/]+))?)?$/,
    );
    if (sampleUrlMatch) {
      const [, logPath, firstSegment, secondSegment] = sampleUrlMatch;

      if (firstSegment) {
        // Define known sample tab IDs
        const validSampleTabIds = new Set(kSampleTabIds);

        if (validSampleTabIds.has(firstSegment) && !secondSegment) {
          // This is /logs/*/samples/sampleTabId
          return {
            logPath: decodeUrlParam(logPath),
            tabId: "samples",
            sampleTabId: decodeUrlParam(firstSegment),
            sampleId: undefined,
            epoch: undefined,
          };
        } else {
          // This is a sample URL with sampleId (and possibly epoch)
          return {
            logPath: decodeUrlParam(logPath),
            tabId: undefined,
            sampleTabId: undefined,
            sampleId: decodeUrlParam(firstSegment),
            epoch: secondSegment ? decodeUrlParam(secondSegment) : undefined,
          };
        }
      } else {
        // This is just /logs/*/samples (samples listing)
        return {
          logPath: decodeUrlParam(logPath),
          tabId: "samples",
          sampleTabId: undefined,
          sampleId: undefined,
          epoch: undefined,
        };
      }
    }

    // Regular log route pattern: /logs/path/to/file.eval/tabId?
    // Split the path and check if the last segment might be a tabId
    const pathSegments = splatPath.split("/").filter(Boolean);

    if (pathSegments.length === 0) {
      return {
        logPath: undefined,
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      };
    }

    // Define valid tab IDs for log view
    const validTabIds = new Set(kWorkspaceTabs);

    // Look for the first valid tab ID from right to left
    let tabIdIndex = -1;
    let foundTabId: string | undefined = undefined;

    for (let i = pathSegments.length - 1; i >= 0; i--) {
      const segment = pathSegments[i];
      const decodedSegment = decodeUrlParam(segment) || segment;

      if (validTabIds.has(decodedSegment)) {
        tabIdIndex = i;
        foundTabId = decodedSegment;
        break;
      }
    }

    if (foundTabId && tabIdIndex > 0) {
      // Found a valid tab ID, split the path there
      const pathSlice = pathSegments.slice(0, tabIdIndex);
      const firstSegment = pathSlice[0];
      const logPath =
        firstSegment?.endsWith(":") && !firstSegment.includes("://")
          ? firstSegment +
            (firstSegment === "file:" ? "///" : "//") +
            pathSlice.slice(1).join("/")
          : pathSlice.join("/");

      return {
        logPath: decodeUrlParam(logPath),
        tabId: foundTabId,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      };
    } else {
      // No valid tab ID found, the entire path is the logPath
      return {
        logPath: decodeUrlParam(splatPath),
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      };
    }
  }, [params]);
};

/**
 * Hook that parses samples route parameters from the splat route.
 * Handles nested paths properly by parsing the full path after /samples/
 * Also handles sample detail routes: /samples/path/to/file.eval/sample/id/epoch
 */
export const useSamplesRouteParams = () => {
  const params = useParams<{
    "*": string;
  }>();

  return useMemo(() => {
    const splatPath = params["*"] || "";

    const sampleMatch = splatPath.match(
      /^(.+?)\/sample\/([^/]+)\/([^/]+)(?:\/([^/]+))?\/?$/,
    );

    if (sampleMatch) {
      const [, logPath, sampleId, epoch, tabId] = sampleMatch;
      return {
        samplesPath: decodeUrlParam(logPath),
        sampleId: decodeUrlParam(sampleId),
        epoch: decodeUrlParam(epoch),
        tabId: tabId ? decodeUrlParam(tabId) : undefined,
      };
    }

    // Otherwise it's just a folder path
    return {
      samplesPath: splatPath ? decodeUrlParam(splatPath) : undefined,
      sampleId: undefined,
      epoch: undefined,
      tabId: undefined,
    };
  }, [params]);
};

export const kLogsRoutUrlPattern = "/logs";
export const kLogRouteUrlPattern = "/logs/*";
export const kSamplesRouteUrlPattern = "/samples";
export const kSampleRouteUrlPattern =
  "/logs/*/samples/sample/:sampleId/:epoch?/:sampleTabId?";
export const kSampleUuidRouteUrlPattern =
  "/logs/*/samples/sample_uuid/:sampleUuid/:sampleTabId?";

export const baseUrl = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  if (sampleId !== undefined && sampleEpoch !== undefined) {
    return logSamplesUrl(logPath, sampleId, sampleEpoch);
  } else {
    return logsUrl(logPath);
  }
};

export type SampleUrlBuilder = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
  sampleTabId?: string,
) => string;

export const useSampleUrlBuilder = () => {
  const location = useLocation();
  return (
    logPath: string,
    sampleId?: string | number,
    sampleEpoch?: string | number,
    sampleTabId?: string,
  ) => {
    if (sampleId && sampleEpoch && location.pathname.startsWith("/samples/")) {
      return samplesSampleUrl(logPath, sampleId, sampleEpoch, sampleTabId);
    } else {
      return logSamplesUrl(logPath, sampleId, sampleEpoch, sampleTabId);
    }
  };
};

export const logSamplesUrl = (
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
  sampleTabId?: string,
) => {
  // Ensure logPath is decoded before encoding for URL construction
  const decodedLogPath = decodeUrlParam(logPath) || logPath;

  if (sampleId !== undefined && sampleEpoch !== undefined) {
    return encodePathParts(
      `/logs/${decodedLogPath}/samples/sample/${sampleId}/${sampleEpoch}/${sampleTabId || ""}`,
    );
  } else {
    return encodePathParts(
      `/logs/${decodedLogPath}/samples/${sampleTabId || ""}`,
    );
  }
};

export const samplesSampleUrl = (
  logPath: string,
  sampleId: string | number,
  epoch: string | number,
  sampleTabId?: string,
) => {
  const decodedLogPath = decodeUrlParam(logPath) || logPath;
  return encodePathParts(
    `/samples/${decodedLogPath}/sample/${sampleId}/${epoch}/${sampleTabId || ""}`,
  );
};

export const sampleEventUrl = (
  builder: SampleUrlBuilder,
  eventId: string,
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const baseUrl = builder(
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
    id: urlSampleId,
    epoch: urlEpoch,
  } = useLogOrSampleRouteParams();
  const builder = useSampleUrlBuilder();

  const log_file = useStore((state) => state.logs.selectedLogFile);
  const log_dir = useStore((state) => state.logs.logDir);

  let targetLogPath = urlLogPath;
  if (!targetLogPath && log_file) {
    targetLogPath = makeLogsPath(log_file, log_dir);
  }

  const messageUrl = useMemo(() => {
    return messageId && targetLogPath
      ? sampleMessageUrl(
          builder,
          messageId,
          targetLogPath,
          sampleId || urlSampleId,
          sampleEpoch || urlEpoch,
        )
      : undefined;
  }, [
    messageId,
    targetLogPath,
    builder,
    sampleId,
    urlSampleId,
    sampleEpoch,
    urlEpoch,
  ]);
  return messageUrl;
};

export const useSampleEventUrl = (
  eventId: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const {
    logPath: urlLogPath,
    id: urlSampleId,
    epoch: urlEpoch,
  } = useLogOrSampleRouteParams();
  const builder = useSampleUrlBuilder();

  const log_file = useStore((state) => state.logs.selectedLogFile);
  const log_dir = useStore((state) => state.logs.logDir);

  let targetLogPath = urlLogPath;
  if (!targetLogPath && log_file) {
    targetLogPath = makeLogsPath(log_file, log_dir);
  }

  const eventUrl = useMemo(() => {
    return targetLogPath
      ? sampleEventUrl(
          builder,
          eventId,
          targetLogPath,
          sampleId || urlSampleId,
          sampleEpoch || urlEpoch,
        )
      : undefined;
  }, [
    targetLogPath,
    builder,
    eventId,
    sampleId,
    urlSampleId,
    sampleEpoch,
    urlEpoch,
  ]);
  return eventUrl;
};

export const sampleMessageUrl = (
  builder: SampleUrlBuilder,
  messageId: string,
  logPath: string,
  sampleId?: string | number,
  sampleEpoch?: string | number,
) => {
  const baseUrl = builder(logPath, sampleId, sampleEpoch, kSampleMessagesTabId);
  return `${baseUrl}?message=${messageId}`;
};

export const samplesUrl = (log_file: string, log_dir?: string) => {
  const path = makeLogsPath(log_file, log_dir);
  const decodedLogSegment = decodeUrlParam(path) || path;
  return encodePathParts(`/samples/${decodedLogSegment}`);
};

export const logsUrl = (log_file: string, log_dir?: string, tabId?: string) => {
  return logsUrlRaw(makeLogsPath(log_file, log_dir), tabId);
};

export const makeLogsPath = (log_file: string, log_dir?: string) => {
  const pathSegment = directoryRelativeUrl(log_file, log_dir);
  return pathSegment;
};

export const logsUrlRaw = (log_segment: string, tabId?: string) => {
  // Ensure log_segment is decoded before encoding for URL construction
  const decodedLogSegment = decodeUrlParam(log_segment) || log_segment;

  if (tabId) {
    return encodePathParts(`/logs/${decodedLogSegment}/${tabId}`);
  } else {
    return encodePathParts(`/logs/${decodedLogSegment}`);
  }
};

export const supportsLinking = () => {
  return (
    location.hostname !== "localhost" &&
    location.hostname !== "127.0.0.1" &&
    location.protocol !== "vscode-webview:"
  );
};

export const toFullUrl = (path: string) => {
  return `${window.location.origin}${window.location.pathname}${window.location.search}#${path}`;
};
