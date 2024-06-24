import { html } from "htm/preact";

/**
 * A string or string array
 * @typedef {(string[]|string)} MaybeArray
 */

/**
 *
 * @param MaybeArray val
 */
export const arrayToString = (val) => {
  val = Array.isArray(val) ? val : [val];
  return val.join(", ");
};

const shorteners = [/^.*(\[.+\])$/m];

/**
 *
 * @param string completion
 */
export const shortenCompletion = (completion) => {
  if (!completion) {
    return completion;
  }

  let shortened = undefined;
  for (const shortenPattern of shorteners) {
    const shortMatch = completion.match(shortenPattern);
    if (shortMatch && shortMatch[1]) {
      shortened = shortMatch[1];
      break;
    }
  }
  return shortened || completion;
};

export const answerForSample = (sample) => {
  if (sample) {
    if (sample.score?.answer) {
      return sample.score.answer;
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

// Gets a string for a sample input
export const inputString = (input) => {
  if (typeof input === "string") {
    return input;
  } else {
    return input.map((inp) => {
      if (typeof inp === "string") {
        return inp;
      } else {
        return inp.content;
      }
    });
  }
};

export const formatDataset = (name, samples, epochs) => {
  const perEpochSamples = epochs > 0 ? samples / epochs : samples;
  return `${name ? "— " : ""}${perEpochSamples + " "}${epochs > 1 ? `x ${epochs} ` : ""}${samples === 1 ? "sample" : "samples"}`;
};

export const userPromptForSample = (sample) => {
  if (sample) {
    if (typeof sample.input == "string") {
      return sample.input.trim();
    } else if (Array.isArray(sample.input)) {
      const userPrompt = sample.input.find((message) => message.role == "user");
      if (userPrompt) {
        return userPrompt.content.trim();
      }
    }
  }

  return "";
};

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

export const formatTime = (seconds) => {
  if (seconds < 60) {
    return `${seconds} sec`;
  } else if (seconds < 60 * 60) {
    return `${Math.floor(seconds / 60)} min ${seconds % 60} sec`;
  } else {
    return `${Math.floor((seconds / 60) * 60 * 24)} days ${Math.floor(
      seconds / 60,
    )} min ${seconds % 60} sec`;
  }
};

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

export function toTitleCase(str) {
  return str
    .split(" ")
    .map((w) => w[0].toUpperCase() + w.substr(1).toLowerCase())
    .join(" ");
}
