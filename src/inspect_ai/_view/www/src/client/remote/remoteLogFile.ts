import { EvalLog, EvalPlan, EvalSample, EvalSpec } from "../../@types/log";
import { asyncJsonParse } from "../../utils/json-worker";
import { AsyncQueue } from "../../utils/queue";
import {
  EvalHeader,
  EvalSummary,
  LogViewAPI,
  SampleSummary,
} from "../api/types";
import { FileSizeLimitError, openRemoteZipFile } from "./remoteZipFile";

// don't try to load samples greater than 50mb
const MAX_BYTES = 50 * 1024 * 1024;

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
  readHeader: () => Promise<EvalHeader>;
  readLogSummary: () => Promise<EvalSummary>;
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
  const remoteZipFile = await openRemoteZipFile(
    url,
    api.eval_log_size,
    api.eval_log_bytes,
  );

  /**
   * Reads and parses a JSON file from the zip.
   */
  const readJSONFile = async (
    file: string,
    maxBytes?: number,
  ): Promise<Object> => {
    try {
      const data = await remoteZipFile.readFile(file, maxBytes);
      const textDecoder = new TextDecoder("utf-8");
      const jsonString = textDecoder.decode(data);
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
    if (remoteZipFile.centralDirectory.has(sampleFile)) {
      return (await readJSONFile(sampleFile, MAX_BYTES)) as EvalSample;
    } else {
      throw new SampleNotFoundError(
        `Unable to read sample file ${sampleFile} - it is not present in the manifest.`,
      );
    }
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
    readHeader,
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
