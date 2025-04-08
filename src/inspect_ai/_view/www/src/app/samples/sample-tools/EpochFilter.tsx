import clsx from "clsx";
import { ChangeEvent, FC } from "react";
import styles from "./EpochFilter.module.css";

interface EpochFilterProps {
  epochs: number;
  epoch: string;
  setEpoch: (n: string) => void;
}

export const EpochFilter: FC<EpochFilterProps> = ({
  epochs,
  epoch,
  setEpoch,
}) => {
  const options = ["all"];
  for (let i = 1; i <= epochs; i++) {
    options.push(i + "");
  }

  const handleEpochChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const sel = e.target as HTMLSelectElement;
    setEpoch(sel.value);
  };

  return (
    <div className={styles.container}>
      <span
        className={clsx(
          "epoch-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles.label,
        )}
      >
        Epochs:
      </span>
      <select
        className={clsx("form-select", "form-select-sm", "text-size-smaller")}
        aria-label=".epoch-filter-label"
        value={epoch}
        onChange={handleEpochChange}
      >
        {options.map((option) => {
          return <option value={option}>{option}</option>;
        })}
      </select>
    </div>
  );
};
