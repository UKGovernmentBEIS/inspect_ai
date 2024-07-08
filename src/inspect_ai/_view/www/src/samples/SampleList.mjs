import { html } from "htm/preact";
import { useEffect, useMemo } from "preact/hooks";

import { sharedStyles } from "../Constants.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";

import {
  shortenCompletion,
  arrayToString,
  answerForSample,
} from "../utils/Format.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { VirtualList } from "../components/VirtualList.mjs";
import { inputString } from "../utils/Format.mjs";

const kSampleHeight = 82;
const kSeparatorHeight = 20;

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
  }, [items]);

  useEffect(() => {
    const listEl = listRef.current;
    if (listEl) {
      // Decide if we need to scroll the element into position
      const selected = rowMap[selectedIndex];
      if (selected) {
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
          listEl.base.scrollTo({ top: itemBottom - listEl.base.offsetHeight });
          return;
        }
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
          id=${`sample-group${item.number}`}
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

  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };

  const headerRow = html`<div
    style=${{
      display: "grid",
      ...gridColumnStyles(sampleDescriptor),
      fontSize: "0.7rem",
      paddingBottom: "0.3em",
      paddingTop: "0.3em",
      borderBottom: "solid var(--bs-light-border-subtle) 1px",
    }}
  >
    <div>#</div>
    <div>Input</div>
    <div>Target</div>
    <div>Answer</div>
    <div>Score</div>
  </div>`;

  return html` <div
    style=${{ display: "flex", flexDirection: "column", width: "100%" }}
  >
    ${headerRow}
    <${VirtualList}
      ref=${listRef}
      data=${items}
      tabIndex="0"
      renderRow=${renderRow}
      onkeydown=${onkeydown}
      rowMap=${rowMap}
      style=${listStyle}
    />
  </div>`;
};

const SeparatorRow = ({ id, title, height }) => {
  return html`<div
    id=${id}
    style=${{
      backgroundColor: "var(--bs-secondary-bg)",
      padding: ".25em 1em .25em 1em",
      textTransform: "uppercase",
      color: "var(--bs-secondary)",
      fontSize: "0.6rem",
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
        ...gridColumnStyles(sampleDescriptor),
        paddingTop: "1em",
        paddingBottom: "1em",
        gridTemplateRows: `${height - 28}px`,
        fontSize: "0.8em",
        borderBottom: "solid var(--bs-border-color) 1px",
        cursor: "pointer",
        ...selectedStyle,
        overflowY: "hidden",
      }}
    >
      <div class="sample-index" style=${{ ...cellStyle }}>${id}</div>
      <div
        class="sample-input"
        style=${{
          ...sharedStyles.threeLineClamp,
          wordWrap: "anywhere",
          ...cellStyle,
        }}
      >
        ${inputString(sample.input)}
      </div>
      <div
        class="sample-target"
        style=${{
          ...sharedStyles.threeLineClamp,
          ...cellStyle,
        }}
      >
        <${MarkdownDiv}
          markdown=${arrayToString(sample?.target)}
          style=${{ paddingLeft: "0" }}
          class="no-last-para-padding"
        />
      </div>
      <div
        class="sample-answer"
        style=${{
          ...sharedStyles.threeLineClamp,
          ...cellStyle,
        }}
      >
        ${sample
          ? html`
              <${MarkdownDiv}
                markdown=${shortenCompletion(answerForSample(sample))}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            `
          : ""}
      </div>

      <div
        style=${{
          fontSize: "0.8rem",
          ...cellStyle,
          display: "flex",
        }}
      >
        ${sampleDescriptor?.scoreDescriptor.render
          ? sampleDescriptor.scoreDescriptor.render(sample?.score?.value)
          : sample?.score?.value === null
            ? "null"
            : sample?.score?.value}
      </div>
    </div>
  `;
};

const gridColumnStyles = (sampleDescriptor) => {
  const { input, target, answer } = gridColumns(sampleDescriptor);

  return {
    gridGap: "0.5em",
    gridTemplateColumns: `minmax(2rem, auto) ${input}fr ${target}fr ${answer}fr minmax(2rem, auto)`,
    paddingLeft: "1em",
    paddingRight: "1em",
  };
};

const gridColumns = (sampleDescriptor) => {
  const input =
    sampleDescriptor?.messageShape.input > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.input)
      : 0;
  const target =
    sampleDescriptor?.messageShape.target > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.target)
      : 0;
  const answer =
    sampleDescriptor?.messageShape.answer > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.answer)
      : 0;
  return { input, target, answer };
};
