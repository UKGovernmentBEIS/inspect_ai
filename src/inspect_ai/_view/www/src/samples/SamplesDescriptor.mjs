import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";
import { ApplicationStyles } from "../appearance/Styles.mjs";
import {
  formatPrettyDecimal,
  formatDecimalNoTrailingZeroes,
  inputString,
  arrayToString,
} from "../utils/Format.mjs";
import { RenderedContent } from "../components/RenderedContent/RenderedContent.mjs";
import { isNumeric } from "../utils/Type.mjs";
import {
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypeObject,
  kScoreTypeOther,
  kScoreTypePassFail,
} from "../constants.mjs";

/**
 * Represents a utility summary of the samples that doesn't change with the selected score.
 * @typedef {Object} EvalDescriptor
 * @property {number} epochs - The number of epochs.
 * @property {import("../api/Types.mjs").SampleSummary[]} samples - The list of sample summaries.
 * @property {import("../Types.mjs").ScoreLabel[]} scores - the list of available scores
 * @property {(sample: import("../api/Types.mjs").BasicSampleData, scoreLabel: import("../Types.mjs").ScoreLabel) => ScorerDescriptor} scorerDescriptor - Returns the scorer descriptor for a sample and a specified scorer.
 * @property {(scoreLabel: import("../Types.mjs").ScoreLabel) => ScoreDescriptor} scoreDescriptor - Provides information about the score types and how to render them.
 * @property {(sample: import("../api/Types.mjs").BasicSampleData, scoreLabel: import("../Types.mjs").ScoreLabel) => SelectedScore} score - Returns information about a score for a sample.
 * @property {(sample: import("../api/Types.mjs").BasicSampleData, scorer: string) => string} scoreAnswer - Returns the answer for a sample and a specified scorer.
 */

/**
 * Represents a utility summary of the samples.
 * @typedef {Object} SamplesDescriptor
 * @property {EvalDescriptor} evalDescriptor - The EvalDescriptor.
 * @property {MessageShape} messageShape - The normalized sizes of input, target, and answer messages.
 * @property {ScoreDescriptor} selectedScoreDescriptor - Provides information about the score types and how to render them.
 * @property {(sample: import("../api/Types.mjs").BasicSampleData) => SelectedScore} selectedScore - Returns the selected score for a sample.
 * @property {(sample: import("../api/Types.mjs").BasicSampleData) => ScorerDescriptor} selectedScorerDescriptor - Returns the scorer descriptor for a sample using the selected scorer.
 */

/**
 * Provides information about the score types and rendering functions.
 * @typedef {Object} ScoreDescriptor
 * @property {string} scoreType - The type of the score (e.g., 'numeric', 'categorical', 'boolean').
 * @property {Array<Object>} [categories] - The categories for categorical scores.
 * @property {number} [min] - The minimum value for numeric scores.
 * @property {number} [max] - The maximum value for numeric scores.
 * @property {(a: import("../types/log").Value2, b: import("../types/log").Value2) => number} compare - Function to compare two score values.
 * @property {(score: import("../types/log").Value2) => any} render - Function to render the score value.
 */

/**
 * Provides descriptor functions for a scorer.
 * @typedef {Object} ScorerDescriptor
 * @property {() => string} metadata - Function to retrieve the metadata of the score.
 * @property {() => string} explanation - Function to retrieve the explanation of the score.
 * @property {() => string} answer - Function to retrieve the answer associated with the score.
 * @property {function(): Array<{name: string, rendered: function(): any}>} scores - Function to retrieve scores with their render functions.
 */

/**
 * Represents a score for a sample, including its value and render function.
 * @typedef {Object} SelectedScore
 * @property {import("../types/log").Value2} value - The value of the selected score.
 * @property {function(): any} render - Function to render the selected score.
 */

/**
 * Describes the shape of the messages based on their sizes.
 * @typedef {Object} MessageShape
 * @property {Object} raw
 * @property {number} raw.id - Normalized size of the id
 * @property {number} raw.input - Normalized size of the input message.
 * @property {number} raw.target - Normalized size of the target message.
 * @property {number} raw.answer - Normalized size of the answer message.
 * @property {number} raw.limit - Normalized size of the limit message.
 * @property {Object} normalized
 * @property {number} normalized.id - Normalized size of the id
 * @property {number} normalized.input - Normalized size of the input message.
 * @property {number} normalized.target - Normalized size of the target message.
 * @property {number} normalized.answer - Normalized size of the answer message.
 * @property {number} normalized.limit - Normalized size of the limit message.
 */

/**
 * @param {import("../Types.mjs").ScoreLabel[]} scores - the list of available scores
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {number} epochs - The number of epochs
 * @returns {EvalDescriptor} The EvalDescriptor
 */
export const createEvalDescriptor = (scores, samples, epochs) => {
  if (!samples) {
    return undefined;
  }

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample - the currently selected score
   * @param {import("../Types.mjs").ScoreLabel} scoreLabel - the score label
   * @returns {import("../types/log").Value2} The Score
   */
  const scoreValue = (sample, scoreLabel) => {
    // no scores, no value
    if (Object.keys(sample.scores).length === 0 || !scoreLabel) {
      return undefined;
    }

    if (
      scoreLabel.scorer !== scoreLabel.name &&
      sample.scores[scoreLabel.scorer] &&
      sample.scores[scoreLabel.scorer].value
    ) {
      return sample.scores[scoreLabel.scorer].value[scoreLabel.name];
    } else if (sample.scores[scoreLabel.name]) {
      return sample.scores[scoreLabel.name].value;
    } else {
      return undefined;
    }
  };

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {string} The answer
   */
  const scoreAnswer = (sample, scorer) => {
    if (sample) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.answer) {
        return sampleScore.answer;
      }
    } else {
      return undefined;
    }
  };

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {string} The explanation
   */
  const scoreExplanation = (sample, scorer) => {
    if (sample) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.explanation) {
        return sampleScore.explanation;
      }
    }
    return undefined;
  };

  // Retrieve the metadata for a sample
  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {Object} The explanation
   */
  const scoreMetadata = (sample, scorer) => {
    if (sample) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.metadata) {
        return sampleScore.metadata;
      }
    }
    return undefined;
  };

  /**
   * @param {import("../Types.mjs").ScoreLabel} [scoreLabel]
   * @returns {string}
   */
  const scoreLabelKey = (scoreLabel) => {
    if (!scoreLabel) {
      return "No score key";
    }
    return `${scoreLabel.scorer}.${scoreLabel.name}`;
  };

  /**
   * The EvalDescriptor is memoized. Compute all descriptors now to avoid duplicate work.
   * @type {Map<string, ScoreDescriptor>}
   */
  const scoreDescriptorMap = new Map();
  for (const scoreLabel of scores) {
    const uniqScoreValues = [
      ...new Set(
        samples
          .filter((sample) => !!sample.scores)
          .filter((sample) => {
            // There is no selected scorer, so include this value
            if (!scoreLabel) {
              return true;
            }

            if (scoreLabel.scorer !== scoreLabel.name) {
              return (
                Object.keys(sample.scores).includes(scoreLabel.scorer) &&
                Object.keys(sample.scores[scoreLabel.scorer].value).includes(
                  scoreLabel.name,
                )
              );
            } else {
              return Object.keys(sample.scores).includes(scoreLabel.name);
            }
          })
          .map((sample) => {
            return scoreValue(sample, scoreLabel);
          })
          .filter((value) => {
            return value !== null;
          }),
      ),
    ];
    const uniqScoreTypes = [
      ...new Set(uniqScoreValues.map((scoreValue) => typeof scoreValue)),
    ];

    for (const categorizer of scoreCategorizers) {
      const scoreDescriptor = categorizer.describe(
        uniqScoreValues,
        uniqScoreTypes,
      );
      if (scoreDescriptor) {
        scoreDescriptorMap.set(scoreLabelKey(scoreLabel), scoreDescriptor);
        break;
      }
    }
  }

  /**
   * @param {import("../Types.mjs").ScoreLabel} scoreLabel
   * @returns {ScoreDescriptor | undefined}
   */
  const scoreDescriptor = (scoreLabel) => {
    return scoreDescriptorMap.get(scoreLabelKey(scoreLabel));
  };

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample
   * @param {import("../Types.mjs").ScoreLabel} scoreLabel
   * @returns {any}
   */
  const scoreRendered = (sample, scoreLabel) => {
    const descriptor = scoreDescriptor(scoreLabel);
    const score = scoreValue(sample, scoreLabel);
    if (score === null || score === "undefined") {
      return "null";
    } else if (descriptor && descriptor.render) {
      return descriptor.render(score);
    } else {
      return score;
    }
  };

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample
   * @param {import("../Types.mjs").ScoreLabel} scoreLabel
   * @returns {ScorerDescriptor}
   */
  const scorerDescriptor = (sample, scoreLabel) => {
    return {
      metadata: () => {
        return scoreMetadata(sample, scoreLabel.scorer);
      },
      explanation: () => {
        return scoreExplanation(sample, scoreLabel.scorer);
      },
      answer: () => {
        return scoreAnswer(sample, scoreLabel.scorer);
      },
      scores: () => {
        if (!sample || !sample.scores) {
          return [];
        }
        const myScoreDescriptor = scoreDescriptor(scoreLabel);
        if (!myScoreDescriptor) {
          return [];
        }

        // Make a list of all the valid score names (this is
        // used to distinguish between dictionaries that contain
        // scores that should be treated as standlone scores and
        // dictionaries that just contain random values, which is allowed)
        const scoreNames = scores.map((score) => {
          return score.name;
        });
        const sampleScorer = sample.scores[scoreLabel.scorer];
        const scoreVal = sampleScorer.value;

        if (typeof scoreVal === "object") {
          const names = Object.keys(scoreVal);

          // See if this is a dictionary of score names
          // if any of the score names match, treat it
          // as a scorer dictionary
          if (
            names.find((name) => {
              return scoreNames.includes(name);
            })
          ) {
            // Since this dictionary contains keys which are  scores
            // we actually render the individual scores
            const scores = names.map((name) => {
              return {
                name,
                rendered: () => {
                  return myScoreDescriptor.render(scoreVal[name]);
                },
              };
            });
            return scores;
          } else {
            // Since this dictionary contains keys which are not scores
            // we just treat it like an opaque dictionary
            return [
              {
                name: scoreLabel.scorer,
                rendered: () => {
                  return myScoreDescriptor.render(scoreVal);
                },
              },
            ];
          }
        } else {
          return [
            {
              name: scoreLabel.scorer,
              rendered: () => {
                return myScoreDescriptor.render(scoreVal);
              },
            },
          ];
        }
      },
    };
  };

  /**
   * @param {import("../api/Types.mjs").BasicSampleData} sample
   * @param {import("../Types.mjs").ScoreLabel} scoreLabel
   * @returns {SelectedScore}
   */
  const score = (sample, scoreLabel) => {
    return {
      value: scoreValue(sample, scoreLabel),
      render: () => {
        return scoreRendered(sample, scoreLabel);
      },
    };
  };

  return {
    epochs,
    samples,
    scores,
    scorerDescriptor,
    scoreDescriptor,
    score,
    scoreAnswer,
  };
};

/**
 * Provides a utility summary of the samples
 *
 * @param {EvalDescriptor} evalDescriptor - The EvalDescriptor.
 * @param {import("../Types.mjs").ScoreLabel} selectedScore - Selected score.
 * @returns {SamplesDescriptor} - The SamplesDescriptor.
 */
export const createSamplesDescriptor = (evalDescriptor, selectedScore) => {
  if (!evalDescriptor) {
    return undefined;
  }

  // Find the total length of the value so we can compute an average
  const sizes = evalDescriptor.samples.reduce(
    (previous, current) => {
      const text = inputString(current.input).join(" ");
      const scoreValue = evalDescriptor.score(current, selectedScore).value;
      const scoreText = scoreValue
        ? String(scoreValue)
        : current.error
          ? String(current.error)
          : "";
      previous[0] = Math.min(Math.max(previous[0], text.length), 300);
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300,
      );
      previous[2] = Math.min(
        Math.max(
          previous[2],
          evalDescriptor.scoreAnswer(current, selectedScore?.name)?.length || 0,
        ),
        300,
      );
      previous[3] = Math.min(
        Math.max(previous[3], current.limit ? current.limit.length : 0),
        50,
      );
      previous[4] = Math.min(
        Math.max(previous[4], String(current.id).length),
        10,
      );
      previous[5] = Math.min(Math.max(previous[5], scoreText.length), 30);

      return previous;
    },
    [0, 0, 0, 0, 0, 0],
  );

  // normalize to base 1
  const maxSizes = {
    input: Math.min(sizes[0], 300),
    target: Math.min(sizes[1], 300),
    answer: Math.min(sizes[2], 300),
    limit: Math.min(sizes[3], 50),
    id: Math.min(sizes[4], 10),
    score: Math.min(sizes[4], 30),
  };
  const base =
    maxSizes.input +
      maxSizes.target +
      maxSizes.answer +
      maxSizes.limit +
      maxSizes.id +
      maxSizes.score || 1;
  const messageShape = {
    raw: {
      input: sizes[0],
      target: sizes[1],
      answer: sizes[2],
      limit: sizes[3],
      id: sizes[4],
      score: sizes[5],
    },
    normalized: {
      input: maxSizes.input / base,
      target: maxSizes.target / base,
      answer: maxSizes.answer / base,
      limit: maxSizes.limit / base,
      id: maxSizes.id / base,
      score: maxSizes.score / base,
    },
  };

  return {
    evalDescriptor,
    messageShape,
    selectedScoreDescriptor: evalDescriptor.scoreDescriptor(selectedScore),
    selectedScore: (sample) => evalDescriptor.score(sample, selectedScore),
    selectedScorerDescriptor: (sample) =>
      evalDescriptor.scorerDescriptor(sample, selectedScore),
  };
};

/**
 * @typedef {Object} ScoreCategorizer
 * @property {(values: import("../types/log").Value2[], types?: ("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]) => ScoreDescriptor} describe
 */
const scoreCategorizers = [
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (values.length === 2 && types.length === 1 && types[0] === "boolean") {
        return booleanScoreCategorizer();
      }
    },
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values) => {
      if (
        values.length === 2 &&
        values.every((val) => {
          return val === 1 || val === 0;
        })
      ) {
        return booleanScoreCategorizer();
      }
    },
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (
        types[0] === "string" &&
        types.length === 1 &&
        values.length < 5 &&
        !values.find((val) => {
          return val !== "I" && val !== "C" && val !== "P" && val !== "N";
        })
      ) {
        return passFailScoreCategorizer(values);
      }
    },
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (values.length < 10 && types.length === 1 && types[0] === "string") {
        return {
          scoreType: kScoreTypeCategorical,
          categories: values,
          compare: (a, b) => {
            return String(a).localeCompare(String(b));
          },
          render: (score) => {
            return score;
          },
        };
      }
    },
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "number") {
        const onlyNumeric = values.filter((val) => {
          return typeof val === "number";
        });

        return {
          scoreType: kScoreTypeNumeric,
          min: Math.min(...onlyNumeric),
          max: Math.max(...onlyNumeric),
          compare: (a, b) => {
            if (typeof a === "number" && typeof b === "number") {
              return a - b;
            } else {
              console.warn(
                "Comparing non-numerics using a nuermic score descriptor",
              );
              return 0;
            }
          },
          render: (score) => {
            return formatDecimalNoTrailingZeroes(Number(score));
          },
        };
      }
    },
  },
  {
    /**
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "object") {
        const buckets = values.map((val) => {
          return JSON.stringify(val);
        });
        const vals = new Set(buckets);
        let categories = undefined;
        if (vals.size < 10) {
          categories = Array.from(vals).map((val) => {
            return {
              val,
              text: val,
            };
          });
        }

        return {
          scoreType: kScoreTypeObject,
          categories,
          compare: () => {
            return 0;
          },
          render: (score) => {
            if (score === null || score === undefined) {
              return "[null]";
            }

            const scores = [];
            const keys = Object.keys(score);
            keys.forEach((key, index) => {
              const value = score[key];
              const formattedValue = isNumeric(value)
                ? formatPrettyDecimal(parseFloat(value))
                : value;
              const style = {
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                marginLeft: "0.5rem",
              };
              if (index + 1 < keys.length) {
                style["paddingBottom"] = "1em";
              }
              scores.push(html`
                <div style=${style}>
                  <div style=${{ fontSize: FontSize.smaller, fontWeight: 300 }}>
                    ${key}
                  </div>
                  <div style=${{ fontSize: FontSize.title, fontWeight: 600 }}>
                    ${formattedValue}
                  </div>
                </div>
              `);
            });

            return scores;
          },
        };
      }
    },
  },
  {
    /**
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    // @ts-ignore
    describe: () => {
      return {
        scoreType: kScoreTypeOther,
        compare: () => {
          return 0;
        },
        render: (score) => {
          return html`<${RenderedContent}
            id="other-score-value"
            entry=${{ value: score }}
          />`;
        },
      };
    },
  },
];

const filledCircleStyle = {
  fontSize: FontSize.small,
  fontFamily: "Consola Regular",
  width: "20px",
  height: "20px",
  display: "inline-flex",
  justifyContent: "center",
  alignItems: "center",
  borderRadius: "50%",
  paddingTop: "1px",
};

const booleanScoreCategorizer = () => {
  return {
    scoreType: "boolean",
    compare: (a, b) => {
      return Number(a.value) - Number(b.value);
    },
    render: (score) => {
      const scoreColorStyle = score
        ? ApplicationStyles.scoreFills.green
        : ApplicationStyles.scoreFills.red;

      return html`<span
        style=${{
          ...scoreColorStyle,
          ...filledCircleStyle,
        }}
        >${score}</span
      >`;
    },
  };
};

const passFailScoreCategorizer = (values) => {
  const categories = [];
  if (values.includes("C")) {
    categories.push({
      val: "C",
      text: "Correct",
    });
  }
  if (values.includes("P")) {
    categories.push({
      val: "P",
      text: "Partial",
    });
  }
  if (values.includes("I")) {
    categories.push({
      val: "I",
      text: "Incorrect",
    });
  }
  if (values.includes("N")) {
    categories.push({
      val: "N",
      text: "Refusal",
    });
  }
  const order = ["C", "P", "I", "N"];

  return {
    scoreType: kScoreTypePassFail,
    categories,
    render: (score) => {
      if (score === "C") {
        return html`<span
          style=${{
            ...ApplicationStyles.scoreFills.green,
            ...filledCircleStyle,
          }}
          >C</span
        >`;
      } else if (score === "I") {
        return html`<span
          style=${{
            ...ApplicationStyles.scoreFills.red,
            ...filledCircleStyle,
          }}
          >I</span
        >`;
      } else if (score === "P") {
        return html`<span
          style=${{
            ...ApplicationStyles.scoreFills.orange,
            ...filledCircleStyle,
          }}
          >P</span
        >`;
      } else if (score === "N") {
        return html`<span
          style=${{
            ...ApplicationStyles.scoreFills.red,
            ...filledCircleStyle,
          }}
          >N</span
        >`;
      } else {
        return score;
      }
    },
    compare: (a, b) => {
      const sort = order.indexOf(a.value) - order.indexOf(b.value);
      return sort;
    },
  };
};
