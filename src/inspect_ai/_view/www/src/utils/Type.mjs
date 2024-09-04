// @ts-check
/**
 * Checks if a given value is numeric.
 *
 * @param {*} n - The value to check.
 * @returns {boolean} - `true` if the value is numeric, `false` otherwise.
 */
export const isNumeric = (n) => {
  return !isNaN(parseFloat(n)) && isFinite(n);
};

/**
 * Ensures the value is an array
 *
 * @param {*} val - The value to ensure is an array.
 * @returns {Array} - an Array
 */
export const toArray = (val) => {
  if (Array.isArray(val)) {
    return val;
  } else {
    return [val];
  }
};
