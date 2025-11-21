import { FC, useEffect, useRef } from "react";

import clsx from "clsx";
import { useLogs, usePrismHighlight } from "../../state/hooks";
import { useStore } from "../../state/store";
import { join } from "../../utils/uri";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { logsUrl, useLogRouteParams } from "../routing/url";
import styles from "./FlowPanel.module.css";
import { useFlowServerData } from "./hooks";
export const FlowPanel: FC = () => {
  // Get the logPath from route params
  const { logPath } = useLogRouteParams();

  // Get the logs from the store
  const { loadLogs } = useLogs();
  useEffect(() => {
    const exec = async () => {
      await loadLogs(logPath);
    };
    exec();
  }, [loadLogs, logPath]);

  // Retrieve flow data
  useFlowServerData(logPath || "");
  const flow = useStore((state) => state.logs.flow);
  const flowFile = join("flow.yaml", logPath);

  // Syntax highlighting
  const codeContainerRef = useRef<HTMLDivElement>(null);
  usePrismHighlight(codeContainerRef, flow?.length || 0);

  return (
    <div className={clsx(styles.container)}>
      <ApplicationNavbar currentPath={flowFile} fnNavigationUrl={logsUrl} />
      <div ref={codeContainerRef} className={clsx(styles.panel)}>
        <pre>
          <code className={clsx("language-yml")}>{flow}</code>
        </pre>
      </div>
    </div>
  );
};
