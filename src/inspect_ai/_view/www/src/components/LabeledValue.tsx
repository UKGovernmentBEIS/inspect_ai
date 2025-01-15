interface LabeledValueProps {
  label: string;
  style: Record<string, string>;
  valueStyle: Record<string, string>;
  layout: "column" | "row";
  children: React.ReactNode;
}

export const LabeledValue = (props: LabeledValueProps) => {
  const flexDirection = props.layout === "column" ? "column" : "row";
  return (
    <div
      className={`labeled-value ${flexDirection}`}
      style={{
        ...props.style,
      }}
    >
      <div
        className={"labeled-value-label text-style-label text-style-secondary"}
      >
        {props.label}
      </div>
      <div className={"labeled-value-value"} style={{ ...props.valueStyle }}>
        {props.children}
      </div>
    </div>
  );
};
