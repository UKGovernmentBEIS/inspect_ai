// @ts-check
/**
 * Checks if a given value is numeric.
 */
export const isNumeric = (n: unknown): boolean => {
  return !isNaN(parseFloat(n as any)) && isFinite(n as any);
};

/**
 * Ensures the value is an array
 *
 * @param {*} val - The value to ensure is an array.
 * @returns {Array} - an Array
 */
export const toArray = <T>(val: T | T[]): Array<T> => {
  if (Array.isArray(val)) {
    return val;
  } else {
    return [val];
  }
};
