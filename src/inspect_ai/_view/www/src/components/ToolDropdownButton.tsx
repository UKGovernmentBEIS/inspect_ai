import clsx from "clsx";
import { ButtonHTMLAttributes, forwardRef, ReactNode, useState } from "react";
import styles from "./ToolDropdownButton.module.css";

interface ToolDropdownButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string | ReactNode;
  icon?: string;
  items: Record<string, () => void>;
}

export const ToolDropdownButton = forwardRef<
  HTMLButtonElement,
  ToolDropdownButtonProps
>(({ label, icon, className, items, ...rest }, ref) => {
  const [isOpen, setIsOpen] = useState(false);

  const handleItemClick = (fn: () => void) => {
    fn();
    setIsOpen(false);
  };

  return (
    <div className={styles.dropdownContainer}>
      <button
        ref={ref}
        type="button"
        className={clsx("btn", "btn-tools", styles.toolButton, className)}
        onClick={() => setIsOpen(!isOpen)}
        {...rest}
      >
        {icon && <i className={`${icon}`} />}
        {label}
        <i className={clsx("bi-chevron-down", styles.chevron)} />
      </button>
      {isOpen && (
        <>
          <div className={styles.backdrop} onClick={() => setIsOpen(false)} />
          <div className={styles.dropdownMenu}>
            {Object.entries(items).map(([itemLabel, fn]) => (
              <button
                key={itemLabel}
                type="button"
                className={styles.dropdownItem}
                onClick={() => handleItemClick(fn)}
              >
                {itemLabel}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
});

ToolDropdownButton.displayName = "ToolDropdownButton";
