//@ts-check

/**
 * Splits an array into chunks of a given size.
 *
 * @template T
 * @param {Array<T>} array - The array to chunk.
 * @param {number} chunkSize - The size of each chunk.
 * @returns {Array<Array<T>>} An array of arrays, where each inner array is a chunk of the original array.
 */
export const chunkArray = (array, chunkSize) => {
  const chunks = [];
  for (let i = 0; i < array.length; i += chunkSize) {
    chunks.push(array.slice(i, i + chunkSize));
  }
  return chunks;
};
