import clsx from "clsx";
import { CSSProperties, forwardRef } from "react";

import styles from "./Preformatted.module.css";

export interface PreformattedProps {
  text: string;
  style?: CSSProperties;
  className?: string | string[];
}

export const Preformatted = forwardRef<HTMLPreElement, PreformattedProps>(
  ({ text, style, className }, ref) => {
    return (
      <pre
        ref={ref}
        className={clsx(styles.content, "text-size-smaller", className)}
        style={style}
      >
        {text}
      </pre>
    );
  },
);
