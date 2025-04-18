import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../@types/log";

/**
 * Converts an array or a single value to a comma-separated string.
 */
export const arrayToString = (val: string | string[]): string => {
  val = Array.isArray(val) ? val : [val];
  return val.join(", ");
};

/**
 * Gets a string for a sample input.
 */
export const inputString = (
  input:
    | string
    | Array<
        | ChatMessageUser
        | ChatMessageSystem
        | ChatMessageAssistant
        | ChatMessageTool
      >,
): string[] => {
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
 */
export const formatDataset = (
  samples: number,
  epochs: number,
  name: string | null,
): string => {
  const perEpochSamples = epochs > 0 ? samples / epochs : samples;
  const namePrefix = name ? `${name} — ` : "";

  const terms: string[] = [
    namePrefix,
    String(perEpochSamples),
    epochs > 1 ? `x ${epochs} ` : "",
    samples === 1 ? "sample" : "samples",
  ];

  return terms.join(" ");
};

/**
 * Formats a duration given in seconds into a human-readable string.
 */
export const formatTime = (seconds: number): string => {
  if (seconds < 60) {
    return `${formatPrettyDecimal(seconds, 1)} sec`;
  } else if (seconds < 60 * 60) {
    return `${Math.floor(seconds / 60)} min ${Math.floor(seconds % 60)} sec`;
  } else if (seconds < 60 * 60 * 24) {
    const hours = Math.floor(seconds / (60 * 60));
    const minutes = Math.floor((seconds % (60 * 60)) / 60);
    const remainingSeconds = seconds % 60;
    return `${hours} hr ${minutes} min ${remainingSeconds} sec`;
  } else {
    const days = Math.floor(seconds / (60 * 60 * 24));
    const hours = Math.floor((seconds % (60 * 60 * 24)) / (60 * 60));
    const minutes = Math.floor((seconds % (60 * 60)) / 60);
    const remainingSeconds = seconds % 60;
    return `${days} days ${hours} hr ${minutes} min ${remainingSeconds} sec`;
  }
};

/**
 * Formats a number to a string with specific decimal places for prettiness.
 */
export function formatPrettyDecimal(
  num: number,
  maxDecimals: number = 3,
): string {
  const numDecimalPlaces = num.toString().includes(".")
    ? num.toString().split(".")[1].length
    : 0;

  if (numDecimalPlaces === 0) {
    return num.toFixed(1);
  } else if (numDecimalPlaces > maxDecimals) {
    return num.toFixed(maxDecimals);
  } else {
    return num.toString();
  }
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 */
export function formatDecimalNoTrailingZeroes(num: number): string {
  // This isn't a number, continue
  // TODO: Remove this, its crazy
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
 */
export function toTitleCase(str: string): string {
  if (!str) {
    return str;
  }

  return str
    .split(" ")
    .map((w) =>
      w.length > 0 ? w[0].toUpperCase() + w.substr(1).toLowerCase() : w,
    )
    .join(" ");
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 */
export function formatNoDecimal(num: number): string {
  // This isn't a number, continue
  // TODO: remove This is crazy
  if (typeof num !== "number") {
    return num;
  }

  // Round to a whole number
  const rounded = Math.round(num);
  return rounded.toFixed(0);
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 */
export function formatNumber(num: number): string {
  return num.toLocaleString(navigator.language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 5,
  });
}

/**
 * Formats a number to a string without trailing zeroes after the decimal point.
 */
export function formatDateTime(date: Date): string {
  const options = {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  };

  // Use the default system locale and timezone
  // @ts-ignore
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

/**
 * Returns the formatted duration between two dates
 */
export function formatDuration(start: Date, end: Date): string {
  const durationMs = end.getTime() - start.getTime();
  const durationSec = durationMs / 1000;
  return formatTime(durationSec);
}
