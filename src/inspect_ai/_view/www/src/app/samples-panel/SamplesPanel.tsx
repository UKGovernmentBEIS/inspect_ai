import clsx from "clsx";

import { AgGridReact } from "ag-grid-react";
import { FC, useEffect, useRef } from "react";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogs } from "../../state/hooks";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import { LogListFooter } from "../log-list/LogListFooter";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { NavbarButton } from "../navbar/NavbarButton";
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

  const gridRef = useRef<AgGridReact>(null);

  const handleResetFilters = () => {
    if (gridRef.current?.api) {
      console.log("Resetting filters");
      gridRef.current.api.setFilterModel(null);
    }
  };

  useEffect(() => {
    const exec = async () => {
      await loadLogs(samplesPath);
    };
    exec();
  }, [loadLogs, samplesPath]);

  const filterModel = gridRef.current?.api?.getFilterModel();
  const hasFilter = filterModel && Object.keys(filterModel).length > 0;

  return (
    <div className={clsx(styles.panel)}>
      <ApplicationNavbar currentPath={samplesPath} fnNavigationUrl={samplesUrl}>
        {hasFilter && (
          <NavbarButton
            key="reset-filters"
            label="Reset Filters"
            icon={ApplicationIcons.filter}
            onClick={handleResetFilters}
          />
        )}

        <ViewSegmentedControl selectedSegment="samples" />
      </ApplicationNavbar>

      <ActivityBar animating={!!loading} />
      <div className={clsx(styles.list, "text-size-smaller")}>
        <SamplesGrid samplesPath={samplesPath} gridRef={gridRef} />
      </div>

      <LogListFooter
        id={"samples-list-footer"}
        itemCount={filteredSamplesCount ?? 0}
        paginated={false}
      />
    </div>
  );
};
