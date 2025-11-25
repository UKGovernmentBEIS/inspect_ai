import { FC, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

import clsx from "clsx";
import { useLogs, usePrismHighlight } from "../../state/hooks";
import { useStore } from "../../state/store";
import { dirname } from "../../utils/path";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { logsUrl, samplesUrl, useLogOrSampleRouteParams } from "../routing/url";
import styles from "./FlowPanel.module.css";
import { useFlowServerData } from "./hooks";
export const FlowPanel: FC = () => {
  const location = useLocation();
  const isSamplesRoute = location.pathname.startsWith("/samples/");

  // Get the path from route params (handles both logs and samples context)
  const { logPath: currentPath } = useLogOrSampleRouteParams();
  const flowDir = dirname(currentPath || "");

  // Get the logs from the store
  const { loadLogs } = useLogs();
  useEffect(() => {
    const exec = async () => {
      await loadLogs(flowDir);
    };
    exec();
  }, [loadLogs, flowDir]);

  // Retrieve flow data
  useFlowServerData(flowDir || "");
  const flow = useStore((state) => state.logs.flow);

  // Syntax highlighting
  const codeContainerRef = useRef<HTMLDivElement>(null);
  usePrismHighlight(codeContainerRef, flow?.length || 0);

  // Use the appropriate navigation function based on context
  const fnNavigationUrl = isSamplesRoute ? samplesUrl : logsUrl;

  return (
    <div className={clsx(styles.container)}>
      <ApplicationNavbar
        currentPath={currentPath}
        fnNavigationUrl={fnNavigationUrl}
      />
      <div ref={codeContainerRef} className={clsx(styles.panel)}>
        <pre className={clsx(styles.code)}>
          <code className={clsx("language-yml")}>{flow}</code>
        </pre>
      </div>
    </div>
  );
};
