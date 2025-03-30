import { ButtonHTMLAttributes, forwardRef, ReactNode } from "react";
import "./ToolButton.css";

interface ToolButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string | ReactNode;
  classes?: string;
  icon?: string;
}

export const ToolButton = forwardRef<HTMLButtonElement, ToolButtonProps>(
  ({ label, classes = "", icon, className, ...rest }, ref) => {
    // Combine class names, ensuring default classes are applied first
    const combinedClasses =
      `btn btn-tools tool-button ${classes} ${className || ""}`.trim();

    return (
      <button ref={ref} type="button" className={combinedClasses} {...rest}>
        {icon && <i className={`${icon}`} />}
        {label}
      </button>
    );
  },
);

// Add display name for debugging purposes
ToolButton.displayName = "ToolButton";
