import clsx from "clsx";
import { MetaDataView } from "../metadata/MetaDataView";
import { EvalDataset } from "../types/log";

import styles from "./DatasetDetailView.module.css";

interface DatasetDetailViewProps {
  dataset: EvalDataset;
  style?: React.CSSProperties;
}

export const DatasetDetailView: React.FC<DatasetDetailViewProps> = ({
  dataset,
  style,
}) => {
  // Filter out sample_ids
  const filtered = Object.fromEntries(
    Object.entries(dataset).filter(([key]) => key !== "sample_ids"),
  );

  if (!dataset || Object.keys(filtered).length === 0) {
    return (
      <span className={clsx("text-size-base", styles.item)} style={style}>
        No dataset information available
      </span>
    );
  }

  return (
    <MetaDataView
      className={clsx("text-size-base", styles.item)}
      entries={filtered}
      tableOptions="borderless,sm"
      style={style}
    />
  );
};
