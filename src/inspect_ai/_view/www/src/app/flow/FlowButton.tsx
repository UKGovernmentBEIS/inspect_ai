import { forwardRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./FlowButton.module.css";

export interface FlowButtonProps {}

export const FlowButton = forwardRef<HTMLButtonElement, FlowButtonProps>(
  (_, ref) => {
    const navigateRouter = useNavigate();
    const location = useLocation();

    const navigate = () => {
      // Navigate to the current logs url with the ?flow parameter
      const searchParams = new URLSearchParams(location.search);
      searchParams.set("flow", "");
      navigateRouter(`${location.pathname}?${searchParams.toString()}`);
    };

    return (
      <div>
        <button
          ref={ref}
          type="button"
          className={clsx(styles.button)}
          onClick={navigate}
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
