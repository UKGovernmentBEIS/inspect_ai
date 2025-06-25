import { ChangeEvent, forwardRef } from "react";

import clsx from "clsx";
import { ApplicationIcons } from "../app/appearance/icons";
import styles from "./TextInput.module.css";

export interface TextInputProps {
  value?: string;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  icon?: string;
  placeholder?: string;
  className?: string | string[];
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  ({ value, onChange, icon, placeholder, className }, ref) => {
    return (
      <div
        className={clsx(
          styles.container,
          className,
          icon ? styles.withIcon : "",
        )}
      >
        {icon && <i className={clsx(icon, styles.icon)} />}
        <input
          type="text"
          value={value}
          onChange={onChange}
          ref={ref}
          placeholder={placeholder}
          className={clsx(styles.input)}
        />
        <i
          className={clsx(
            styles.clearText,
            value === "" ? styles.hidden : "",
            ApplicationIcons["clear-text"],
          )}
          onClick={() => {
            if (onChange && value !== "") {
              onChange({
                target: { value: "" },
              } as ChangeEvent<HTMLInputElement>);
            }
          }}
          role="button"
        />
      </div>
    );
  },
);
