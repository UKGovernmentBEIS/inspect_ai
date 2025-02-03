//@ts-check

/**
 * Fetches a range of bytes from a remote resource and returns it as a `Uint8Array`.
 *
 * @param {string} url - The URL of the remote resource to fetch.
 * @param {number} start - The starting byte position of the range to fetch.
 * @param {number} end - The ending byte position of the range to fetch.
 * @returns {Promise<Uint8Array>} A promise that resolves to a `Uint8Array` containing the fetched byte range.
 * @throws {Error} If there is an issue with the network request.
 */
export const fetchRange = async (url, start, end) => {
  const response = await fetch(url, {
    headers: { Range: `bytes=${start}-${end}` },
  });
  const arrayBuffer = await response.arrayBuffer();
  return new Uint8Array(arrayBuffer);
};
