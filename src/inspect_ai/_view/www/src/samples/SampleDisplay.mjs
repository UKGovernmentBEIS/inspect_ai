import { html } from "htm/preact";
import { useState, useEffect } from "preact/hooks";

import { ChatView } from "../components/ChatView.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { TabSet, TabPanel } from "../components/TabSet.mjs";

import { inputString } from "../utils/Format.mjs";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { ApplicationStyles } from "../appearance/Styles.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { arrayToString, shortenCompletion } from "../utils/Format.mjs";

import { SampleScoreView } from "./SampleScoreView.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { SampleTranscript } from "./SampleTranscript.mjs";

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
  index,
  id,
  sample,
  sampleDescriptor,
  context,
}) => {
  // Tab ids
  const baseId = `sample-${index}`;
  const msgTabId = `${baseId}-messages`;
  const transcriptTabId = `${baseId}-transcript`;
  const scoringTabId = `${baseId}-scoring`;
  const metdataTabId = `${baseId}-metadata`;

  // Upon sample update
  useEffect(() => {
    // reset tabs when sample changes
    if (sample.transcript && sample.transcript.events.length > 0) {
      setSelectedTab(transcriptTabId);
    } else {
      setSelectedTab(msgTabId);
    }
  }, [sample]);

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
    <${TabPanel} id=${msgTabId} title="Messages" icon=${ApplicationIcons.messages} onSelected=${onSelectedTab} selected=${
      selectedTab === msgTabId
    }>
      <${ChatView} key=${`${baseId}-chat`} id=${`${baseId}-chat`} messages=${
        sample.messages
      } style=${{ paddingLeft: ".8em", paddingTop: "1em" }}/>
    </${TabPanel}>`,
  ];

  if (sample.transcript && sample.transcript.events.length > 0) {
    tabs.unshift(html`
      <${TabPanel} id=${transcriptTabId} title="Transcript" icon=${ApplicationIcons.transcript} onSelected=${onSelectedTab} selected=${
        selectedTab === transcriptTabId || selectedTab === undefined
      } scrollable=${false}>
        <${SampleTranscript} id=${`${baseId}-transcript`} evalEvents=${sample.transcript}/>
      </${TabPanel}>`);
  }

  const scorerNames = Object.keys(sample.scores);
  if (scorerNames.length === 1) {
    tabs.push(html`
      <${TabPanel} id=${scoringTabId} title="Scoring" icon=${ApplicationIcons.scorer} onSelected=${onSelectedTab} selected=${
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
        <${TabPanel} id="${tabId}" title="${scorer}" icon=${ApplicationIcons.scorer} onSelected=${onSelectedTab} selected=${
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

  const sampleMetadatas = metadataViewsForSample(baseId, sample, context);
  if (sampleMetadatas.length > 0) {
    tabs.push(
      html`
      <${TabPanel} 
          id=${metdataTabId} 
          title="Metadata" 
          icon=${ApplicationIcons.metadata}
          onSelected=${onSelectedTab} 
          selected=${selectedTab === metdataTabId}>
         <div style=${{ paddingLeft: "0.8em", marginTop: "0.4em" }}> 
        ${sampleMetadatas}
        </div>
      </${TabPanel}>`,
    );
  }

  return html`<${SampleSummary}
    id=${sample.id}
    sample=${sample}
    sampleDescriptor=${sampleDescriptor}/>

  <${TabSet} id="task-sample-details-tab-${id}" styles=${{
    tabs: {
      fontSize: FontSize.base,
    },
    tabBody: {},
  }}>
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
            markdown=${arrayToString(shortenCompletion(fullAnswer))}
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
    value: sampleDescriptor?.selectedScore(sample).render(),
    size: "minmax(2em, auto)",
    center: true,
  });

  return html`
    <div
      id=${`sample-${id}`}
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
