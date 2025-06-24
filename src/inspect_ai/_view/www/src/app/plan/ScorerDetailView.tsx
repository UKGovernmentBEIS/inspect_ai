import clsx from "clsx";
import { FC } from "react";
import { ApplicationIcons } from "../appearance/icons";
import { DetailStep } from "./DetailStep";
import styles from "./ScorerDetailView.module.css";

interface ScorerDetailViewProps {
  name: string;
  scores: string[];
  params: Record<string, unknown>;
}

export const ScorerDetailView: FC<ScorerDetailViewProps> = ({
  name,
  scores,
  params,
}) => {
  // Merge scores into params
  if (scores.length > 1) {
    params = { ...params, ["scores"]: scores };
  }

  return (
    <DetailStep
      icon={ApplicationIcons.scorer}
      name={name}
      params={params}
      className={clsx(styles.item, "text-size-base")}
    />
  );
};
