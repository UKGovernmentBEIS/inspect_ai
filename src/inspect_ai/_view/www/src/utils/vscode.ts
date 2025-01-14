/**
 * Type definition for the VS Code API object
 * Note: This is a minimal definition - expand based on your needs
 */
interface VSCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

/**
 * The cached instance of the VS Code API
 */
let vscodeApi: VSCodeApi | undefined;

// Declare the acquireVsCodeApi function on the window object
declare global {
  interface Window {
    acquireVsCodeApi?: () => VSCodeApi;
  }
}

/**
 * Gets or initializes the VS Code API instance
 * @returns {VSCodeApi | undefined} The VS Code API instance if in VS Code environment, undefined otherwise
 */
export const getVscodeApi = (): VSCodeApi | undefined => {
  if (window.acquireVsCodeApi) {
    if (vscodeApi === undefined) {
      vscodeApi = window.acquireVsCodeApi();
    }
    return vscodeApi;
  } else {
    return undefined;
  }
};
