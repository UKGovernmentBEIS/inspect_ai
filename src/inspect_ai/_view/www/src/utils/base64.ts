/**
 * Determines whether a string is a base64 encoded string
 */
export const isBase64 = (str: string): boolean => {
  const base64Pattern =
    /^(?:[A-Za-z0-9+/]{4})*?(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
  return base64Pattern.test(str);
};
