import browserApi from "./api-browser.mjs";
import vscodeApi from "./api-vscode.mjs";
import simpleHttpApi from "./api-http.mjs";

export default window.acquireVsCodeApi
  ? vscodeApi
  : simpleHttpApi() || browserApi;
