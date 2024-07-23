import browserApi from "./api-browser.mjs";
import vscodeApi from "./api-vscode.mjs";
import singleFileHttpApi from "./api-http.mjs";

export default window.acquireVsCodeApi
  ? vscodeApi
  : singleFileHttpApi() || browserApi;
