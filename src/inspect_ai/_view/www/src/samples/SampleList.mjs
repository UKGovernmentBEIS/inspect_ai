import { html } from "htm/preact";
import { useCallback } from "preact/hooks";
import { useEffect, useMemo } from "preact/hooks";

import { ApplicationStyles } from "../appearance/Styles.mjs";
import { FontSize } from "../appearance/Fonts.mjs";
import { TextStyle } from "../appearance/Fonts.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { SampleError } from "./SampleError.mjs";

import { arrayToString, formatNoDecimal } from "../utils/Format.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { VirtualList } from "../components/VirtualList.mjs";
import { WarningBand } from "../components/WarningBand.mjs";
import { inputString } from "../utils/Format.mjs";

const kSampleHeight = 88;
const kSeparatorHeight = 24;

// Convert samples to a datastructure which contemplates grouping, etc...
export const SampleList = (props) => {
  const {
    listRef,
    items,
    sampleDescriptor,
    style,
    selectedIndex,
    setSelectedIndex,
    selectedScore,
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

  const renderRow = (item) => {
    if (item.type === "sample") {
      return html`
        <${SampleRow}
          id=${item.number}
          index=${item.index}
          sample=${item.data}
          height=${kSampleHeight}
          sampleDescriptor=${sampleDescriptor}
          selected=${selectedIndex === item.index}
          setSelected=${setSelectedIndex}
          selectedScore=${selectedScore}
          showSample=${showSample}
        />
      `;
    } else if (item.type === "separator") {
      return html`
        <${SeparatorRow}
          id=${`sample-group${item.number}`}
          title=${item.data}
          height=${kSeparatorHeight}
        />
      `;
    } else {
      return "";
    }
  };

  const onkeydown = useCallback(
    (e) => {
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
          showSample(selectedIndex);
          e.preventDefault();
          e.stopPropagation();
          return false;
      }
    },
    [selectedIndex],
  );

  const listStyle = { ...style, flex: "1", overflowY: "auto", outline: "none" };

  const headerRow = html`<div
    style=${{
      display: "grid",
      ...gridColumnStyles(sampleDescriptor),
      fontSize: FontSize.smaller,
      ...TextStyle.label,
      ...TextStyle.secondary,
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

  const sampleCount = items?.reduce((prev, current) => {
    if (current.type === "sample") {
      return prev + 1;
    } else {
      return prev;
    }
  }, 0);
  const footerRow = html` <div
    style=${{
      borderTop: "solid var(--bs-light-border-subtle) 1px",
      background: "var(--bs-light-bg-subtle)",
      fontSize: FontSize.smaller,
      display: "grid",
      gridTemplateColumns: "max-content",
      justifyContent: "end",
      alignContent: "end",
      padding: "0.2em 1em",
    }}
  >
    <div>${sampleCount} Samples</div>
  </div>`;

  // Count any sample errors and display a bad alerting the user
  // to any errors
  const errorCount = items?.reduce((previous, item) => {
    if (item.data.error) {
      return previous + 1;
    } else {
      return previous;
    }
  }, 0);

  const percentError = (errorCount / sampleCount) * 100;
  const warningMessage =
    errorCount > 0
      ? `WARNING: ${errorCount} of ${sampleCount} samples (${formatNoDecimal(percentError)}%) had errors and were not scored.`
      : undefined;

  const warningRow = warningMessage
    ? html`<${WarningBand} message=${warningMessage} />`
    : "";

  return html` <div
    style=${{ display: "flex", flexDirection: "column", width: "100%" }}
  >
    ${warningRow} ${headerRow}
    <${VirtualList}
      ref=${listRef}
      data=${items}
      tabIndex="0"
      renderRow=${renderRow}
      onkeydown=${onkeydown}
      rowMap=${rowMap}
      style=${listStyle}
    />
    ${footerRow}
  </div>`;
};

const SeparatorRow = ({ id, title, height }) => {
  return html`<div
    id=${id}
    style=${{
      padding: ".25em 1em .25em 1em",
      textTransform: "uppercase",
      ...TextStyle.secondary,
      fontSize: FontSize.smaller,
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
        showSample(index);
      }}
      style=${{
        height: `${height}px`,
        display: "grid",
        ...gridColumnStyles(sampleDescriptor),
        paddingTop: "1em",
        paddingBottom: "1em",
        gridTemplateRows: `${height - 28}px`,
        fontSize: FontSize.base,
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
          ...ApplicationStyles.threeLineClamp,
          wordWrap: "anywhere",
          ...cellStyle,
        }}
      >
        ${inputString(sample.input).join(" ")}
      </div>
      <div
        class="sample-target"
        style=${{
          ...ApplicationStyles.threeLineClamp,
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
          ...ApplicationStyles.threeLineClamp,
          ...cellStyle,
        }}
      >
        ${sample
          ? html`
              <${MarkdownDiv}
                markdown=${sampleDescriptor?.selectedScorer(sample).answer()}
                style=${{ paddingLeft: "0" }}
                class="no-last-para-padding"
              />
            `
          : ""}
      </div>

      <div
        style=${{
          fontSize: FontSize.small,
          ...cellStyle,
          display: "flex",
        }}
      >
        ${sample.error
          ? html`<${SampleError} message=${sample.error.message} />`
          : sampleDescriptor?.selectedScore(sample).render()}
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
