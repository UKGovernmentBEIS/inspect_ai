import "./ProgressBar.css";

interface ProgressBarProps {
  style: Record<string, string>;
  containerStyle: Record<string, string>;
  animating: boolean;
}

export const ProgressBar = (props: ProgressBarProps) => {
  return (
    <div className="progress-bar-wrapper" style={props.style}>
      <div
        className="progress-container"
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow={25}
        aria-valuemin={0}
        aria-valuemax={100}
        style={props.containerStyle}
      >
        {props.animating && (
          <div className="progress-bar-animated" style={props.style} />
        )}
      </div>
    </div>
  );
};
