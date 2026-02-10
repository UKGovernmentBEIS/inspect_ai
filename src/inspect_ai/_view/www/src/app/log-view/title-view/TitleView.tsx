import clsx from "clsx";
import { FC } from "react";
import {
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
  Status,
} from "../../../@types/log";
import { useTotalSampleCount } from "../../../state/hooks";
import { PrimaryBar } from "./PrimaryBar";
import { SecondaryBar } from "./SecondaryBar";
import styles from "./TitleView.module.css";

interface TitleViewProps {
  evalSpec?: EvalSpec;
  evalResults?: EvalResults | null;
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  status?: Status;
}

/**
 * Renders the Navbar
 */
export const TitleView: FC<TitleViewProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  status,
}) => {
  const totalSampleCount = useTotalSampleCount();

  return (
    <nav className={clsx("navbar", "sticky-top", styles.navbarWrapper)}>
      <PrimaryBar
        evalSpec={evalSpec}
        evalResults={evalResults}
        status={status}
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
