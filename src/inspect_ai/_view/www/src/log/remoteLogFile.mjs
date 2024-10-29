//@ts-check
import { asyncJsonParse } from "../utils/Json.mjs";
import { AsyncQueue } from "../utils/queue.mjs";
import { openRemoteZipFile } from "../utils/remoteZipFile.mjs";

/**
 * @typedef {Object} SampleEntry
 * @property {string} sampleId
 * @property {number} epoch
 */

/**
 * @typedef {Object} RemoteLogFile
 * @property {() => Promise<Object>} readHeader - Reads the header of the log file.
 * @property {() => Promise<Object>} readLogSummary - Reads the log summary including header and sample summaries.
 * @property {(sampleId: string, epoch: number) => Promise<Object>} readSample - Reads a specific sample file.
 * @property {() => Promise<import("../types/log").EvalLog>} readCompleteLog - Reads the complete log file including all samples.
 */

/**
 * Opens a remote log file and provides methods to read its contents.
 * @param {import("../api/Types.mjs").LogViewAPI} api - The api
 * @param {string} url - The URL of the remote zip file.
 * @param {number} concurrency - The number of concurrent operations allowed.
 * @returns {Promise<RemoteLogFile>} An object with methods to read the log file.
 */
export const openRemoteLogFile = async (api, url, concurrency) => {
  const queue = new AsyncQueue(concurrency);
  const remoteZipFile = await openRemoteZipFile(
    `${encodeURIComponent(url)}`,
    api.eval_log_size,
    api.eval_log_bytes,
  );

  /**
   * Reads and parses a JSON file from the zip.
   * @param {string} file - The name of the file to read.
   * @returns {Promise<Object>} The parsed JSON content.
   */
  const readJSONFile = async (file) => {
    try {
      const data = await remoteZipFile.readFile(file);
      const textDecoder = new TextDecoder("utf-8");
      const jsonString = textDecoder.decode(data);
      return asyncJsonParse(jsonString);
    } catch (error) {
      throw new Error(`Failed to read or parse file ${file}: ${error.message}`);
    }
  };

  /**
   * Lists all samples in the zip file.
   * @returns {Promise<SampleEntry[]>} An array of sample objects.
   */
  const listSamples = async () => {
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
   * @param {string} sampleId - The ID of the sample.
   * @param {number} epoch - The epoch of the sample.
   * @returns {Promise<Object>} The content of the sample file.
   */
  const readSample = (sampleId, epoch) => {
    const sampleFile = `samples/${sampleId}_epoch_${epoch}.json`;
    if (remoteZipFile.centralDirectory.has(sampleFile)) {
      return readJSONFile(sampleFile);
    } else {
      console.log({ dir: remoteZipFile.centralDirectory });
      throw new Error(
        `Unable to read sample file ${sampleFile} - it is not present in the manifest.`,
      );
    }
  };

  /**
   * Reads the results.json file.
   * @returns {Promise<Object>} The content of results.json.
   */
  const readHeader = async () => {
    if (remoteZipFile.centralDirectory.has("header.json")) {
      return readJSONFile("header.json");
    } else {
      const evalSpec = await readJSONFile("_journal/start.json");
      return {
        status: "started",
        eval: evalSpec.eval,
        plan: evalSpec.plan,
      };
    }
  };

  /**
   * Reads individual summary files when summaries.json is not available.
   * @returns {Promise<Object>} Combined summaries from individual files.
   */
  const readFallbackSummaries = async () => {
    const summaryFiles = Array.from(
      remoteZipFile.centralDirectory.keys(),
    ).filter(
      (filename) =>
        filename.startsWith("_journal/summaries/") &&
        filename.endsWith(".json"),
    );

    const summaries = [];
    const errors = [];

    await Promise.all(
      summaryFiles.map((filename) =>
        queue.enqueue(async () => {
          try {
            const partialSummary = await readJSONFile(filename);
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
   * @returns {Promise<Object>} All summaries.
   */
  const readSampleSummaries = async () => {
    if (remoteZipFile.centralDirectory.has("summaries.json")) {
      return await readJSONFile("summaries.json");
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
     * @returns {Promise<import("../types/log").EvalLog>} The complete log data.
     */
    readCompleteLog: async () => {
      const [evalLog, samples] = await Promise.all([
        readHeader(),
        listSamples().then((sampleIds) =>
          Promise.all(
            sampleIds.map(({ sampleId, epoch }) => readSample(sampleId, epoch)),
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
