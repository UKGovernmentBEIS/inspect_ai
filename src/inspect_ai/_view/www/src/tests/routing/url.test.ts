/**
 * Tests for URL route parsing logic.
 *
 * These tests verify the regex-based URL parsing that extracts route parameters
 * from splat paths. The parsing logic is extracted here as pure functions to
 * avoid React Router dependencies in tests.
 */

// Constants copied from src/constants.ts to avoid import chain issues
const kSampleTabIds = [
  "messages",
  "transcript",
  "scoring",
  "metadata",
  "error",
  "retry-errors",
  "json",
];

const kWorkspaceTabs = ["samples", "json", "info", "models", "task", "error"];

/**
 * Decodes a URL parameter that may be URL-encoded.
 * Safely handles already decoded strings.
 */
const decodeUrlParam = (param: string | undefined): string | undefined => {
  if (!param) return param;
  try {
    return decodeURIComponent(param);
  } catch {
    return param;
  }
};

/**
 * Pure function that parses log route parameters from a splat path.
 * This is extracted from useLogRouteParams for testability.
 */
function parseLogRouteParams(splatPath: string) {
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

  // Check for full sample route pattern in splat path
  // Pattern: logPath/samples/sample/sampleId/epoch/sampleTabId
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
  // Pattern: /logs/*/samples/sampleId/epoch or /logs/*/samples/sampleTabId
  const sampleUrlMatch = splatPath.match(
    /^(.+?)\/samples(?:\/([^/]+)(?:\/([^/]+))?)?$/,
  );
  if (sampleUrlMatch) {
    const [, logPath, firstSegment, secondSegment] = sampleUrlMatch;

    if (firstSegment) {
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
    return {
      logPath: decodeUrlParam(splatPath),
      tabId: undefined,
      sampleTabId: undefined,
      sampleId: undefined,
      epoch: undefined,
    };
  }
}

/**
 * Pure function that parses samples route parameters from a splat path.
 * This is extracted from useSamplesRouteParams for testability.
 */
function parseSamplesRouteParams(splatPath: string) {
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

  return {
    samplesPath: splatPath ? decodeUrlParam(splatPath) : undefined,
    sampleId: undefined,
    epoch: undefined,
    tabId: undefined,
  };
}

describe("parseLogRouteParams", () => {
  describe("sample UUID routes", () => {
    test("parses /logs/path/to/file.eval/samples/sample_uuid/uuid123", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample_uuid/uuid123",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
        sampleUuid: "uuid123",
      });
    });

    test("parses sample UUID with tab ID", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample_uuid/uuid123/transcript",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: "transcript",
        sampleId: undefined,
        epoch: undefined,
        sampleUuid: "uuid123",
      });
    });

    test("handles trailing slash in sample UUID route", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample_uuid/uuid123/",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
        sampleUuid: "uuid123",
      });
    });
  });

  describe("full sample routes with /samples/sample/ pattern", () => {
    test("parses /logs/path/samples/sample/sampleId/epoch", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample/123/1",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: "123",
        epoch: "1",
      });
    });

    test("parses sample route with tab ID", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample/123/1/transcript",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: "transcript",
        sampleId: "123",
        epoch: "1",
      });
    });

    test("handles string sample IDs", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample/my-sample-id/2/messages",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: "messages",
        sampleId: "my-sample-id",
        epoch: "2",
      });
    });

    test("handles trailing slash", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample/123/1/",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: "123",
        epoch: "1",
      });
    });
  });

  describe("samples listing routes", () => {
    test("parses /logs/path/samples (samples listing)", () => {
      const result = parseLogRouteParams("path/to/file.eval/samples");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: "samples",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("parses /logs/path/samples/transcript (samples with tab)", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/transcript",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: "samples",
        sampleTabId: "transcript",
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("parses /logs/path/samples/messages (samples with messages tab)", () => {
      const result = parseLogRouteParams("path/to/file.eval/samples/messages");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: "samples",
        sampleTabId: "messages",
        sampleId: undefined,
        epoch: undefined,
      });
    });
  });

  describe("single sample mode (sampleId/epoch without /sample/ prefix)", () => {
    test("parses /logs/path/samples/sampleId/epoch", () => {
      const result = parseLogRouteParams("path/to/file.eval/samples/456/3");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: "456",
        epoch: "3",
      });
    });
  });

  describe("regular log routes (no samples)", () => {
    test("parses /logs/path/to/file.eval", () => {
      const result = parseLogRouteParams("path/to/file.eval");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("parses /logs/path/to/file.eval/info (with tab)", () => {
      const result = parseLogRouteParams("path/to/file.eval/info");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: "info",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("parses /logs/path/to/file.eval/json (with json tab)", () => {
      const result = parseLogRouteParams("path/to/file.eval/json");
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: "json",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("handles empty path", () => {
      const result = parseLogRouteParams("");
      expect(result).toEqual({
        logPath: undefined,
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });
  });

  describe("URL encoding handling", () => {
    test("decodes URL-encoded path segments", () => {
      const result = parseLogRouteParams(
        "path/to/file%20with%20spaces.eval/samples",
      );
      expect(result).toEqual({
        logPath: "path/to/file with spaces.eval",
        tabId: "samples",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("decodes URL-encoded sample IDs", () => {
      const result = parseLogRouteParams(
        "path/to/file.eval/samples/sample/sample%2Fid/1",
      );
      expect(result).toEqual({
        logPath: "path/to/file.eval",
        tabId: undefined,
        sampleTabId: undefined,
        sampleId: "sample/id",
        epoch: "1",
      });
    });
  });

  describe("ambiguous route patterns (regression tests)", () => {
    test("sample_uuid pattern takes precedence over sampleId pattern", () => {
      // This tests that /samples/sample_uuid/X is recognized as UUID, not as sampleId="sample_uuid"
      const result = parseLogRouteParams(
        "path/file.eval/samples/sample_uuid/abc123",
      );
      expect(result.sampleUuid).toBe("abc123");
      expect(result.sampleId).toBeUndefined();
    });

    test("/samples/sample/ pattern takes precedence over simple sampleId", () => {
      // /samples/sample/X/Y should be recognized as full sample route
      const result = parseLogRouteParams("path/file.eval/samples/sample/myid/5");
      expect(result.sampleId).toBe("myid");
      expect(result.epoch).toBe("5");
    });

    test("numeric-looking string is treated as sampleId, not epoch", () => {
      // When we have /samples/123/456, first is sampleId, second is epoch
      const result = parseLogRouteParams("path/file.eval/samples/123/456");
      expect(result.sampleId).toBe("123");
      expect(result.epoch).toBe("456");
    });

    test("known tab IDs are recognized in samples context", () => {
      // /samples/transcript should be recognized as sampleTabId
      const result = parseLogRouteParams("path/file.eval/samples/transcript");
      expect(result.sampleTabId).toBe("transcript");
      expect(result.sampleId).toBeUndefined();
    });

    test("unknown segment after /samples/ is treated as sampleId", () => {
      // /samples/unknownvalue should be treated as sampleId
      const result = parseLogRouteParams("path/file.eval/samples/unknownvalue");
      expect(result.sampleId).toBe("unknownvalue");
      expect(result.sampleTabId).toBeUndefined();
    });
  });

  describe("complex file paths", () => {
    test("handles deeply nested paths", () => {
      const result = parseLogRouteParams(
        "very/deeply/nested/path/to/file.eval/samples",
      );
      expect(result).toEqual({
        logPath: "very/deeply/nested/path/to/file.eval",
        tabId: "samples",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("handles paths with dots in directory names", () => {
      const result = parseLogRouteParams(
        "path/with.dots/in.dirs/file.eval/info",
      );
      expect(result).toEqual({
        logPath: "path/with.dots/in.dirs/file.eval",
        tabId: "info",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("handles paths with file: prefix in samples route", () => {
      // Note: file: prefix is passed through as-is in /samples pattern
      const result = parseLogRouteParams(
        "file:/Users/test/path/file.eval/samples",
      );
      expect(result).toEqual({
        logPath: "file:/Users/test/path/file.eval",
        tabId: "samples",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });

    test("handles paths with file: prefix normalized for workspace tabs", () => {
      // file: prefix gets normalized with /// when reaching workspace tab logic
      const result = parseLogRouteParams("file:/Users/test/path/file.eval/info");
      expect(result).toEqual({
        logPath: "file:///Users/test/path/file.eval",
        tabId: "info",
        sampleTabId: undefined,
        sampleId: undefined,
        epoch: undefined,
      });
    });
  });
});

describe("parseSamplesRouteParams", () => {
  test("parses /samples/path/to/file.eval/sample/id/epoch", () => {
    const result = parseSamplesRouteParams(
      "path/to/file.eval/sample/my-sample/1",
    );
    expect(result).toEqual({
      samplesPath: "path/to/file.eval",
      sampleId: "my-sample",
      epoch: "1",
      tabId: undefined,
    });
  });

  test("parses sample route with tab ID", () => {
    const result = parseSamplesRouteParams(
      "path/to/file.eval/sample/123/2/transcript",
    );
    expect(result).toEqual({
      samplesPath: "path/to/file.eval",
      sampleId: "123",
      epoch: "2",
      tabId: "transcript",
    });
  });

  test("parses folder-only path", () => {
    const result = parseSamplesRouteParams("path/to/folder");
    expect(result).toEqual({
      samplesPath: "path/to/folder",
      sampleId: undefined,
      epoch: undefined,
      tabId: undefined,
    });
  });

  test("handles empty path", () => {
    const result = parseSamplesRouteParams("");
    expect(result).toEqual({
      samplesPath: undefined,
      sampleId: undefined,
      epoch: undefined,
      tabId: undefined,
    });
  });

  test("handles trailing slash", () => {
    const result = parseSamplesRouteParams("path/to/file.eval/sample/123/1/");
    expect(result).toEqual({
      samplesPath: "path/to/file.eval",
      sampleId: "123",
      epoch: "1",
      tabId: undefined,
    });
  });
});

describe("decodeUrlParam", () => {
  test("decodes URL-encoded strings", () => {
    expect(decodeUrlParam("hello%20world")).toBe("hello world");
    expect(decodeUrlParam("path%2Fto%2Ffile")).toBe("path/to/file");
  });

  test("returns undefined for undefined input", () => {
    expect(decodeUrlParam(undefined)).toBeUndefined();
  });

  test("returns original string if not encoded", () => {
    expect(decodeUrlParam("hello")).toBe("hello");
  });

  test("handles invalid encoding gracefully", () => {
    // Invalid percent encoding should return original
    expect(decodeUrlParam("%ZZ")).toBe("%ZZ");
  });
});
