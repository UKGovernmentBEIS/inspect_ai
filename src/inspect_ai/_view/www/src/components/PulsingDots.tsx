import styles from "./PulsingDots.module.css";

export const PulsingDots = ({ text = "Loading...", dotsCount = 3 }) => {
  return (
    <div className={styles.container} role="status">
      <div className={styles.dotsContainer}>
        {[...Array(dotsCount)].map((_, index) => (
          <div
            key={index}
            className={styles.dot}
            style={{ animationDelay: `${index * 0.15}s` }}
          />
        ))}
      </div>
      <span className={styles.visuallyHidden}>{text}</span>
    </div>
  );
};
