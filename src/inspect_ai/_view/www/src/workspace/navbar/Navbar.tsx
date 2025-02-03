import clsx from "clsx";
import { SampleSummary } from "../../api/types";
import { EvalDescriptor } from "../../samples/descriptor/types";
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
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  evalDescriptor?: EvalDescriptor;
  samples?: SampleSummary[];
  status?: Status;
  offcanvas: boolean;
  setOffcanvas: (offcanvas: boolean) => void;
  showToggle: boolean;
}

/**
 * Renders the Navbar
 */
export const Navbar: React.FC<NavBarProps> = ({
  file,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  evalDescriptor,
  showToggle,
  offcanvas,
  setOffcanvas,
  status,
}) => {
  return (
    <nav className={clsx("navbar", "sticky-top", styles.navbarWrapper)}>
      <PrimaryBar
        file={file}
        evalSpec={evalSpec}
        evalResults={evalResults}
        samples={samples}
        showToggle={showToggle}
        offcanvas={offcanvas}
        setOffcanvas={setOffcanvas}
        status={status}
      />
      <SecondaryBar
        evalSpec={evalSpec}
        evalPlan={evalPlan}
        evalResults={evalResults}
        evalStats={evalStats}
        samples={samples}
        evalDescriptor={evalDescriptor}
        status={status}
      />
    </nav>
  );
};
