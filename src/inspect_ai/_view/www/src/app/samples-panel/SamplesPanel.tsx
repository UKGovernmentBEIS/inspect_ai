import clsx from "clsx";

import { FC, useEffect, useRef } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogs } from "../../state/hooks";
import { useStore } from "../../state/store";
import { ViewerOptionsButton } from "../log-list/ViewerOptionsButton";
import { ViewerOptionsPopover } from "../log-list/ViewerOptionsPopover";
import { Navbar } from "../navbar/Navbar";
import { ViewSegmentedControl } from "../navbar/ViewSegmentedControl";
import { useLogRouteParams } from "../routing/url";
import { SamplesGrid } from "./samples-grid/SamplesGrid";
import styles from "./SamplesPanel.module.css";

export const SamplesPanel: FC = () => {
  const { logPath } = useLogRouteParams();
  const { loadLogs } = useLogs();

  const optionsRef = useRef<HTMLButtonElement>(null);
  const loading = useStore((state) => state.app.status.loading);

  const isShowing = useStore((state) => state.app.dialogs.options);
  const setShowing = useStore(
    (state) => state.appActions.setShowingOptionsDialog,
  );

  useEffect(() => {
    const exec = async () => {
      await loadLogs(logPath);
    };
    exec();
  }, [loadLogs, logPath]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar bordered={false}>
        <ViewSegmentedControl selectedSegment="samples" />
        <ViewerOptionsButton
          showing={isShowing}
          setShowing={setShowing}
          ref={optionsRef}
        />
        <ViewerOptionsPopover
          positionEl={optionsRef.current}
          showing={isShowing}
          setShowing={setShowing}
        />
      </Navbar>

      <ActivityBar animating={!!loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <SamplesGrid />
      </div>
    </div>
  );
};
