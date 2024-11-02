//@ts-check
import { html } from "htm/preact";
import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import { SampleDialog } from "./SampleDialog.mjs";
import { SampleList } from "./SampleList.mjs";
import { InlineSampleDisplay } from "./SampleDisplay.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";

/**
 * Renders Samples Tab
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").Sample} [props.sample] - The sample
 * @param {string} [props.task_id] - The task id
 * @param {import("../api/Types.mjs").SampleSummary[]} [props.samples] - the samples
 * @param {import("../Types.mjs").SampleMode} props.sampleMode - the mode for displaying samples
 * @param {"epoch" | "sample" | "none" } props.groupBy - how to group items
 * @param {"asc" | "desc" } props.groupByOrder - whether grouping is ascending or descending
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} [props.sampleDescriptor] - the sample descriptor
 * @param {import("../Types.mjs").ScoreLabel} [props.selectedScore] - the selected score
 * @param {import("../Types.mjs").RenderContext} props.context - the app context
 * @param {string} props.sampleStatus - whether the sample is loading
 * @param {Error} [props.sampleError] - sample error
 * @param {number} props.selectedSampleIndex - the selected sample index
 * @param {(index: number) => void } props.setSelectedSampleIndex - function to select a sample
 * @param {boolean} props.showingSampleDialog - whether the dialog is showing
 * @param {(showing: boolean) => void } props.setShowingSampleDialog - update whether the dialog is showing
 * @param {string} props.selectedSampleTab - the selected tab
 * @param {(tab: string) => void} props.setSelectedSampleTab - function to select a tab
 * @param {string} props.epoch - the selected epoch
 * @param {import("../Types.mjs").ScoreFilter} props.filter - the selected filter
 * @param {any} props.sort - the selected sort
 *
 * @returns {import("preact").JSX.Element[]} The TranscriptView component.
 */
export const SamplesTab = ({
  task_id,
  sample,
  samples,
  sampleMode,
  groupBy,
  groupByOrder,
  sampleDescriptor,
  selectedScore,
  sampleStatus,
  sampleError,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  context,
}) => {
  const [items, setItems] = useState([]);
  const [sampleItems, setSampleItems] = useState([]);

  const sampleListRef = useRef(/** @type {HTMLElement|null} */ (null));
  const sampleDialogRef = useRef(/** @type {HTMLElement|null} */ (null));

  // Shows the sample dialog
  const showSample = useCallback(
    (index) => {
      setSelectedSampleIndex(index);
      setShowingSampleDialog(true);
    },
    [sampleDialogRef],
  );

  useEffect(() => {
    if (showingSampleDialog) {
      setTimeout(() => {
        // @ts-ignore
        sampleDialogRef.current.base.focus();
      }, 0);
    } else {
      setTimeout(() => {
        if (sampleListRef.current) {
          // @ts-ignore
          sampleListRef.current.base.focus();
        }
      }, 0);
    }
  }, [showingSampleDialog]);

  useEffect(() => {
    const sampleProcessor = getSampleProcessor(
      samples,
      groupBy,
      groupByOrder,
      sampleDescriptor,
    );

    // Process the samples into the proper data structure
    const items = samples.flatMap((sample, index) => {
      const results = [];
      const previousSample = index !== 0 ? samples[index - 1] : undefined;
      const items = sampleProcessor(sample, index, previousSample);
      results.push(...items);
      return results;
    });

    setItems(items);
    setSampleItems(
      items.filter((item) => {
        return item.type === "sample";
      }),
    );
  }, [samples, groupBy, groupByOrder, sampleDescriptor]);

  const nextSampleIndex = useCallback(() => {
    if (selectedSampleIndex < sampleItems.length - 1) {
      return selectedSampleIndex + 1;
    } else {
      return -1;
    }
  }, [selectedSampleIndex, items]);

  const previousSampleIndex = useCallback(() => {
    return selectedSampleIndex > 0 ? selectedSampleIndex - 1 : -1;
  }, [selectedSampleIndex, items]);

  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = nextSampleIndex();
    if (sampleStatus !== "loading" && next > -1) {
      setSelectedSampleIndex(next);
    }
  }, [selectedSampleIndex, samples, sampleStatus, nextSampleIndex]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (sampleStatus !== "loading" && prev > -1) {
      setSelectedSampleIndex(prev);
    }
  }, [selectedSampleIndex, samples, sampleStatus, previousSampleIndex]);

  const elements = [];
  if (sampleMode === "single") {
    elements.push(
      html` <${InlineSampleDisplay}
        key=${`${task_id}-single-sample`}
        id="sample-display"
        sample=${sample}
        sampleStatus=${sampleStatus}
        sampleError=${sampleError}
        sampleDescriptor=${sampleDescriptor}
        selectedTab=${selectedSampleTab}
        setSelectedTab=${setSelectedSampleTab}
        context=${context}
      />`,
    );
  } else if (sampleMode === "many") {
    elements.push(
      html`<${SampleList}
        listRef=${sampleListRef}
        items=${items}
        sampleDescriptor=${sampleDescriptor}
        selectedIndex=${selectedSampleIndex}
        setSelectedIndex=${setSelectedSampleIndex}
        selectedScore=${selectedScore}
        nextSample=${nextSample}
        prevSample=${previousSample}
        showSample=${showSample}
      />`,
    );
  } else {
    elements.push(html`<${EmptyPanel} />`);
  }

  const title =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].label
      : "";
  const index =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].index
      : -1;
  elements.push(html`
    <${SampleDialog}
      id=${sample?.id || ""}
      ref=${sampleDialogRef}
      task=${task_id}
      title=${title}
      index=${index}
      sample=${sample}
      sampleStatus=${sampleStatus}
      sampleError=${sampleError}
      sampleDescriptor=${sampleDescriptor}
      showingSampleDialog=${showingSampleDialog}
      setShowingSampleDialog=${setShowingSampleDialog}
      selectedTab=${selectedSampleTab}
      setSelectedTab=${setSelectedSampleTab}
      nextSample=${nextSample}
      prevSample=${previousSample}
      context=${context}
    />
  `);

  return elements;
};

/**
 * @typedef {Object} ListItem
 * @property {string} label - The label for the sample, formatted as "Sample {group} (Epoch {item})".
 * @property {number} number - The current counter item value.
 * @property {number} index - The index of the sample.
 * @property {import("../api/Types.mjs").SampleSummary | string} data - The items data payload.
 * @property {string} type - The type of the result, in this case, "sample". (or "separator")
 */

/**
 * Perform any grouping of the samples
 *
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {"sample" | "epoch" | "none"} groupBy - how to group samples
 * @param {"asc" | "desc"} groupByOrder - how to order grouped samples
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} sampleDescriptor - the sample descriptor
 
 * @returns {(sample: import("../api/Types.mjs").SampleSummary, index: number, previousSample: import("../api/Types.mjs").SampleSummary) => ListItem[]} The list items
 */
const getSampleProcessor = (
  samples,
  groupBy,
  groupByOrder,
  sampleDescriptor,
) => {
  // Perform grouping if there are epochs
  if (groupBy == "epoch") {
    return groupByEpoch(samples, sampleDescriptor, groupByOrder);
  } else if (groupBy === "sample") {
    return groupBySample(samples, sampleDescriptor, groupByOrder);
  } else {
    return noGrouping(samples, groupByOrder);
  }
};

/**
 * Performs no grouping
 *
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {string} order - the selected order
 * @returns {(sample: import("../api/Types.mjs").SampleSummary, index: number, previousSample: import("../api/Types.mjs").SampleSummary) => ListItem[]} The list
 */
const noGrouping = (samples, order) => {
  const counter = getCounter(samples.length, 1, order);
  return (sample, index) => {
    counter.incrementItem();
    const itemCount = counter.item();
    return [
      {
        label: `Sample ${itemCount}`,
        number: itemCount,
        index: index,
        data: sample,
        type: "sample",
      },
    ];
  };
};

/**
 * Groups by sample (showing separators for Epochs)
 *
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {string} order - the selected order
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} sampleDescriptor - the sample descriptor
 * @returns {(sample: import("../api/Types.mjs").SampleSummary, index: number, previousSample: import("../api/Types.mjs").SampleSummary) => ListItem[]} The list
 */
const groupBySample = (samples, sampleDescriptor, order) => {
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
  const groupCount = samples.length / sampleDescriptor.epochs;
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order);
  return (sample, index, previousSample) => {
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
      });
      counter.resetItem();
    }

    counter.incrementItem();
    results.push({
      label: `Sample ${counter.group()} (Epoch ${counter.item()})`,
      number: counter.item(),
      index: index,
      data: sample,
      type: "sample",
    });

    return results;
  };
};

/**
 * Groups by epoch (showing a separator for each sample)
 *
 * @param {import("../api/Types.mjs").SampleSummary[]} samples - the list of sample summaries
 * @param {string} order - the selected order
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} sampleDescriptor - the sample descriptor
 * @returns {(sample: import("../api/Types.mjs").SampleSummary, index: number, previousSample: import("../api/Types.mjs").SampleSummary) => ListItem[]} The list
 */
const groupByEpoch = (samples, sampleDescriptor, order) => {
  const groupCount = sampleDescriptor.epochs;
  const itemCount = samples.length / groupCount;
  const counter = getCounter(itemCount, groupCount, order);

  return (sample, index, previousSample) => {
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
      });
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
    });

    return results;
  };
};

// An order aware counter that hides increment/decrement behavior
const getCounter = (itemCount, groupCount, order) => {
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
