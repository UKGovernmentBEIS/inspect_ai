import { html } from "htm/preact";
import { useEffect, useMemo, useRef } from "preact/hooks";

import { sharedStyles } from "../Constants.mjs";

import {
  shortenCompletion,
  arrayToString,
  answerForSample,
} from "../utils/Format.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { VirtualList } from "../components/VirtualList.mjs";

const kSampleHeight = 82;
const kSeparatorHeight = 32;

// Convert samples to a datastructure which contemplates grouping, etc...
export const SampleList = (props) => {
  const {
    listRef,
    items,
    sampleDescriptor,
    style,
    selectedIndex,
    setSelectedIndex,
    nextSample,
    prevSample,
    showSample,
  } = props;

  // If there are no samples, just display an empty state
  if (items.length === 0) {
    return html`<${EmptyPanel}>No Samples</${EmptyPanel}>`;
  }

  const heightForType = (type) => {
    return type === "sample" ? kSampleHeight : kSeparatorHeight;
  };

  // Compute the row arrangement
  const rowMap = useMemo(() => {
    return items.reduce((values, current, index) => {
      const height = heightForType(current.type);
      const previous =
        values.length > 0 ? values[values.length - 1] : undefined;
      const start =
        previous === undefined ? 0 : previous.start + previous.height;
      values.push({
        index,
        height,
        start,
      });
      return values;
    }, []);
  });

  useEffect(() => {
    const listEl = listRef.current;
    if (listEl) {
      // Decide if we need to scroll the element into position
      const selected = rowMap[selectedIndex];
      const itemTop = selected.start;
      const itemBottom = selected.start + selected.height;

      const scrollTop = listEl.base.scrollTop;
      const scrollBottom = scrollTop + listEl.base.offsetHeight;

      // It is visible
      if (itemTop >= scrollTop && itemBottom <= scrollBottom) {
        return;
      }

      if (itemTop < scrollTop) {
        // Top is scrolled off
        listEl.base.scrollTo({ top: itemTop });
        return;
      }

      if (itemBottom > scrollBottom) {
        listEl.base.scrollTo({top: itemBottom - listEl.base.offsetHeight});
        return;
      }
    }
  }, [selectedIndex, rowMap, listRef]);

  const renderRow = (item, index) => {
    if (item.type === "sample") {
      return html`
        <${SampleRow}
          id=${item.number}
          index=${index}
          sample=${item.data}
          height=${kSampleHeight}
          sampleDescriptor=${sampleDescriptor}
          selected=${selectedIndex === index}
          setSelected=${setSelectedIndex}
          showSample=${showSample}
        />
      `;
    } else if (item.type === "separator") {
      return html`
        <${SeparatorRow}
          id=${`sample-group${item.id}`}
          class="cool"
          title=${item.data}
          height=${kSeparatorHeight}
        />
      `;
    } else {
      return "";
    }
  };

  const onkeydown = (e) => {
    switch (e.key) {
      case "ArrowUp":
        prevSample();
        e.preventDefault();
        e.stopPropagation();
        return false;
      case "ArrowDown":
        nextSample();
        e.preventDefault();
        e.stopPropagation();
        return false;
      case "Enter":
        showSample();
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
  };

  const listStyle = { ...style, flex: "1", overflowY: "auto" };
  return html` <${VirtualList}
    ref=${listRef}
    data=${items}
    tabIndex="0"
    renderRow=${renderRow}
    onkeydown=${onkeydown}
    rowMap=${rowMap}
    style=${listStyle}
  />`;
};

const SeparatorRow = ({ id, title, height }) => {
  return html`<div
    id=${id}
    style=${{
      backgroundColor: "var(--bs-secondary-bg)",
      padding: ".45em 1em .25em 1em",
      textTransform: "uppercase",
      color: "var(--bs-secondary)",
      fontSize: "0.8em",
      fontWeight: 600,
      borderBottom: "solid 1px var(--bs-border-color)",
      height: `${height}px`,
    }}
  >
    <div>${title}</div>
  </div>`;
};

const SampleRow = ({
  id,
  index,
  sample,
  sampleDescriptor,
  height,
  selected,
  setSelected,
  showSample,
}) => {
  const selectedStyle = selected
    ? {
        boxShadow: "inset 0 0 0px 2px var(--bs-focus-ring-color)",
      }
    : {};

  const input =
    sampleDescriptor.messageShape.input > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.input)
      : 0;
  const target =
    sampleDescriptor.messageShape.target > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.target)
      : 0;
  const answer =
    sampleDescriptor.messageShape.answer > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.answer)
      : 0;

  const cellStyle = {
    paddingLeft: "0em",
    paddingRight: "0em",
  };

  return html`
    <div
      id=${`sample-${id}`}
      onclick=${() => {
        if (setSelected) {
          setSelected(index);
        }

        if (showSample) {
          showSample();
        }
      }}
      style=${{
        height: `${height}px`,
        display: "grid",
        gridTemplateColumns: `minmax(2em, auto) ${input}fr ${target}fr ${answer}fr minmax(2em, auto)`,
        gridTemplateRows: `${height - 28}px`,
        gridGap: "0.5em",
        fontSize: "0.8em",
        borderBottom: "solid var(--bs-border-color) 1px",
        padding: "1em",
        cursor: "pointer",
        ...selectedStyle,
        overflowY: "hidden"
      }}
    >
      <div
        class="sample-index"
        style=${{ ...cellStyle }}
      >
        ${id}
      </div>
      <div
        class="sample-input"
        style=${{
          ...sharedStyles.threeLineClamp,
          wordWrap: "anywhere",
          ...cellStyle,
        }}
      >
        ${sample.input}
      </div>
      <div
        class="sample-target"
        style=${{
          ...sharedStyles.threeLineClamp,
          ...cellStyle,
        }}
      >
        ${arrayToString(sample?.target)}
      </div>
      <div
        class="sample-answer"
        style=${{
          ...sharedStyles.threeLineClamp,
          ...cellStyle,
        }}
      >
        ${sample ? shortenCompletion(answerForSample(sample)) : ""}
      </div>

      <div
        style=${{
          fontSize: "0.8rem",
          ...cellStyle,
          display: "flex"
        }}
      >
        ${sampleDescriptor.scoreDescriptor.render
          ? sampleDescriptor.scoreDescriptor.render(sample?.score?.value)
          : sample?.score?.value === null
          ? "null"
          : sample?.score?.value}
      </div>
    </div>
  `;
};
