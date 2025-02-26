import clsx from "clsx";
import { CSSProperties, FC, ReactNode } from "react";

interface LabeledValueProps {
  label: string;
  style?: CSSProperties;
  valueStyle?: CSSProperties;
  layout?: "column" | "row";
  children: ReactNode;
  className?: string | string[];
}

export const LabeledValue: FC<LabeledValueProps> = ({
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
