import { FC } from "react";

import styles from "./EmptyCell.module.css";

export const EmptyCell: FC = () => {
  return <div className={styles.emptyCell}>-</div>;
};
