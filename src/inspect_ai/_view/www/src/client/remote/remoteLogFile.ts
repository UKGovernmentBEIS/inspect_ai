import { EvalLog, EvalPlan, EvalSample, EvalSpec } from "../../@types/log";
import { clearLargeEventsArray } from "../../utils/clear-events-preprocessor";
import { asyncJsonParse } from "../../utils/json-worker";
import { AsyncQueue } from "../../utils/queue";
import {
  EvalHeader,
  LogDetails,
  LogPreview,
  LogViewAPI,
  SampleSummary,
} from "../api/types";
import { toLogPreview } from "../utils/type-utils";
import {
  CentralDirectoryEntry,
  FileSizeLimitError,
  openRemoteZipFile,
} from "./remoteZipFile";

const OPEN_RETRY_LIMIT = 5;

// Maximum uncompressed sample size (512MB). Files larger than this will
// fail to allocate memory in the browser, so we reject them early with a
// clear error rather than crashing with "Array buffer allocation failed".
const MAX_SAMPLE_SIZE_BYTES = 2048 * 1024 * 1024;

interface SampleEntry {
  sampleId: string;
  epoch: number;
}

export class SampleNotFoundError extends Error {
  constructor(message?: string) {
    super(message || "Sample not found");
    this.name = "SampleNotFoundError";

    Object.setPrototypeOf(this, SampleNotFoundError.prototype);
  }
}
export interface RemoteLogFile {
  readEvalBasicInfo: () => Promise<LogPreview>;
  readLogSummary: () => Promise<LogDetails>;
  readSample: (sampleId: string, epoch: number) => Promise<EvalSample>;
  readCompleteLog: () => Promise<EvalLog>;
}

interface LogStart {
  version: number;
  eval: EvalSpec;
  plan: EvalPlan;
}

/**
 * Opens a remote log file and provides methods to read its contents.
 */
export const openRemoteLogFile = async (
  api: LogViewAPI,
  url: string,
  concurrency: number,
): Promise<RemoteLogFile> => {
  const queue = new AsyncQueue(concurrency);

  let remoteZipFile:
    | {
        centralDirectory: Map<string, CentralDirectoryEntry>;
        readFile: (file: string, maxBytes?: number) => Promise<Uint8Array>;
      }
    | undefined = undefined;

  let retryCount = 0;
  while (!remoteZipFile && retryCount < OPEN_RETRY_LIMIT) {
    try {
      remoteZipFile = await openRemoteZipFile(
        url,
        api.get_log_size,
        api.get_log_bytes,
      );
    } catch {
      retryCount++;
      console.warn(
        `Failed to open remote log file at ${url}, retrying (${retryCount}/${OPEN_RETRY_LIMIT})...`,
      );
      await new Promise((resolve) =>
        setTimeout(resolve, 100 * (retryCount + retryCount)),
      );
    }
  }

  if (!remoteZipFile) {
    throw new Error(
      `Failed to open remote log file at ${url} after ${OPEN_RETRY_LIMIT} attempts.`,
    );
  }

  interface JSONPreprocessor {
    preprocess: (data: Uint8Array) => Uint8Array;
  }

  /**
   * Reads and parses a JSON file from the zip.
   * Optionally applies a preprocessor to transform bytes before decoding.
   */
  const readJSONFile = async (
    file: string,
    maxBytes?: number,
    preprocessor?: JSONPreprocessor,
  ): Promise<Object> => {
    try {
      let data = await remoteZipFile.readFile(file, maxBytes);

      // Apply preprocessor if provided
      if (preprocessor) {
        data = preprocessor.preprocess(data);
      }

      const textDecoder = new TextDecoder("utf-8");
      const jsonString = textDecoder.decode(data);

      // Check if decoding failed (resulted in empty string)
      if (data.length > 0 && jsonString.length === 0) {
        throw new Error(
          `Failed to decode ${file} (${(data.length / 1024 / 1024).toFixed(0)}MB). ` +
            `The file may be corrupted or contain invalid UTF-8 sequences.`,
        );
      }

      return asyncJsonParse(jsonString);
    } catch (error) {
      if (error instanceof FileSizeLimitError) {
        throw error;
      } else if (error instanceof Error) {
        throw new Error(
          `Failed to read or parse file ${file}: ${error.message}`,
        );
      } else {
        throw new Error(
          `Failed to read or parse file ${file} - an unknown error occurred`,
        );
      }
    }
  };

  /**
   * Lists all samples in the zip file.
   */
  const listSamples = async (): Promise<SampleEntry[]> => {
    return Array.from(remoteZipFile.centralDirectory.keys())
      .filter(
        (filename) =>
          filename.startsWith("samples/") && filename.endsWith(".json"),
      )
      .map((filename) => {
        const [sampleId, epochStr] = filename.split("/")[1].split("_epoch_");
        return {
          sampleId,
          epoch: parseInt(epochStr.split(".")[0], 10),
        };
      });
  };

  /**
   * Reads a specific sample file.
   */
  const readSample = async (
    sampleId: string,
    epoch: number,
  ): Promise<EvalSample> => {
    const sampleFile = `samples/${sampleId}_epoch_${epoch}.json`;

    if (!remoteZipFile.centralDirectory.has(sampleFile)) {
      throw new SampleNotFoundError(
        `Unable to read sample file ${sampleFile} - it is not present in the manifest.`,
      );
    }

    // Check the uncompressed size before attempting to read – this avoids
    // crashing the browser with "Array buffer allocation failed".
    const entry = remoteZipFile.centralDirectory.get(sampleFile)!;
    if (entry.uncompressedSize > MAX_SAMPLE_SIZE_BYTES) {
      throw new FileSizeLimitError(sampleFile, MAX_SAMPLE_SIZE_BYTES);
    }

    // Use a preprocessor to clear large events arrays
    const eventsPreprocessor: JSONPreprocessor = {
      preprocess: clearLargeEventsArray,
    };
    return (await readJSONFile(
      sampleFile,
      undefined,
      eventsPreprocessor,
    )) as EvalSample;
  };

  /**
   * Reads the results.json file.
   */
  const readHeader = async (): Promise<EvalHeader> => {
    if (remoteZipFile.centralDirectory.has("header.json")) {
      return (await readJSONFile("header.json")) as EvalHeader;
    } else {
      const evalSpec = (await readJSONFile("_journal/start.json")) as LogStart;
      return {
        status: "started",
        eval: evalSpec.eval,
        plan: evalSpec.plan,
      };
    }
  };

  const readEvalBasicInfo = async (): Promise<LogPreview> => {
    const header = await readHeader();
    return toLogPreview(header);
  };

  /**
   * Reads individual summary files when summaries.json is not available.
   */
  const readFallbackSummaries = async (): Promise<SampleSummary[]> => {
    const summaryFiles = Array.from(
      remoteZipFile.centralDirectory.keys(),
    ).filter(
      (filename) =>
        filename.startsWith("_journal/summaries/") &&
        filename.endsWith(".json"),
    );

    const summaries: SampleSummary[] = [];
    const errors: unknown[] = [];

    await Promise.all(
      summaryFiles.map((filename) =>
        queue.enqueue(async () => {
          try {
            const partialSummary = (await readJSONFile(
              filename,
            )) as SampleSummary[];
            summaries.push(...partialSummary);
          } catch (error) {
            errors.push(error);
          }
        }),
      ),
    );

    if (errors.length > 0) {
      console.error(
        `Encountered ${errors.length} errors while reading summary files:`,
        errors,
      );
    }

    return summaries;
  };

  /**
   * Reads all summaries, falling back to individual files if necessary.
   */
  const readSampleSummaries = async (): Promise<SampleSummary[]> => {
    if (remoteZipFile.centralDirectory.has("summaries.json")) {
      return (await readJSONFile("summaries.json")) as SampleSummary[];
    } else {
      return readFallbackSummaries();
    }
  };

  return {
    readEvalBasicInfo,
    readLogSummary: async () => {
      const [header, sampleSummaries] = await Promise.all([
        readHeader(),
        readSampleSummaries(),
      ]);
      const result = {
        status: header.status,
        eval: header.eval,
        plan: header.plan,
        results: header.results,
        stats: header.stats,
        error: header.error,
        sampleSummaries,
      };
      return result;
    },
    readSample,
    /**
     * Reads the complete log file.
     */
    readCompleteLog: async (): Promise<EvalLog> => {
      const [evalLog, samples] = await Promise.all([
        readHeader(),
        listSamples().then((sampleIds) =>
          Promise.all(
            sampleIds.map(({ sampleId, epoch }) =>
              readSample(sampleId, epoch).then(
                (sample) => sample as EvalSample,
              ),
            ),
          ),
        ),
      ]);

      return {
        status: evalLog.status,
        eval: evalLog.eval,
        plan: evalLog.plan,
        results: evalLog.results,
        stats: evalLog.stats,
        error: evalLog.error,
        samples,
      };
    },
  };
};
