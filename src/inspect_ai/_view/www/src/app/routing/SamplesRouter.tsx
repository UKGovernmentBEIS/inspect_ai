import { FC } from "react";
import { SamplesPanel } from "../samples-panel/SamplesPanel";
import { SampleDetailView } from "../samples-panel/SampleDetailView";
import { useSamplesRouteParams } from "./url";

/**
 * Router component that determines whether to show the samples grid or sample detail view
 * based on the URL parameters.
 */
export const SamplesRouter: FC = () => {
  const { sampleId, epoch } = useSamplesRouteParams();

  // If we have both sampleId and epoch, show the detail view
  if (sampleId && epoch) {
    return <SampleDetailView />;
  }

  // Otherwise show the samples grid
  return <SamplesPanel />;
};
