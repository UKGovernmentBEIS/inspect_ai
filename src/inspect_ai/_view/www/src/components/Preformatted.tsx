import clsx from "clsx";
import { FC } from "react";

import styles from "./Preformatted.module.css";

export interface PreformattedProps {
  text: string;
}

export const Preformatted: FC<PreformattedProps> = ({ text }) => {
  return (
    <pre className={clsx(styles.content, "text-size-smallest")}>{text}</pre>
  );
};
