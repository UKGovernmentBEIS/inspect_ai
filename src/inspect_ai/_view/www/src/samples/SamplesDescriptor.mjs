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

/**
 * A string or string array
 * @typedef {(string[]|string)} SampleDescriptor
 */

export const kScoreTypePassFail = "passfail";
export const kScoreTypeCategorical = "categorical";
export const kScoreTypeNumeric = "numeric";
export const kScoreTypeOther = "other";
export const kScoreTypeObject = "object";
export const kScoreTypeBoolean = "boolean";

export const samplesDescriptor = (
  selectedScore,
  scorers,
  samples,
  epochs,
  context,
) => {
  if (!samples) {
    return undefined;
  }

  const score = (sample, scorer = selectedScore?.scorer) => {
    if (sample.scores[scorer]) {
      return sample.scores[scorer];
    } else {
      return undefined;
    }
  };

  // function for retrieving the sample score value
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
  const scoreAnswer = (sample, scorer) => {
    if (sample) {
      const sampleScore = score(sample, scorer);
      if (sampleScore && sampleScore.answer) {
        return sampleScore.answer;
      } else if (sample.output.choices && sample.output.choices.length > 0) {
        const content = sample.output.choices[0].message.content;
        if (typeof content === "string") {
          return content;
        } else {
          // TODO: Support image completions.
          return content.length > 0 ? content[0].text : "";
        }
      }
    } else {
      return undefined;
    }
  };

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
      previous[0] = Math.min(
        Math.max(previous[0], inputString(current.input).length),
        300,
      );
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300,
      );
      previous[2] = Math.min(
        Math.max(previous[2], scoreAnswer(current)?.length || 0),
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

const scoreCategorizers = [
  {
    describe: (values, types) => {
      if (values.length === 2 && types.length === 1 && types[0] === "boolean") {
        return booleanScoreCategorizer();
      }
    },
  },
  {
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
    describe: (values, types) => {
      if (values.length < 10 && types.length === 1 && types[0] === "string") {
        return {
          scoreType: kScoreTypeCategorical,
          categories: values,
          compare: (a, b) => {
            return a.localeCompare(b);
          },
          render: (score) => {
            return score;
          },
        };
      }
    },
  },
  {
    describe: (values, types) => {
      if (types.length !== 0 && types[0] === "number") {
        return {
          scoreType: kScoreTypeNumeric,
          min: Math.min(...values),
          max: Math.max(...values),
          compare: (a, b) => {
            return a - b;
          },
          render: (score) => {
            return formatDecimalNoTrailingZeroes(score);
          },
        };
      }
    },
  },
  {
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
    describe: (values, types, context) => {
      return {
        scoreType: kScoreTypeOther,
        render: (score) => {
          return html`<${RenderedContent}
            id="asdasdas"
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
      const sort = order.indexOf(a) - order.indexOf(b);
      return sort;
    },
  };
};
