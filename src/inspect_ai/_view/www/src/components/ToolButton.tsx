// ToolButton.tsx
import React from "react";
import "./ToolButton.css";

interface ToolButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  name: string;
  classes?: string;
  icon?: string;
}

export const ToolButton = React.forwardRef<HTMLButtonElement, ToolButtonProps>(
  ({ name, classes = "", icon, className, ...rest }, ref) => {
    // Combine class names, ensuring default classes are applied first
    const combinedClasses =
      `btn btn-tools tool-button ${classes} ${className || ""}`.trim();

    return (
      <button ref={ref} type="button" className={combinedClasses} {...rest}>
        {icon && <i className={`${icon}`} />}
        {name}
      </button>
    );
  },
);

// Add display name for debugging purposes
ToolButton.displayName = "ToolButton";
