import { FC } from "react";
import { FlowPanel } from "../flow/FlowPanel";
import { SamplesPanel } from "../samples-panel/SamplesPanel";
import { SampleDetailView } from "../samples-panel/SampleDetailView";
import { useSamplesRouteParams } from "./url";

/**
 * Router component that determines whether to show the flow panel, samples grid, or sample detail view
 * based on the URL parameters. If the path ends with .yaml/.yml, it shows the FlowPanel.
 */
export const SamplesRouter: FC = () => {
  const { samplesPath, sampleId, epoch } = useSamplesRouteParams();

  // Check if the path ends with .yaml or .yml (indicating it's a flow file)
  if (samplesPath) {
    const isFlowFile =
      samplesPath.endsWith(".yaml") || samplesPath.endsWith(".yml");

    // If it's a flow file, show the FlowPanel
    if (isFlowFile) {
      return <FlowPanel />;
    }
  }

  // If we have both sampleId and epoch, show the detail view
  if (sampleId && epoch) {
    return <SampleDetailView />;
  }

  // Otherwise show the samples grid
  return <SamplesPanel />;
};
