import { useMemo } from "react";
import { useParams } from "react-router-dom";
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

export const kLogsRoutUrlPattern = "/logs";
export const kLogRouteUrlPattern = "/logs/*";
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
  } = useLogRouteParams();

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
  } = useLogRouteParams();

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
  return `${window.location.origin}${window.location.pathname}#${path}`;
};
