export const kSampleIdVariable = "id";
export const kSampleMetadataVariable = "metadata";
export const kSampleMetadataPrefix = kSampleMetadataVariable + ".";

export const KEYWORDS: string[] = ["and", "or", "not", "in", "not in", "mod"];

export const MATH_FUNCTIONS: [string, string][] = [
  ["min", "Minimum of two or more values"],
  ["max", "Maximum of two or more values"],
  ["abs", "Absolute value"],
  ["round", "Round to the nearest integer"],
  ["floor", "Round down to the nearest integer"],
  ["ceil", "Round up to the nearest integer"],
  ["sqrt", "Square root"],
  ["log", "Natural logarithm"],
  ["log2", "Base 2 logarithm"],
  ["log10", "Base 10 logarithm"],
];

export const SAMPLE_VARIABLES: [string, string][] = [
  ["has_error", "Checks if the sample has an error"],
  ["has_retries", "Checks if the sample has been retried"],
  [kSampleIdVariable, "The unique identifier of the sample"],
  [kSampleMetadataVariable, "Metadata associated with the sample"],
];

export const SAMPLE_FUNCTIONS: [string, string][] = [
  ["input_contains", "Checks if input contains a regular expression"],
  ["target_contains", "Checks if target contains a regular expression"],
  ["error_contains", "Checks if error contains a regular expression"],
];
