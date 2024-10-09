//@ts-check
import { AsyncQueue } from "../utils/queue.mjs";
import { openRemoteZipFile } from "../utils/remoteZipFile.mjs";

/**
 * @typedef {Object} SampleEntry
 * @property {string} sampleId
 * @property {number} epoch
 */

/**
 * Opens a remote log file and provides methods to read its contents.
 * @param {string} url - The URL of the remote zip file.
 * @param {number} concurrency - The number of concurrent operations allowed.
 * @returns {Promise<Object>} An object with methods to read the log file.
 */
export const openRemoteLogFile = async (url, concurrency) => {
  const queue = new AsyncQueue(concurrency);
  const remoteZipFile = await openRemoteZipFile(url);

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
      return JSON.parse(jsonString);
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
   * Reads the start.json file.
   * @returns {Promise<Object>} The content of start.json.
   */
  const readStart = () => readJSONFile("start.json");

  /**
   * Reads a specific sample file.
   * @param {string} sampleId - The ID of the sample.
   * @param {number} epoch - The epoch of the sample.
   * @returns {Promise<Object>} The content of the sample file.
   */
  const readSample = (sampleId, epoch) =>
    readJSONFile(`samples/${sampleId}_epoch_${epoch}.json`);

  /**
   * Reads the results.json file.
   * @returns {Promise<Object>} The content of results.json.
   */
  const readResults = () => readJSONFile("results.json");

  /**
   * Reads individual summary files when summary.json is not available.
   * @returns {Promise<Object>} Combined summaries from individual files.
   */
  const readFallbackSummaries = async () => {
    const summaryFiles = Array.from(
      remoteZipFile.centralDirectory.keys(),
    ).filter(
      (filename) =>
        filename.startsWith("summaries/") && filename.endsWith(".json"),
    );

    const summaries = {};
    const errors = [];

    await Promise.all(
      summaryFiles.map((filename) =>
        queue.enqueue(async () => {
          try {
            const partialSummary = await readJSONFile(filename);
            Object.assign(summaries, partialSummary);
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
  const readAllSummaries = async () => {
    try {
      return await readJSONFile("summary.json");
    } catch {
      console.warn(
        "summary.json not found, falling back to individual summary files",
      );
      return readFallbackSummaries();
    }
  };

  return {
    readAllSummaries,
    /**
     * Reads the complete log file.
     * @returns {Promise<import("../types/log").EvalLog>} The complete log data.
     */
    readCompleteLog: async () => {
      const [evalResult, startData, samples] = await Promise.all([
        readResults(),
        readStart(),
        listSamples().then((sampleIds) =>
          Promise.all(
            sampleIds.map(({ sampleId, epoch }) => readSample(sampleId, epoch)),
          ),
        ),
      ]);

      return {
        status: evalResult.status,
        eval: startData.eval,
        plan: startData.plan,
        results: evalResult.results,
        stats: evalResult.stats,
        error: evalResult.error,
        samples,
      };
    },
  };
};
