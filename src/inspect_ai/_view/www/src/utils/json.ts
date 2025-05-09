export const isJson = (text: string): boolean => {
  text = text.trim();
  if (text.startsWith("{") && text.endsWith("}")) {
    try {
      JSON.parse(text);
      return true;
    } catch {
      return false;
    }
  }
  return false;
};

export const parsedJson = (text: string): unknown | undefined => {
  text = text.trim();
  if (text.startsWith("{") && text.endsWith("}")) {
    try {
      return JSON.parse(text);
    } catch {
      return undefined;
    }
  }
  return undefined;
};

// Estimates the size of a list of objects by sampling a subset of the list.
export function estimateSize(list: unknown[], frequency = 0.2) {
  if (!list || list.length === 0) {
    return 0;
  }

  // Total number of samples
  const sampleSize = Math.ceil(list.length * frequency);

  // Get a proper random sample without duplicates
  const messageIndices = new Set<number>();
  while (
    messageIndices.size < sampleSize &&
    messageIndices.size < list.length
  ) {
    const randomIndex = Math.floor(Math.random() * list.length);
    messageIndices.add(randomIndex);
  }

  // Calculate size from sampled messages
  const totalSize = Array.from(messageIndices).reduce((size, index) => {
    return size + JSON.stringify(list[index]).length;
  }, 0);

  // Estimate total size based on sample
  const estimatedTotalSize = (totalSize / sampleSize) * list.length;
  return estimatedTotalSize;
}
