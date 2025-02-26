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
