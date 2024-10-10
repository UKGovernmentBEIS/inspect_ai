//@ts-check

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 *
 * @param { import("./Types.mjs").LogViewAPI } api - The api to use when loading logs
 * @returns { import("./Types.mjs").ClientAPI } A Client API for the viewer
 */
export const clientApi = (api) => {

    let current_log = undefined;
    let current_path = undefined;

    /**
     * Gets a log
     *
     * @param { string } log_file - The api to use when loading logs
     * @returns { Promise<import("./Types.mjs").LogContents> } A Log Viewer API
     */
    const get_log = async (log_file) => {
        if (log_file !== current_path) {
            current_log = await api.eval_log(log_file);
        }
        return current_log;
    }

    /**
     * Gets a log summary
     *
     * @param { string } log_file - The api to use when loading logs
     * @returns { Promise<import("./Types.mjs").EvalSummary> } A Log Viewer API
     */
    const get_log_summary = async (log_file) => {
        const logContents = await get_log(log_file);

        /**
        * @type {import("./Types.mjs").SampleSummary[]}
        */
        const sampleSummaries = logContents.parsed.samples ? logContents.parsed.samples?.map((sample) => {
            return {
                id: sample.id,
                epoch: sample.epoch,
                input: sample.input,
                target: sample.target,
                scores: sample.scores,
                metadata: sample.metadata
            }
        }) : [];

        const parsed = logContents.parsed;
        return {
            version: parsed.version,
            status: parsed.status,
            eval: parsed.eval,
            plan: parsed.plan,
            results: parsed.results,
            stats: parsed.stats,
            error: parsed.error,
            sampleSummaries
        };
    }


    /**
     * Gets a sample
     *
     * @param { string } log_file - The api to use when loading logs
     * @param { string | number } id - The api to use when loading logs
     * @param { number } epoch - The api to use when loading logs
     * @returns { Promise<import("../types/log").EvalSample | undefined> }  The sample
     */
    const get_log_sample = async (log_file, id, epoch) => {
        const logContents = await get_log(log_file);
        if (logContents.parsed.samples && logContents.parsed.samples.length > 0) {
            return logContents.parsed.samples.find((sample) => {
                return sample.id === id && sample.epoch === epoch;
            })
        }
        return undefined;
    }

    return {
        client_events: () => {
            return api.client_events();
        },
        get_log_paths: () => {
            return api.eval_logs()
        },
        get_log_headers: (log_files) => {
            return api.eval_log_headers(log_files)
        },
        get_log_summary,
        get_log_sample,
        open_log_file: (log_file, log_dir) => {
            return api.open_log_file(log_file, log_dir)
        },
        download_log_file: (log_file, download_files, web_workers) => {
            return api.download_file(log_file, download_files, web_workers)

        }
    }
}