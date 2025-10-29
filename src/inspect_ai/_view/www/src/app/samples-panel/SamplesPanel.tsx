import clsx from "clsx";

import { FC, useEffect, useRef } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogs } from "../../state/hooks";
import { useStore } from "../../state/store";
import { LogListFooter } from "../log-list/LogListFooter";
import { ViewerOptionsButton } from "../log-list/ViewerOptionsButton";
import { ViewerOptionsPopover } from "../log-list/ViewerOptionsPopover";
import { Navbar } from "../navbar/Navbar";
import { ViewSegmentedControl } from "../navbar/ViewSegmentedControl";
import { samplesUrl, useSamplesRouteParams } from "../routing/url";
import { SamplesGrid } from "./samples-grid/SamplesGrid";
import styles from "./SamplesPanel.module.css";

export const SamplesPanel: FC = () => {
  const { samplesPath } = useSamplesRouteParams();
  const { loadLogs } = useLogs();

  const optionsRef = useRef<HTMLButtonElement>(null);
  const loading = useStore((state) => state.app.status.loading);

  const isShowing = useStore((state) => state.app.dialogs.options);
  const setShowing = useStore(
    (state) => state.appActions.setShowingOptionsDialog,
  );

  const filteredSamplesCount = useStore(
    (state) => state.log.filteredSampleCount,
  );

  useEffect(() => {
    const exec = async () => {
      await loadLogs(samplesPath);
    };
    exec();
  }, [loadLogs, samplesPath]);

  return (
    <div className={clsx(styles.panel)}>
      <Navbar
        bordered={false}
        fnNavigationUrl={samplesUrl}
        currentPath={samplesPath}
      >
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
        <SamplesGrid samplesPath={samplesPath} />
      </div>

      <LogListFooter
        id={"samples-list-footer"}
        itemCount={filteredSamplesCount ?? 0}
        paginated={false}
      />
    </div>
  );
};
