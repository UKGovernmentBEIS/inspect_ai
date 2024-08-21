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
