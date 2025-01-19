import clsx from "clsx";

interface LabeledValueProps {
  label: string;
  style?: React.CSSProperties;
  valueStyle?: React.CSSProperties;
  layout?: "column" | "row";
  children: React.ReactNode;
  className?: string | string[];
}

export const LabeledValue: React.FC<LabeledValueProps> = ({
  layout = "column",
  style,
  label,
  children,
  valueStyle,
  className,
}) => {
  return (
    <div
      className={clsx(
        "labeled-value",
        layout === "column" ? "column" : "row",
        className,
      )}
      style={{
        ...style,
      }}
    >
      <div
        className={"labeled-value-label text-style-label text-style-secondary"}
      >
        {label}
      </div>
      <div className={"labeled-value-value"} style={{ ...valueStyle }}>
        {children}
      </div>
    </div>
  );
};
