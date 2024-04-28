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
    } else {
      const content = sample.output.choices[0].message.content;
      if (typeof content === "string") {
        return content;
      } else {
        // TODO: Support image completions.
        return content[0].text; 
      }  
    }
  } else {
    return undefined;
  }
};

export const userPromptForSample = (sample) => {
  if (sample) {
    if (typeof (sample.input) == "string") {
      return sample.input.trim();
    } else if (Array.isArray(sample.input)) {
      const userPrompt = sample.input.find(message => message.role == "user");
      if (userPrompt) {
        return userPrompt.content.trim();
      }
    }
  }

  return ''
}

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
      seconds / 60
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
  if (num.toString().includes(".")) {
    const decimal = num.toString().split(".")[1];
    const trimmed = decimal.replace(/\.?0+$/, '');
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
