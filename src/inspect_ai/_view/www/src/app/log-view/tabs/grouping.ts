import { ScoreLabel } from "../../../app/types";
import { SampleSummary } from "../../../client/api/types";
import { SamplesDescriptor } from "../../samples/descriptor/samplesDescriptor";
import { ListItem, SampleListItem, SeparatorListItem } from "./types";

/**
 * Creates a processor that groups samples by sample ID, adding separators between different samples.
 * Used when there are multiple epochs per sample.
 *
 * Assumes samples are already sorted by ID then epoch (done by useFilteredSamples).
 */
export const getSampleProcessor = (
  sampleDescriptor: SamplesDescriptor,
  selectedScores: ScoreLabel[],
): ((
  sample: SampleSummary,
  index: number,
  previousSample?: SampleSummary,
) => ListItem[]) => {
  selectedScores = selectedScores || [];

  let itemIndex = 0;
  let groupIndex = 0;

  return (
    sample: SampleSummary,
    index: number,
    previousSample?: SampleSummary,
  ): ListItem[] => {
    const results: ListItem[] = [];

    // Add a separator when the sample id changes
    const lastId = previousSample ? previousSample.id : undefined;
    if (sample.id !== lastId) {
      groupIndex++;
      results.push({
        label: `Sample ${sample.id}`,
        number: groupIndex,
        index: index,
        data: `Sample ${sample.id}`,
        type: "separator",
      } as SeparatorListItem);
      itemIndex = 0;
    }

    itemIndex++;
    results.push({
      sampleId: sample.id,
      sampleEpoch: sample.epoch,
      label: `Sample ${groupIndex} (Epoch ${itemIndex})`,
      number: itemIndex,
      index: index,
      data: sample,
      type: "sample",
      answer: sampleDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
      scoresRendered: selectedScores.map((sc) =>
        sampleDescriptor.evalDescriptor.score(sample, sc)?.render(),
      ),
      completed: sample.completed !== undefined ? sample.completed : true,
    } as SampleListItem);

    return results;
  };
};
