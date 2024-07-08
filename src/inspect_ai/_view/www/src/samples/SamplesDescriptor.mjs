import { html } from "htm/preact";
import { sharedStyles } from "../Constants.mjs";
import {
  formatPrettyDecimal,
  formatDecimalNoTrailingZeroes,
  inputString,
  arrayToString,
  answerForSample,
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

export const samplesDescriptor = (samples, epochs, context) => {
  if (!samples) {
    return undefined;
  }

  const uniqScoreValues = [
    ...new Set(
      samples
        .filter((sample) => !!sample.score)
        .map((sample) => sample.score.value)
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
      previous[0] = Math.max(previous[0], inputString(current.input).length);
      previous[1] = Math.max(previous[1], arrayToString(current.target).length);
      previous[2] = Math.max(
        previous[2],
        answerForSample(current)?.length || 0,
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
  return { scoreDescriptor, epochs, messageShape };
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
            if (score === null) {
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
                  <div style=${{ fontSize: "0.9em", fontWeight: 300 }}>
                    ${key}
                  </div>
                  <div style=${{ fontSize: "1.5em", fontWeight: 600 }}>
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
  border: "solid 1px",
  fontSize: "0.8em",
  width: "2em",
  height: "2em",
  display: "inline-flex",
  justifyContent: "center",
  alignItems: "center",
  borderRadius: "50%",
};

const booleanScoreCategorizer = () => {
  return {
    scoreType: "boolean",
    render: (score) => {
      const scoreColorStyle = score
        ? sharedStyles.scoreFills.green
        : sharedStyles.scoreFills.red;

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
            ...sharedStyles.scoreFills.green,
            ...filledCircleStyle,
          }}
          >C</span
        >`;
      } else if (score === "I") {
        return html`<span
          style=${{
            ...sharedStyles.scoreFills.red,
            ...filledCircleStyle,
          }}
          >I</span
        >`;
      } else if (score === "P") {
        return html`<span
          style=${{
            ...sharedStyles.scoreFills.orange,
            ...filledCircleStyle,
          }}
          >P</span
        >`;
      } else if (score === "N") {
        return html`<span
          style=${{
            ...sharedStyles.scoreFills.red,
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
