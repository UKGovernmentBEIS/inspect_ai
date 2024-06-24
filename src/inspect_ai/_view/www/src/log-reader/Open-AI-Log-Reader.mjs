import { arrayToString } from "../utils/Format.mjs";
import { register } from "./Log-Reader.mjs";
import { filename } from "../utils/Path.mjs";

export const openAiLogReader = {
  name: "OpenAiEvalsFileReader",
  canRead: (filename) => {
    return filename.match(/\d{12}.{8}_.+?\.jsonl/);
  },
  read: (contents) => {
    const kSpec = "spec";
    const kFinal = "final";
    const kSample = "sample";
    const kMetrics = "metrics";
    const kMatch = "match";
    const elementType = (json) => {
      if (json["spec"] !== undefined) {
        return kSpec;
      } else if (json["final_report"] !== undefined) {
        return kFinal;
      } else if (
        json["sample_id"] !== undefined &&
        json["type"] !== undefined
      ) {
        switch (json.type) {
          case "sampling":
            return kSample;
          case "metrics":
            return kMetrics;
          case "match":
            return kMatch;
        }
        return json["type"];
      } else {
        //console.warn("Unprocessed json element in open ai file:")
        //console.warn(json);
      }
    };

    const generateMessage = (content) => {
      return {
        message: {
          content,
          source: "generate",
          role: "assistant",
        },
        stop_reason: "stop",
      };
    };

    const lines = contents.split(/\r\n|\n/);
    const evalLog = {
      eval: {},
      plan: {},
      samples: [],
      results: {},
    };

    for (const line of lines) {
      // Skip any empty lines
      if (!line) {
        continue;
      }

      const json = JSON.parse(line);
      const elType = elementType(json);
      switch (elType) {
        case kSpec: {
          const spec = json.spec;
          evalLog.eval.metadata = {};
          evalLog.eval.config = {};

          // Base eval data
          evalLog.eval.task = spec.eval_name;
          evalLog.eval.run_id = spec.run_id;
          evalLog.eval.created = spec.created_at;
          evalLog.eval.model = spec.completion_fns[0];
          evalLog.status = "success";

          // Parse configuration
          evalLog.eval.config = {
            seed: spec.run_config.seed,
            split: spec.split,
          };
          ["max_samples", "command"].forEach((key) => {
            if (spec.run_config[key] && spec.run_config[key] !== null) {
              evalLog.eval.config[key] = spec.run_config[key];
            }
          });

          // Parse metadata
          ["initial_settings"].forEach((key) => {
            if (spec.run_config[key] && spec.run_config[key] !== null) {
              evalLog.eval.metadata[key] = spec.run_config[key];
            }
          });

          // Parse 'plan'
          evalLog.plan = {};
          evalLog.plan.steps = [];
          evalLog.plan.config = [];
          const generateName = evalLog.eval.model;
          const completions = spec.run_config.completion_fns;
          evalLog.plan.steps.push(
            ...completions.map((comp) => {
              return {
                solver: comp === generateName ? "generate" : comp,
                params: {},
              };
            }),
          );

          const evalSpec = spec.run_config.eval_spec;
          const scorer = {
            name: evalSpec.cls.split(":")[1],
            metadata: evalSpec.args,
          };
          scorer.metadata["cls"] = evalSpec.cls;
          evalLog.results = evalLog.results || {};
          evalLog.results.scorer = scorer;

          // Get the sample file data
          if (evalSpec.args.samples_jsonl) {
            evalLog.eval = evalLog.eval || {};
            evalLog.eval.dataset = {
              name: filename(evalSpec.args.samples_jsonl),
              location: evalSpec.args.samples_jsonl,
            };
          }
          break;
        }
        case kSample: {
          evalLog.samples = evalLog.samples || [];
          const sample_id = json.sample_id;
          const idx = evalLog.samples.findIndex((sam) => {
            return sam.sample_idx === sample_id;
          });

          const sample = idx > -1 ? evalLog.samples[idx] : {};
          sample.sample_idx = json.sample_id;
          sample.metadata = sample.metadata || {};

          sample.id = json["sample_id"].split(".").reverse()[0];
          [
            "sample_id",
            "run_id",
            "event_id",
            "created_by",
            "created_at",
          ].forEach((key) => {
            if (!sample.metadata[key]) {
              sample.metadata[key] = json[key];
            }
          });
          sample.score = sample.score || { value: "" };
          sample.messages = sample.messages || [];
          sample.messages.push(...json.data.prompt);

          if (json.data.sampled) {
            sample.output = sample.output || {};
            sample.output.choices =
              sample.output.choices ||
              json.data.sampled.map((sample) => generateMessage(sample));
            sample.messages.push({
              role: "assistant",
              content: arrayToString(json.data.sampled),
            });
          }

          // The first user message is treated as the input
          if (!sample.input) {
            const inputMsg = json.data.prompt?.find((msg) => {
              return msg.role === "user";
            });

            // But the messages may be very long so truncate.
            sample.input = inputMsg ? inputMsg.content.split("\n")[0] : "";
          }

          if (idx > -1) {
            evalLog.samples[idx] = sample;
          } else {
            evalLog.samples.push(sample);
          }
          break;
        }

        case kMetrics: {
          const sample_id = json.sample_id;
          const idx = evalLog.samples.findIndex((sam) => {
            return sam.sample_idx === sample_id;
          });
          const score = evalLog.samples[idx].score || {};
          if (json.data.choice) {
            evalLog.samples[idx].output = evalLog.samples[idx].output || {};
            evalLog.samples[idx].output.completion =
              evalLog.samples[idx].output.completion || json.data.choice;

            score.value = score.value || json.data.choice;
          }
          evalLog.samples[idx].score = score;
          break;
        }

        case kMatch: {
          const sample_id = json.sample_id;
          const idx = evalLog.samples.findIndex((sam) => {
            return sam.sample_idx === sample_id;
          });

          const score = evalLog.samples[idx].score || {};
          score.value = json.data.correct ? "C" : "I";
          if (json.data.expected) {
            evalLog.samples[idx].target =
              evalLog.samples[idx].target || json.data.expected;
          }
          if (json.data.picked) {
            evalLog.samples[idx].output = evalLog.samples[idx].output || {
              choices: json.data.picked.map((pick) => generateMessage(pick)),
            };
          }

          if (json.data.sampled) {
            if (!evalLog.samples[idx].output.choices) {
              evalLog.samples[idx].output = evalLog.samples[idx].output || {
                choices: json.data.sampled.map((sample) =>
                  generateMessage(sample),
                ),
              };
            } else {
              evalLog.samples[idx].metadata =
                evalLog.samples[idx].metadata || {};
              evalLog.samples[idx].metadata.sampled = json.data.sampled;
            }
          }
          evalLog.samples[idx].score = score;
          break;
        }

        case kFinal: {
          const final_report = json.final_report;
          const keys = Object.keys(final_report);

          const metrics = {};
          keys.forEach((key) => {
            metrics[key] = {
              name: key,
              value: final_report[key],
              options: {},
              metadata: {},
            };
          });
          evalLog.results = evalLog.results || {};
          evalLog.results["metrics"] = metrics;
          break;
        }
      }
    }
    return evalLog;
  },
};

register(openAiLogReader);
