interface LabeledValueProps {
  label: string;
  style: React.CSSProperties;
  valueStyle: React.CSSProperties;
  layout: "column" | "row";
  children: React.ReactNode;
}

export const LabeledValue: React.FC<LabeledValueProps> = ({
  layout,
  style,
  label,
  children,
  valueStyle,
}) => {
  const flexDirection = layout === "column" ? "column" : "row";
  return (
    <div
      className={`labeled-value ${flexDirection}`}
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
