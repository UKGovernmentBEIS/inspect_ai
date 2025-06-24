import clsx from "clsx";
import { FC } from "react";
import { MetaDataGrid } from "../content/MetaDataGrid";
import styles from "./DetailStep.module.css";

interface DetailStepProps {
  icon?: string;
  name: string;
  params?: Record<string, unknown>;
  className?: string | string[];
}

export const DetailStep: FC<DetailStepProps> = ({
  icon,
  name,
  params,
  className,
}) => {
  const iconHtml = icon ? <i className={clsx(icon, styles.icon)} /> : "";
  return (
    <div className={clsx(className)}>
      {iconHtml} {name}
      {params && Object.keys(params).length > 0 ? (
        <div className={styles.container}>
          <MetaDataGrid
            entries={params}
            className={clsx("text-size-small", styles.metadata)}
          />
        </div>
      ) : (
        ""
      )}
    </div>
  );
};
