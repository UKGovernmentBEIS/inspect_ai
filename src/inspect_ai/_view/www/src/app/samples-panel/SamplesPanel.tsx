import clsx from "clsx";

import { FC, useEffect } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogs } from "../../state/hooks";
import { useStore } from "../../state/store";
import { LogListFooter } from "../log-list/LogListFooter";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { ViewSegmentedControl } from "../navbar/ViewSegmentedControl";
import { samplesUrl, useSamplesRouteParams } from "../routing/url";
import { SamplesGrid } from "./samples-grid/SamplesGrid";
import styles from "./SamplesPanel.module.css";

export const SamplesPanel: FC = () => {
  const { samplesPath } = useSamplesRouteParams();
  const { loadLogs } = useLogs();

  const loading = useStore((state) => state.app.status.loading);

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
      <ApplicationNavbar
        currentPath={samplesPath}
        fnNavigationUrl={samplesUrl}
        bordered={false}
      >
        <ViewSegmentedControl selectedSegment="samples" />
      </ApplicationNavbar>

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
