import clsx from "clsx";
import { FC } from "react";

import styles from "./UnscoredSamplesView.module.css";

export interface UnscoredSamplesProps {
  unscoredSamples: number;
  scoredSamples: number;
}

export const UnscoredSamples: FC<UnscoredSamplesProps> = ({
  scoredSamples,
  unscoredSamples,
}) => {
  if (unscoredSamples === 0) {
    return null;
  }
  const msg =
    unscoredSamples === 1
      ? `${unscoredSamples} sample was excluded from this metric because it returned a Nan value.`
      : `${unscoredSamples} samples were excluded from this metric because they returned Nan values.`;

  return (
    <span
      className={clsx("text-style-secondary", styles.unscoredSamples)}
      title={msg}
    >
      ({scoredSamples}/{unscoredSamples + scoredSamples})
    </span>
  );
};
