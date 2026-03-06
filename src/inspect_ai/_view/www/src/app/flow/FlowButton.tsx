import { forwardRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import { useLogOrSampleRouteParams } from "../routing/url";
import styles from "./FlowButton.module.css";

export interface FlowButtonProps {}

export const FlowButton = forwardRef<HTMLButtonElement, FlowButtonProps>(
  (_, ref) => {
    const navigateRouter = useNavigate();
    const location = useLocation();
    const { logPath } = useLogOrSampleRouteParams();

    const navigate = () => {
      // Navigate to flow.yaml in the current directory
      // Preserve whether we're in /samples or /logs context
      const isSamplesRoute = location.pathname.startsWith("/samples/");
      const routePrefix = isSamplesRoute ? "/samples" : "/logs";

      const flowPath = logPath
        ? `${routePrefix}/${logPath}/flow.yaml`
        : `${routePrefix}/flow.yaml`;
      navigateRouter(flowPath);
    };

    return (
      <div>
        <button
          ref={ref}
          type="button"
          className={clsx(styles.button)}
          onClick={navigate}
          title={"View Flow configuration for this directory"}
        >
          <i
            ref={ref}
            className={clsx(ApplicationIcons.flow, styles.viewerOptions)}
          />
        </button>
      </div>
    );
  },
);
