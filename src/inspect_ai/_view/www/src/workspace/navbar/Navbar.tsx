import clsx from "clsx";
import { FC } from "react";
import { RunningMetric, SampleSummary } from "../../api/types";
import {
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
  Status,
} from "../../types/log";
import styles from "./Navbar.module.css";
import { PrimaryBar } from "./PrimaryBar";
import { SecondaryBar } from "./SecondaryBar";

interface NavBarProps {
  file?: string;
  evalSpec?: EvalSpec;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  samples?: SampleSummary[];
  status?: Status;
  showToggle: boolean;
}

/**
 * Renders the Navbar
 */
export const Navbar: FC<NavBarProps> = ({
  file,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  showToggle,
  status,
  runningMetrics,
}) => {
  return (
    <nav className={clsx("navbar", "sticky-top", styles.navbarWrapper)}>
      <PrimaryBar
        file={file}
        evalSpec={evalSpec}
        evalResults={evalResults}
        samples={samples}
        showToggle={showToggle}
        status={status}
        runningMetrics={runningMetrics}
      />
      <SecondaryBar
        evalSpec={evalSpec}
        evalPlan={evalPlan}
        evalResults={evalResults}
        evalStats={evalStats}
        samples={samples}
        status={status}
      />
    </nav>
  );
};
