import clsx from "clsx";
import { FC, Fragment } from "react";
import { Steps } from "../../@types/log";
import { ApplicationIcons } from "../appearance/icons";
import { DetailStep } from "./DetailStep";
import styles from "./SolverDetailView.module.css";

interface SolversDetailViewProps {
  steps: Steps;
}

export const SolversDetailView: FC<SolversDetailViewProps> = ({ steps }) => {
  const separator = (
    <div className={clsx(styles.items, "text-size-small", styles.separator)}>
      <i className={ApplicationIcons.arrows.right} />
    </div>
  );

  const details = steps?.map((step, index) => {
    return (
      <Fragment key={`solver-step-${index}`}>
        <DetailStep
          name={step.solver}
          className={clsx(styles.items, "text-size-small")}
        />
        {index < steps.length - 1 ? separator : ""}
      </Fragment>
    );
  });

  return <div className={styles.container}>{details}</div>;
};
