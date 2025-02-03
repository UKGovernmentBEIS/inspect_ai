import styles from "./ProgressBar.module.css";

interface ProgressBarProps {
  animating: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ animating }) => {
  return (
    <div className={styles.wrapper}>
      <div
        className={styles.container}
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow={25}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {animating && <div className={styles.animate} />}
      </div>
    </div>
  );
};
