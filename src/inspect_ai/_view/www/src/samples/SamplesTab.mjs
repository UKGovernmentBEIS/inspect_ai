import { html } from "htm/preact";
import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import { byEpoch, bySample, sort as doSort } from "./tools/SortFilter.mjs";
import { SampleDialog } from "./SampleDialog.mjs";
import { SampleList } from "./SampleList.mjs";
import { InlineSampleDisplay } from "./SampleDisplay.mjs";

export const SamplesTab = (props) => {
  const {
    task,
    model,
    samples,
    sampleDescriptor,
    filter,
    sort,
    epoch,
    context,
    selectedScore,
    //setSelectedScore,
  } = props;

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [filteredSamples, setFilteredSamples] = useState([]);
  const [items, setItems] = useState([]);

  const sampleListRef = useRef(/** @type {HTMLElement|null} */ (null));
  const sampleDialogRef = useRef(/** @type {HTMLElement|null} */ (null));
  const [sampleDialogVisible, setSampleDialogVisible] = useState(false);

  // Re-filter the samples
  useEffect(() => {
    setFilteredSamples(
      (samples || []).filter((sample) => {
        // Filter by epoch if specified
        if (epoch && epoch !== "all") {
          if (epoch !== sample.epoch + "") {
            return false;
          }
        }

        if (filter.filterFn && filter.value) {
          return filter.filterFn(sample, filter.value);
        } else {
          return true;
        }
      }),
    );
  }, [samples, filter, sort, epoch]);

  // Shows the sample dialog
  const showSample = useCallback(() => {
    setSampleDialogVisible(true);
    setTimeout(() => {
      sampleDialogRef.current.base.focus();
    }, 0);
  }, [setSampleDialogVisible, sampleDialogRef]);

  const hideSample = useCallback(() => {
    setSampleDialogVisible(false);
  }, [setSampleDialogVisible]);

  useEffect(() => {
    // Sort the samples
    const { sorted, order } = doSort(sort, filteredSamples, sampleDescriptor);

    const sampleProcessor = getSampleProcessor(
      filteredSamples,
      sort,
      epoch,
      order,
      sampleDescriptor,
    );

    // Process the samples into the proper data structure
    const items = sorted.flatMap((sample, index) => {
      const results = [];
      const previousSample = index !== 0 ? sorted[index - 1] : undefined;
      const items = sampleProcessor(sample, index, previousSample);
      results.push(...items);
      return results;
    });

    setItems(items);
    const firstSample = items.findIndex((val) => {
      return val.type === "sample";
    });
    if (items.length) {
      setSelectedIndex(firstSample);
    }

    return items;
  }, [filteredSamples, sort, epoch, sampleDescriptor]);

  // Focus the sample list
  useEffect(() => {
    // Hide a dialog, if it is displaying
    hideSample();
  }, [items]);

  const nextSampleIndex = useCallback(() => {
    for (let i = selectedIndex + 1; i < items.length; i++) {
      if (items[i].type === "sample") {
        return i;
      }
    }
    return -1;
  }, [selectedIndex, items]);

  const previousSampleIndex = useCallback(() => {
    for (let i = selectedIndex - 1; i >= 0; i--) {
      if (items[i].type === "sample") {
        return i;
      }
    }
    return -1;
  }, [selectedIndex, items]);

  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = nextSampleIndex();
    if (next > -1) {
      setSelectedIndex(next);
    }
  }, [selectedIndex, filteredSamples, nextSampleIndex]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (prev > -1) {
      setSelectedIndex(prev);
    }
  }, [selectedIndex, filteredSamples, previousSampleIndex]);

  const elements = [];
  if (samples?.length === 1 && items.length === 1) {
    elements.push(
      html` <${InlineSampleDisplay}
        index="0"
        key=${`${task}-single-sample`}
        id="sample-display"
        sample=${samples[0]}
        sampleDescriptor=${sampleDescriptor}
        context=${context}
      />`,
    );
  } else {
    elements.push(
      html`<${SampleList}
        listRef=${sampleListRef}
        items=${items}
        sampleDescriptor=${sampleDescriptor}
        selectedIndex=${selectedIndex}
        setSelectedIndex=${setSelectedIndex}
        selectedScore=${selectedScore}
        nextSample=${nextSample}
        prevSample=${previousSample}
        showSample=${showSample}
      />`,
    );
  }

  elements.push(html`
    <${SampleDialog}
      ref=${sampleDialogRef}
      task=${task}
      model=${model}
      title=${items.length > 0 ? items[selectedIndex].label : undefined}
      index=${items.length > 0 ? items[selectedIndex].number : undefined}
      sample=${items.length > 0 ? items[selectedIndex].data : undefined}
      sampleDescriptor=${sampleDescriptor}
      nextSample=${nextSample}
      prevSample=${previousSample}
      sampleDialogVisible=${sampleDialogVisible}
      hideSample=${hideSample}
      context=${context}
    />
  `);

  return elements;
};

// Perform any grouping of the samples
const getSampleProcessor = (samples, sort, epoch, order, sampleDescriptor) => {
  // Perform grouping if there are epochs
  if (sampleDescriptor?.epochs > 1) {
    if (byEpoch(sort) || epoch !== "all") {
      return groupByEpoch(samples, sampleDescriptor, order);
    } else if (bySample(sort)) {
      return groupBySample(samples, sampleDescriptor, order);
    }
  }
  return noGrouping(samples, order);
};

// Performs no grouping
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

// Groups by sample (showing separators for Epochs)
const groupBySample = (samples, sampleDescriptor, order) => {
  // ensure that we are sorted by id
  samples = samples.sort((a, b) => {
    return ("" + a.id).localeCompare(b.id);
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

// Groups by epoch (showing a separator for each sample)
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
