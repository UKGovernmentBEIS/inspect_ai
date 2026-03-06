import clsx from "clsx";
import { ButtonHTMLAttributes, forwardRef, ReactNode } from "react";
import styles from "./ToolButton.module.css";

interface ToolButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string | ReactNode;
  classes?: string;
  icon?: string;
  latched?: boolean;
}

export const ToolButton = forwardRef<HTMLButtonElement, ToolButtonProps>(
  ({ label, classes = "", icon, className, latched, ...rest }, ref) => {
    // Combine class names, ensuring default classes are applied first

    return (
      <button
        ref={ref}
        type="button"
        className={clsx(
          "btn",
          "btn-tools",
          styles.toolButton,
          classes,
          className,
          latched ? styles.latched : undefined,
        )}
        {...rest}
      >
        {icon && <i className={`${icon}`} />}
        {label}
      </button>
    );
  },
);

// Add display name for debugging purposes
ToolButton.displayName = "ToolButton";
