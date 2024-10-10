//@ts-check

export const getVscodeApi = () => {
  // @ts-ignore
  return window.acquireVsCodeApi
    ? // @ts-ignore
      window.acquireVsCodeApi()
    : undefined;
};
