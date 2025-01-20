import "./ProgressBar.css";

interface ProgressBarProps {
  style?: React.CSSProperties;
  containerStyle?: React.CSSProperties;
  animating: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  style,
  containerStyle,
  animating,
}) => {
  return (
    <div className="progress-bar-wrapper" style={style}>
      <div
        className="progress-container"
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow={25}
        aria-valuemin={0}
        aria-valuemax={100}
        style={containerStyle}
      >
        {animating && <div className="progress-bar-animated" style={style} />}
      </div>
    </div>
  );
};
