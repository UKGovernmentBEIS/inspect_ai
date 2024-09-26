import { html } from "htm/preact";
import { useState, useEffect } from "preact/hooks";

import { ChatView } from "../components/ChatView.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { TabSet, TabPanel } from "../components/TabSet.mjs";

import { inputString } from "../utils/Format.mjs";
import { escapeSelector, isVscode } from "../utils/Html.mjs";

import { ApplicationStyles } from "../appearance/Styles.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { arrayToString } from "../utils/Format.mjs";

import { SampleScoreView } from "./SampleScoreView.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { SampleTranscript } from "./SampleTranscript.mjs";
import { ANSIDisplay } from "../components/AnsiDisplay.mjs";
import { FlatSampleError } from "./SampleError.mjs";
import { ToolButton } from "../components/ToolButton.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";

import { printHeadingHtml, printHtml } from "../utils/Print.mjs";

export const InlineSampleDisplay = ({
  index,
  id,
  sample,
  sampleDescriptor,
  context,
}) => {
  return html`<div
    style=${{ flexDirection: "row", width: "100%", margin: "1em" }}
  >
    <${SampleDisplay}
      index=${index}
      id=${id}
      sample=${sample}
      sampleDescriptor=${sampleDescriptor}
      context=${context}
    />
  </div>`;
};

export const SampleDisplay = ({
  sample,
  sampleDescriptor,
  visible,
  index,
  context,
}) => {
  // Tab ids
  const baseId = `sample-dialog`;
  const msgTabId = `${baseId}-messages`;
  const transcriptTabId = `${baseId}-transcript`;
  const scoringTabId = `${baseId}-scoring`;
  const metdataTabId = `${baseId}-metadata`;
  const errorTabId = `${baseId}-error`;

  // Upon new dialog
  useEffect(() => {
    if (!visible) {
      setSelectedTab(undefined);
    } else {
      if (selectedTab === undefined) {
        const defaultTab =
          sample.transcript && sample.transcript.events.length > 0
            ? transcriptTabId
            : msgTabId;
        setSelectedTab(defaultTab);
      }
    }
  }, [visible]);

  // Tab selection
  const [selectedTab, setSelectedTab] = useState(undefined);
  const onSelectedTab = (e) => {
    const id = e.currentTarget.id;
    setSelectedTab(id);
    return false;
  };

  // The core tabs
  const tabs = [
    html`
    <${TabPanel} id=${msgTabId} classes="sample-tab" title="Messages" onSelected=${onSelectedTab} selected=${
      selectedTab === msgTabId
    }>
      <${ChatView} 
        key=${`${baseId}-chat-${index}`} 
        id=${`${baseId}-chat-${index}`} 
        messages=${sample.messages} 
        style=${{ paddingLeft: ".8em", paddingTop: "1em" }}
        indented=${true}
      />
    </${TabPanel}>`,
  ];

  if (sample.transcript && sample.transcript.events.length > 0) {
    tabs.unshift(html`
      <${TabPanel} id=${transcriptTabId} classes="sample-tab" title="Transcript" onSelected=${onSelectedTab} selected=${
        selectedTab === transcriptTabId || selectedTab === undefined
      } scrollable=${false}>
        <${SampleTranscript} key=${`${baseId}-transcript-display-${index}`} id=${`${baseId}-transcript-display-${index}`} evalEvents=${sample.transcript}/>
      </${TabPanel}>`);
  }

  const scorerNames = Object.keys(sample.scores);
  if (scorerNames.length === 1) {
    tabs.push(html`
      <${TabPanel} id=${scoringTabId} classes="sample-tab" title="Scoring" onSelected=${onSelectedTab} selected=${
        selectedTab === scoringTabId
      }>
        <${SampleScoreView}
          sample=${sample}
          context=${context}
          sampleDescriptor=${sampleDescriptor}
          scorer=${Object.keys(sample.scores)[0]}
          style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
        />
      </${TabPanel}>`);
  } else {
    for (const scorer of Object.keys(sample.scores)) {
      const tabId = `score-${scorer}`;
      tabs.push(html`
        <${TabPanel} id="${tabId}" classes="sample-tab" title="${scorer}" onSelected=${onSelectedTab} selected=${
          selectedTab === tabId
        }>
          <${SampleScoreView}
            sample=${sample}
            context=${context}
            sampleDescriptor=${sampleDescriptor}
            scorer=${scorer}
            style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}
          />
        </${TabPanel}>`);
    }
  }

  const sampleMetadatas = metadataViewsForSample(
    `${baseId}-${index}`,
    sample,
    context,
  );
  if (sampleMetadatas.length > 0) {
    tabs.push(
      html`
      <${TabPanel} 
          id=${metdataTabId} 
          classes="sample-tab"
          title="Metadata" 
          onSelected=${onSelectedTab} 
          selected=${selectedTab === metdataTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
        ${sampleMetadatas}
        </div>
      </${TabPanel}>`,
    );
  }

  if (sample.error) {
    tabs.push(
      html`
      <${TabPanel} 
          id=${errorTabId} 
          classes="sample-tab"
          title="Error" 
          onSelected=${onSelectedTab} 
          selected=${selectedTab === errorTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
          <${ANSIDisplay} output=${sample.error.traceback_ansi} style=${{ fontSize: FontSize.small, margin: "1em 0" }}/>
        </div>
      </${TabPanel}>`,
    );
  }

  const tabsetId = `task-sample-details-tab-${sample.id}`;
  const targetId = `${tabsetId}-content`;
  const printSample = () => {
    // The active tab
    const targetTabEl = document.querySelector(
      `#${escapeSelector(targetId)} .sample-tab.tab-pane.show.active`,
    );
    if (targetTabEl) {
      // The target element
      const targetEl = targetTabEl.firstElementChild;
      if (targetEl) {
        // Get the sample heading to include
        const headingId = `sample-heading-${sample.id}`;
        const headingEl = document.getElementById(headingId);

        // Print the document
        const headingHtml = printHeadingHtml();
        const css = `
        html { font-size: 9pt }
        /* Allow content to break anywhere without any forced page breaks */
        * {
          break-inside: auto;  /* Let elements break anywhere */
          page-break-inside: auto;  /* Legacy support */
          break-before: auto;
          page-break-before: auto;
          break-after: auto;
          page-break-after: auto;
        }
        /* Specifically disable all page breaks for divs */
        div {
          break-inside: auto;
          page-break-inside: auto;
        }
        body > .transcript-step {
          break-inside: avoid;
        }
        body{
          -webkit-print-color-adjust:exact !important;
          print-color-adjust:exact !important;
        }
        /* Allow preformatted text and code blocks to break across pages */
        pre, code {
            white-space: pre-wrap; /* Wrap long lines instead of keeping them on one line */
            overflow-wrap: break-word; /* Ensure long words are broken to fit within the page */
            break-inside: auto; /* Allow page breaks inside the element */
            page-break-inside: auto; /* Older equivalent */
        }

        /* Additional control for long lines within code/preformatted blocks */
        pre {
            word-wrap: break-word; /* Break long words if needed */
        }    
            
        `;
        printHtml(
          [headingHtml, headingEl.outerHTML, targetEl.innerHTML].join("\n"),
          css,
        );
      }
    }
  };

  const tools = [];
  if (!isVscode()) {
    tools.push(
      html`<${ToolButton}
        name=${html`Print`}
        icon="${ApplicationIcons.copy}"
        onclick="${printSample}"
      />`,
    );
  }

  return html`<${SampleSummary}
    id=${sample.id}
    sample=${sample}
    sampleDescriptor=${sampleDescriptor}/>

  <${TabSet} id=${tabsetId} styles=${{
    tabs: {
      fontSize: FontSize.base,
    },
    tabBody: { paddingBottom: "1em" },
  }}
    tools=${tools}>
    ${tabs}
  </${TabSet}>`;
};

const metadataViewsForSample = (id, sample, context) => {
  const sampleMetadatas = [];
  if (Object.keys(sample?.metadata).length > 0) {
    sampleMetadatas.push(
      html` <${MetaDataView}
        id="task-sample-metadata-${id}"
        classes="tab-pane"
        entries="${sample?.metadata}"
        style=${{ marginTop: "1em" }}
        context=${context}
      />`,
    );
  }

  if (
    sample?.score?.metadata &&
    Object.keys(sample?.score?.metadata).length > 0
  ) {
    sampleMetadatas.push(
      html`<${MetaDataView}
        id="task-sample-metadata-${id}"
        classes="tab-pane"
        entries="${sample?.score?.metadata}"
        style=${{ marginTop: "1em" }}
        context=${context}
      />`,
    );
  }
  return sampleMetadatas;
};

const SampleSummary = ({ id, sample, style, sampleDescriptor }) => {
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

  const scoreInput = [inputString(sample.input)];
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  // The columns for the sample
  const columns = [];
  columns.push({
    label: "Id",
    value: id,
    size: "minmax(min-content, max-content)",
  });

  columns.push({
    label: "Input",
    value: scoreInput,
    size: `${input}fr`,
    clamp: true,
  });

  if (sample.target) {
    columns.push({
      label: "Target",
      value: html`<${MarkdownDiv}
        markdown=${arrayToString(arrayToString(sample?.target || "none"))}
        style=${{ paddingLeft: "0" }}
        class="no-last-para-padding"
      />`,
      size: `${target}fr`,
      clamp: true,
    });
  }

  const fullAnswer =
    sample && sampleDescriptor
      ? sampleDescriptor.selectedScorer(sample).answer()
      : undefined;
  if (fullAnswer) {
    columns.push({
      label: "Answer",
      value: sample
        ? html`<${MarkdownDiv}
            markdown=${fullAnswer}
            style=${{ paddingLeft: "0" }}
            class="no-last-para-padding"
          />`
        : "",
      size: `${answer}fr`,
      clamp: true,
    });
  }

  columns.push({
    label: "Score",
    value: sample.error
      ? html`<${FlatSampleError}
          message=${sample.error.message}
          style=${{ marginTop: "0.4rem" }}
        />`
      : sampleDescriptor?.selectedScore(sample).render(),
    size: "minmax(2em, auto)",
    center: true,
  });

  return html`
    <div
      id=${`sample-heading-${id}`}
      style=${{
        display: "grid",
        gridTemplateColumns: `${columns
          .map((col) => {
            return col.size;
          })
          .join(" ")}`,
        gridColumnGap: "0.5em",
        fontSize: FontSize.base,
        borderBottom: "solid var(--bs-border-color) 1px",
        marginBottom: "1em",
        padding: "0em 1em 1em 1em",
        ...style,
      }}
    >
      ${columns.map((col) => {
        const style = {
          ...TextStyle.label,
          ...TextStyle.secondary,
          fontSize: FontSize.base,
        };
        if (col.center) {
          style["display"] = "flex";
          style["justifyContent"] = "center";
        }
        return html`<div style=${{ ...style }}>${col.label}</div>`;
      })}
      ${columns.map((col) => {
        const style = {
          ...(col.clamp ? ApplicationStyles.threeLineClamp : {}),
        };
        if (col.center) {
          style.display = "flex";
          style.justifyContent = "center";
        }
        style.wordWrap = "anywhere";
        return html`<div style=${{ ...style }}>${col.value}</div>`;
      })}
    </div>
  `;
};
