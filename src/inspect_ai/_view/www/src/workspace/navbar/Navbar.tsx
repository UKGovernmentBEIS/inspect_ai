import clsx from "clsx";
import { FC } from "react";
import { RunningMetric } from "../../api/types";
import { useTotalSampleCount } from "../../state/hooks";
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
  evalSpec?: EvalSpec;
  evalResults?: EvalResults;
  runningMetrics?: RunningMetric[];
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  status?: Status;
  showToggle: boolean;
}

/**
 * Renders the Navbar
 */
export const Navbar: FC<NavBarProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  showToggle,
  status,
  runningMetrics,
}) => {
  const totalSampleCount = useTotalSampleCount();
  return (
    <nav className={clsx("navbar", "sticky-top", styles.navbarWrapper)}>
      <PrimaryBar
        evalSpec={evalSpec}
        evalResults={evalResults}
        showToggle={showToggle}
        status={status}
        runningMetrics={runningMetrics}
        sampleCount={totalSampleCount}
      />
      <SecondaryBar
        evalSpec={evalSpec}
        evalPlan={evalPlan}
        evalResults={evalResults}
        evalStats={evalStats}
        status={status}
        sampleCount={totalSampleCount}
      />
    </nav>
  );
};
