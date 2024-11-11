// @ts-check
import { html } from "htm/preact";

/**
 * Converts an array or a single value to a comma-separated string.
 *
 * @param {(string|string[])} val - The value to be converted. Can be a string or an array of strings.
 * @returns {string} - A comma-separated string.
 */
export const arrayToString = (val) => {
  val = Array.isArray(val) ? val : [val];
  return val.join(", ");
};

/**
 * Gets a string for a sample input.
 *
 * @param {(string|Array.<import("../types/log").ChatMessageUser | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageTool>)} input - The input to process. Can be a string or an array of objects containing a content string.
 * @returns {(string[])} - The processed string or an array of strings.
 */
export const inputString = (input) => {
  if (typeof input === "string") {
    return [input];
  } else {
    return input.map((inp) => {
      if (typeof inp === "string") {
        return inp;
      } else {
        const content = inp.content;
        if (typeof content === "string") {
          return content;
        } else {
          const result = content.map((con) => {
            if (con.type === "text") {
              return con.text;
            } else {
              return "";
            }
          });
          return result.join("\n");
        }
      }
    });
  }
};

/**
 * Formats dataset information into a string.
 *
 * @param {string} name - The name of the dataset.
 * @param {number} samples - The total number of samples in the dataset.
 * @param {number} epochs - The number of epochs.
 * @returns {string} - A formatted string describing the dataset.
 */
export const formatDataset = (name, samples, epochs) => {
  const perEpochSamples = epochs > 0 ? samples / epochs : samples;
  return `${name ? "— " : ""}${perEpochSamples + " "}${epochs > 1 ? `x ${epochs} ` : ""}${samples === 1 ? "sample" : "samples"}`;
};

/**
 * Extracts and trims the user prompt from a sample input.
 *
 * @param {import("../types/log").EvalSample} sample - The sample containing input data.
 * @returns {(string | Array<string|import("preact").JSX.Element>)} - The trimmed user prompt or an array of contents if the input is an array.
 */
export const userPromptForSample = (sample) => {
  if (sample) {
    if (typeof sample.input == "string") {
      return sample.input.trim();
    } else if (Array.isArray(sample.input)) {
      const userPrompt = sample.input.find((message) => message.role == "user");
      if (userPrompt) {
        const contents = userPrompt.content;
        if (Array.isArray(contents)) {
          const results = [];
          for (const content of contents) {
            if (content.type === "text") {
              results.push(content.text);
            } else {
              results.push(
                html`<img
                  src="${content.image}"
                  style=${{
                    maxWidth: "400px",
                    border: "solid var(--bs-border-color) 1px",
                  }}
                />`,
              );
            }
          }
          return results;
        } else {
          return contents.trim();
        }
      }
    }
  }
  return "";
};

/**
 * Formats a score with specific HTML based on its value.
 *
 * @param {string} score - The score to format.
 * @returns {import("preact").JSX.Element|string} The formatted score as an HTML template or the original score if not "C" or "I".
 */
export const formatScore = (score) => {
  // Circle with single letter
  if (score === "C") {
    return html`<span class="circle-border score-green">C</span>`;
  } else if (score === "I") {
    return html`<span class="circle-border score-red">I</span>`;
  } else {
    return score;
  }
};

/**
 * Formats a duration given in seconds into a human-readable string.
 *
 * @param {number} seconds - The duration in seconds.
 * @returns {string} - The formatted time string.
 */
export const formatTime = (seconds) => {
  if (seconds < 60) {
    return `${seconds} sec`;
  } else if (seconds < 60 * 60) {
    return `${Math.floor(seconds / 60)} min ${seconds % 60} sec`;
  } else {
    return `${Math.floor(seconds / (60 * 60 * 24))} days ${Math.floor(
      seconds / 60,
    )} min ${seconds % 60} sec`;
  }
};

/**
 * Formats a number to a string with specific decimal places for prettiness.
 *
 * @param {number} num - The number to format.
 * @returns {string} - The formatted number as a string.
 */
export function formatPrettyDecimal(num) {
  const numDecimalPlaces = num.toString().includes(".")
    ? num.toString().split(".")[1].length
    : 0;

  if (numDecimalPlaces === 0) {
    return num.toFixed(1);
  } else if (numDecimalPlaces > 3) {
    return num.toFixed(3);
  } else {
    return num.toString();
  }
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 *
 * @param {number} num - The number to format.
 * @returns {string|number} - The formatted number as a string, or the original input if it's not a number.
 */
export function formatDecimalNoTrailingZeroes(num) {
  // This isn't a number, continue
  if (typeof num !== "number") {
    return num;
  }

  if (num.toString().includes(".")) {
    const decimal = num.toString().split(".")[1];
    const trimmed = decimal.replace(/\.?0+$/, "");
    return num.toFixed(trimmed.length);
  } else {
    return num.toFixed(0);
  }
}

/**
 * Converts a string to title case.
 *
 * @param {string} str - The string to convert.
 * @returns {string} - The string in title case.
 */
export function toTitleCase(str) {
  return str
    .split(" ")
    .map((w) => w[0].toUpperCase() + w.substr(1).toLowerCase())
    .join(" ");
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 *
 * @param {number} num - The number to format.
 * @returns {string|number} - The formatted number as a string, or the original input if it's not a number.
 */
export function formatNoDecimal(num) {
  // This isn't a number, continue
  if (typeof num !== "number") {
    return num;
  }

  // Round to a whole number
  const rounded = Math.round(num);
  return rounded.toFixed(0);
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 *
 * @param {number} num - The number to format.
 * @returns {string} - The formatted number as a string
 */
export function formatNumber(num) {
  return num.toLocaleString(navigator.language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 5,
  });
}
