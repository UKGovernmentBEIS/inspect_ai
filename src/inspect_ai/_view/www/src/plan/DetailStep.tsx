import clsx from "clsx";
import { MetaDataView } from "../metadata/MetaDataView";
import styles from "./DatasetDetailView.module.css";

interface DetailStepProps {
  icon?: string;
  name: string;
  params?: Record<string, unknown>;
  className?: string | string[];
}

export const DetailStep: React.FC<DetailStepProps> = ({
  icon,
  name,
  params,
  className,
}) => {
  const iconHtml = icon ? <i className={clsx(icon, styles.icon)} /> : "";
  return (
    <div className={clsx(className)}>
      {iconHtml} {name}
      <div className={styles.container}>
        {params ? (
          <MetaDataView entries={params} className={"text-size-small"} />
        ) : (
          ""
        )}
      </div>
    </div>
  );
};
