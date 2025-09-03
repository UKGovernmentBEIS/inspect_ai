import clsx from "clsx";
import { CSSProperties, FC } from "react";

import styles from "./Preformatted.module.css";

export interface PreformattedProps {
  text: string;
  style?: CSSProperties;
  className?: string | string[];
}

export const Preformatted: FC<PreformattedProps> = ({
  text,
  style,
  className,
}) => {
  return (
    <pre
      className={clsx(styles.content, "text-size-smaller", className)}
      style={style}
    >
      {text}
    </pre>
  );
};
