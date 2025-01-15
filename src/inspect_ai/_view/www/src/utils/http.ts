/**
 * Fetches a range of bytes from a remote resource and returns it as a `Uint8Array`.
 */
export const fetchRange = async (
  url: string,
  start: number,
  end: number,
): Promise<Uint8Array> => {
  const response = await fetch(url, {
    headers: { Range: `bytes=${start}-${end}` },
  });
  const arrayBuffer = await response.arrayBuffer();
  return new Uint8Array(arrayBuffer);
};
