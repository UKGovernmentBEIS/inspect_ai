import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./DatasetDetailView.module.css";
import { DetailStep } from "./DetailStep";

interface ScorerDetailViewProps {
  name: string;
  scores: string[];
  params: Record<string, unknown>;
}

export const ScorerDetailView: React.FC<ScorerDetailViewProps> = ({
  name,
  scores,
  params,
}) => {
  // Merge scores into params
  if (scores.length > 1) {
    params["scores"] = scores;
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
