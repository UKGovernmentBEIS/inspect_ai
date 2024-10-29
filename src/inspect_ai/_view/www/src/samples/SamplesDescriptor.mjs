import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";
import { ApplicationStyles } from "../appearance/Styles.mjs";
import {
  formatPrettyDecimal,
  formatDecimalNoTrailingZeroes,
  inputString,
  arrayToString,
} from "../utils/Format.mjs";
import { RenderedContent } from "../components/RenderedContent.mjs";
import { isNumeric } from "../utils/Type.mjs";
import {
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypeObject,
  kScoreTypeOther,
  kScoreTypePassFail,
} from "../constants.mjs";

/**
 * Represents a utility summary of the samples.
 * @typedef {Object} SamplesDescriptor
 * @property {ScoreDescriptor} scoreDescriptor - Provides information about the score types and how to render them.
 * @property {number} epochs - The number of epochs.
 * @property {MessageShape} messageShape - The normalized sizes of input, target, and answer messages.
 * @property {(sample: import("../api/Types.mjs").SampleSummary) => SelectedScore} selectedScore - Returns the selected score for a sample.
 * @property {(sample: import("../api/Types.mjs").SampleSummary, scorer: string) => ScorerDescriptor} scorer - Returns the scorer descriptor for a sample and a specified scorer.
 * @property {(sample: import("../api/Types.mjs").SampleSummary) => ScorerDescriptor} selectedScorer - Returns the scorer descriptor for a sample using the selected scorer.
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
 * @property {() => string} explanation - Function to retrieve the explanation of the score.
 * @property {() => string} answer - Function to retrieve the answer associated with the score.
 * @property {function(): Array<{name: string, rendered: function(): any}>} scores - Function to retrieve scores with their render functions.
 */

/**
 * Represents the selected score for a sample, including its value and render function.
 * @typedef {Object} SelectedScore
 * @property {import("../types/log").Value2} value - The value of the selected score.
 * @property {function(): any} render - Function to render the selected score.
 */

/**
 * Describes the shape of the messages based on their sizes.
 * @typedef {Object} MessageShape
 * @property {number} input - Normalized size of the input message.
 * @property {number} target - Normalized size of the target message.
 * @property {number} answer - Normalized size of the answer message.
 */

/**
 * Provides a utility summary of the samples
 *
 * @param {import("../Types.mjs").ScoreLabel[]} scorers - the list of available scores
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {number} epochs - The number of epochs
 * @param {import("..//Types.mjs").RenderContext} context - The application context
 * @param {import("../Types.mjs").ScoreLabel} [selectedScore] - the currently selected score
 * @returns {SamplesDescriptor} The SamplesDescriptor
 */
export const createsSamplesDescriptor = (
  scorers,
  samples,
  epochs,
  context,
  selectedScore,
) => {
  if (!samples) {
    return undefined;
  }

  /**
   * @param {import("../api/Types.mjs").SampleSummary} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {import("../types/log").Score} The Score
   */
  const score = (sample, scorer = selectedScore?.scorer) => {
    if (sample.scores[scorer]) {
      return sample.scores[scorer];
    } else {
      return undefined;
    }
  };

  /**
   * @param {import("../api/Types.mjs").SampleSummary} sample - the currently selected score
   * @returns {import("../types/log").Value2} The Score
   */
  const scoreValue = (sample) => {
    // no scores, no value
    if (Object.keys(sample.scores).length === 0 || !selectedScore) {
      return undefined;
    }

    if (
      selectedScore.scorer !== selectedScore.name &&
      sample.scores[selectedScore.scorer] &&
      sample.scores[selectedScore.scorer].value
    ) {
      return sample.scores[selectedScore.scorer].value[selectedScore.name];
    } else if (sample.scores[selectedScore.name]) {
      return sample.scores[selectedScore.name].value;
    } else {
      return undefined;
    }
  };

  // Retrieve the answer for a sample
  /**
   * @param {import("../api/Types.mjs").SampleSummary} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {string} The answer
   */
  const scoreAnswer = (sample, scorer) => {
    if (sample) {
      const sampleScore = score(sample, scorer);
      if (sampleScore && sampleScore.answer) {
        return sampleScore.answer;
      }
    } else {
      return undefined;
    }
  };

  // Retrieve the answer for a sample
  /**
   * @param {import("../api/Types.mjs").SampleSummary} sample - the currently selected score
   * @param {string} scorer - the scorer name
   * @returns {string} The explanation
   */
  const scoreExplanation = (sample, scorer) => {
    if (sample) {
      const sampleScore = score(sample, scorer);
      if (sampleScore && sampleScore.explanation) {
        return sampleScore.explanation;
      }
    }
    return undefined;
  };

  const uniqScoreValues = [
    ...new Set(
      samples
        .filter((sample) => !!sample.scores)
        .filter((sample) => {
          // There is no selected scorer, so include this value
          if (!selectedScore) {
            return true;
          }

          if (selectedScore.scorer !== selectedScore.name) {
            return (
              Object.keys(sample.scores).includes(selectedScore.scorer) &&
              Object.keys(sample.scores[selectedScore.scorer].value).includes(
                selectedScore.name,
              )
            );
          } else {
            return Object.keys(sample.scores).includes(selectedScore.name);
          }
        })
        .map((sample) => {
          return scoreValue(sample);
        })
        .filter((value) => {
          return value !== null;
        }),
    ),
  ];
  const uniqScoreTypes = [
    ...new Set(uniqScoreValues.map((scoreValue) => typeof scoreValue)),
  ];

  /** @type {ScoreDescriptor} */
  let scoreDescriptor;
  for (const categorizer of scoreCategorizers) {
    scoreDescriptor = categorizer.describe(
      uniqScoreValues,
      uniqScoreTypes,
      context,
    );
    if (scoreDescriptor) {
      break;
    }
  }

  // Find the total length of the value so we can compute an average
  const sizes = samples.reduce(
    (previous, current) => {
      const text = inputString(current.input).join(" ");
      previous[0] = Math.min(Math.max(previous[0], text.length), 300);
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300,
      );
      previous[2] = Math.min(
        Math.max(
          previous[2],
          scoreAnswer(current, selectedScore?.name)?.length || 0,
        ),
        300,
      );
      return previous;
    },
    [0, 0, 0],
  );

  // normalize to base 1
  const base = sizes[0] + sizes[1] + sizes[2] || 1;
  const messageShape = {
    input: sizes[0] / base,
    target: sizes[1] / base,
    answer: sizes[2] / base,
  };

  const scoreRendered = (sample) => {
    const score = scoreValue(sample);
    if (score === null || score === "undefined") {
      return "null";
    } else if (scoreDescriptor.render) {
      return scoreDescriptor.render(score);
    } else {
      return score;
    }
  };

  const scorerDescriptor = (sample, scorer) => {
    return {
      explanation: () => {
        return scoreExplanation(sample, scorer);
      },
      answer: () => {
        return scoreAnswer(sample, scorer);
      },
      scores: () => {
        if (!sample || !sample.scores) {
          return [];
        }

        // Make a list of all the valid score names (this is
        // used to distinguish between dictionaries that contain
        // scores that should be treated as standlone scores and
        // dictionaries that just contain random values, which is allowed)
        const scoreNames = scorers.map((score) => {
          return score.name;
        });
        const sampleScorer = sample.scores[scorer];
        const scoreVal = sampleScorer.value;
        if (typeof scoreVal === "object") {
          const names = Object.keys(scoreVal);
          if (
            names.find((name) => {
              return !scoreNames.includes(name);
            })
          ) {
            // Since this dictionary contains keys which are not scores
            // we just treat it like an opaque dictionary
            return [
              {
                name: scorer,
                rendered: () => {
                  return scoreDescriptor.render(scoreVal);
                },
              },
            ];
          } else {
            // Since this dictionary contains keys which are  scores
            // we actually render the individual scores
            const scores = names.map((name) => {
              return {
                name,
                rendered: () => {
                  return scoreDescriptor.render(scoreVal[name]);
                },
              };
            });
            return scores;
          }
        } else {
          return [
            {
              name: scorer,
              rendered: () => {
                return scoreDescriptor.render(scoreVal);
              },
            },
          ];
        }
      },
    };
  };

  return {
    scoreDescriptor,
    epochs,
    messageShape,
    selectedScore: (sample) => {
      return {
        value: scoreValue(sample),
        render: () => {
          return scoreRendered(sample);
        },
      };
    },
    scorer: (sample, scorer) => {
      return scorerDescriptor(sample, scorer);
    },
    selectedScorer: (sample) => {
      return scorerDescriptor(sample, selectedScore?.scorer);
    },
  };
};

/**
 * @typedef {Object} ScoreCategorizer
 * @property {(values: import("../types/log").Value2[], types?: ("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[], context?: import("../Types.mjs").RenderContext) => ScoreDescriptor} describe
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
        (values.length === 1 || values.length === 2) &&
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
     * @param {import("../types/log").Value2[]} values - the currently selected score
     * @param {("string" | "number" | "bigint" | "boolean" | "symbol" | "undefined" | "object" | "function")[]} [types] - the scorer name
     * @param {import("../Types.mjs").RenderContext} [context] - the application context
     * @returns {ScoreDescriptor} a ScoreDescriptor
     */
    // @ts-ignore
    describe: (values, types, context) => {
      return {
        scoreType: kScoreTypeOther,
        compare: () => {
          return 0;
        },
        render: (score) => {
          return html`<${RenderedContent}
            id="other-score-value"
            entry=${{ value: score }}
            context=${context}
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
