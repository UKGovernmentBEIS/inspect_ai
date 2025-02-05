interface SampleFooterProps {
  sampleCount: number;
}

import clsx from "clsx";
import styles from "./SampleFooter.module.css";

export const SampleFooter: React.FC<SampleFooterProps> = ({ sampleCount }) => {
  return (
    <div className={clsx("text-size-smaller", styles.footer)}>
      <div>{sampleCount} Samples</div>
    </div>
  );
};
