import { G as useLocation, H as useLogOrSampleRouteParams, g as dirname, u as useStore, j as jsxRuntimeExports, I as samplesUrl, l as logsUrl } from "./index.js";
import { b as reactExports } from "./vendor-grid.js";
import { b as useLogs, W as usePrismHighlight, A as ApplicationNavbar, c as clsx } from "./ApplicationNavbar.js";
import { u as useFlowServerData } from "./hooks.js";
import "./vendor-prism.js";
const container = "_container_ovp9s_1";
const panel = "_panel_ovp9s_7";
const code = "_code_ovp9s_12";
const styles = {
  container,
  panel,
  code
};
const FlowPanel = () => {
  const location = useLocation();
  const isSamplesRoute = location.pathname.startsWith("/samples/");
  const { logPath: currentPath } = useLogOrSampleRouteParams();
  const flowDir = dirname(currentPath || "");
  const { loadLogs } = useLogs();
  reactExports.useEffect(() => {
    loadLogs(flowDir);
  }, [loadLogs, flowDir]);
  useFlowServerData(flowDir || "");
  const flow = useStore((state) => state.logs.flow);
  const codeContainerRef = reactExports.useRef(null);
  usePrismHighlight(codeContainerRef, flow?.length || 0);
  const fnNavigationUrl = isSamplesRoute ? samplesUrl : logsUrl;
  return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: clsx(styles.container), children: [
    /* @__PURE__ */ jsxRuntimeExports.jsx(
      ApplicationNavbar,
      {
        currentPath,
        fnNavigationUrl
      }
    ),
    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { ref: codeContainerRef, className: clsx(styles.panel), children: /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: clsx(styles.code), children: /* @__PURE__ */ jsxRuntimeExports.jsx("code", { className: clsx("language-yml"), children: flow }) }) })
  ] });
};
export {
  FlowPanel
};
//# sourceMappingURL=FlowPanel.js.map
