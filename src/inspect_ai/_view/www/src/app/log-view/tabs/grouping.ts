import { Epochs } from "../../../@types/log";
import { ScoreLabel } from "../../../app/types";
import { SampleSummary } from "../../../client/api/types";
import { SamplesDescriptor } from "../../samples/descriptor/samplesDescriptor";
import { ListItem, SampleListItem, SeparatorListItem } from "./types";

export const getSampleProcessor = (
  samples: SampleSummary[],
  epochs: Epochs,
  groupBy: "sample" | "epoch" | "none",
  groupByOrder: "asc" | "desc",
  sampleDescriptor: SamplesDescriptor,
  score?: ScoreLabel,
): ((
  sample: SampleSummary,
  index: number,
  previousSample?: SampleSummary,
) => ListItem[]) => {
  // Perform grouping if there are epochs
  if (groupBy == "epoch") {
    return groupByEpoch(samples, epochs, sampleDescriptor, groupByOrder, score);
  } else if (groupBy === "sample") {
    return groupBySample(
      samples,
      epochs,
      sampleDescriptor,
      groupByOrder,
      score,
    );
  } else {
    return noGrouping(samples, groupByOrder, sampleDescriptor, score);
  }
};

/**
 * Performs no grouping
 */
const noGrouping = (
  samples: SampleSummary[],
  order: "asc" | "desc",
  sampleDescriptor: SamplesDescriptor,
  score?: ScoreLabel,
): ((sample: SampleSummary, index: number) => ListItem[]) => {
  const counter = getCounter(samples.length, 1, order);
  return (sample: SampleSummary, index: number) => {
    counter.incrementItem();
    const itemCount = counter.item();
    return [
      {
        label: `Sample ${itemCount}`,
        number: itemCount,
        index: index,
        data: sample,
        type: "sample",
        answer:
          sampleDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
        scoreRendered: sampleDescriptor.evalDescriptor
          .score(sample, score)
          ?.render(),
        completed: sample.completed !== undefined ? sample.completed : true,
      },
    ];
  };
};

/**
 * Groups by sample (showing separators for Epochs)
 */
const groupBySample = (
  samples: SampleSummary[],
  epochs: Epochs,
  sampleDescriptor: SamplesDescriptor,
  order: "asc" | "desc",
  score?: ScoreLabel,
): ((
  sample: SampleSummary,
  index: number,
  previousSample?: SampleSummary,
) => ListItem[]) => {
  // ensure that we are sorted by id
  samples = samples.sort((a, b) => {
    if (typeof a.id === "string") {
      if (order === "asc") {
        return String(a.id).localeCompare(String(b.id));
      } else {
        return String(b.id).localeCompare(String(a.id));
      }
    } else {
      if (order === "asc") {
        return Number(a.id) - Number(b.id);
      } else {
        return Number(b.id) - Number(b.id);
      }
    }
  });
  const groupCount = samples.length / (epochs || 1);
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order);
  return (
    sample: SampleSummary,
    index: number,
    previousSample?: SampleSummary,
  ): ListItem[] => {
    const results = [];
    // Add a separator when the id changes
    const lastId = previousSample ? previousSample.id : undefined;
    if (sample.id !== lastId) {
      counter.incrementGroup();
      results.push({
        label: `Sample ${itemCount}`,
        number: counter.group(),
        index: index,
        data: `Sample ${counter.group()}`,
        type: "separator",
      } as SeparatorListItem);
      counter.resetItem();
    }

    counter.incrementItem();
    results.push({
      label: `Sample ${counter.group()} (Epoch ${counter.item()})`,
      number: counter.item(),
      index: index,
      data: sample,
      type: "sample",
      answer: sampleDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
      scoreRendered: sampleDescriptor.evalDescriptor
        .score(sample, score)
        ?.render(),
      completed: sample.completed !== undefined ? sample.completed : true,
    } as SampleListItem);

    return results;
  };
};

/**
 * Groups by epoch (showing a separator for each sample)
 */
const groupByEpoch = (
  samples: SampleSummary[],
  epochs: Epochs,
  sampleDescriptor: SamplesDescriptor,
  order: "asc" | "desc",
  score?: ScoreLabel,
): ((
  sample: SampleSummary,
  index: number,
  previousSample?: SampleSummary,
) => ListItem[]) => {
  const groupCount = epochs || 1;
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order);

  return (
    sample: SampleSummary,
    index: number,
    previousSample?: SampleSummary,
  ) => {
    const results = [];
    const lastEpoch = previousSample ? previousSample.epoch : -1;
    if (lastEpoch !== sample.epoch) {
      counter.incrementGroup();
      // Add a separator
      results.push({
        label: `Epoch ${counter.group()}`,
        number: counter.group(),
        index: index,
        data: `Epoch ${counter.group()}`,
        type: "separator",
      } as SeparatorListItem);
      counter.resetItem();
    }

    // Compute the index within the epoch
    counter.incrementItem();
    results.push({
      label: `Sample ${counter.item()} (Epoch ${counter.group()})`,
      number: counter.item(),
      index: index,
      data: sample,
      type: "sample",
      answer: sampleDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
      scoreRendered: sampleDescriptor.evalDescriptor
        .score(sample, score)
        ?.render(),
      completed: sample.completed !== undefined ? sample.completed : true,
    } as SampleListItem);

    return results;
  };
};

// An order aware counter that hides increment/decrement behavior
const getCounter = (
  itemCount: number,
  groupCount: number,
  order: "asc" | "desc",
) => {
  let itemIndex = order !== "desc" ? 0 : itemCount + 1;
  let groupIndex = order !== "desc" ? 0 : groupCount + 1;
  return {
    resetItem: () => {
      itemIndex = order !== "desc" ? 0 : itemCount + 1;
    },
    incrementItem: () => {
      if (order !== "desc") {
        itemIndex++;
      } else {
        itemIndex--;
      }
    },
    incrementGroup: () => {
      if (order !== "desc") {
        groupIndex++;
      } else {
        groupIndex--;
      }
    },
    item: () => {
      return itemIndex;
    },
    group: () => {
      return groupIndex;
    },
  };
};
