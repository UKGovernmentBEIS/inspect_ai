import { forwardRef, useCallback } from "react";

import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./ViewerOptionsButton.module.css";

export interface ViewerOptionsButtonProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
}

export const ViewerOptionsButton = forwardRef<
  HTMLButtonElement,
  ViewerOptionsButtonProps
>(({ showing, setShowing }, ref) => {
  const toggleShowing = useCallback(() => {
    setShowing(!showing);
  }, [showing, setShowing]);

  return (
    <div>
      <button
        ref={ref}
        type="button"
        className={clsx(styles.button)}
        onClick={toggleShowing}
        title={"Viewer information and options"}
      >
        <i
          ref={ref}
          className={clsx(ApplicationIcons.info, styles.viewerOptions)}
        />
      </button>
    </div>
  );
});
