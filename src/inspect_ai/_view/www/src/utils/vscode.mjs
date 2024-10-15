//@ts-check

let _vscodeApi = undefined;

export const getVscodeApi = () => {
  // @ts-ignore
  if (window.acquireVsCodeApi) {
    if (_vscodeApi == undefined) {
      // @ts-ignore
      _vscodeApi = window.acquireVsCodeApi();
    }
    return _vscodeApi;
  } else {
    return undefined;
  }
};
