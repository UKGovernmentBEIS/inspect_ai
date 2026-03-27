import { FC } from "react";
import { EvalSample } from "../../@types/log";
import { JSONPanel } from "../../components/JsonPanel";
import { NoContentsPanel } from "../../components/NoContentsPanel";
import { estimateSize } from "../../utils/json";

const MAX_JSON_DISPLAY_SIZE = 25 * 1024 * 1024;

interface SampleJSONViewProps {
  sample: EvalSample;
  className?: string;
}

export const SampleJSONView: FC<SampleJSONViewProps> = ({
  sample,
  className,
}) => {
  return estimateSize(sample.events) > MAX_JSON_DISPLAY_SIZE ? (
    <NoContentsPanel text="JSON too large to display" />
  ) : (
    <JSONPanel data={sample} simple={true} className={className} />
  );
};
