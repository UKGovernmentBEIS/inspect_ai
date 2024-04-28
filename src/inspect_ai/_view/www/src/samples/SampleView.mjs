import { html } from "htm/preact";
import { useState, useEffect } from "preact/hooks";

import { sharedStyles } from "../Constants.mjs";
import { ChatView } from "../components/ChatView.mjs";
import { MarkdownDiv } from "../components/MarkdownDiv.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { TabSet, Tab } from "../components/TabSet.mjs";
import {
  arrayToString,
  shortenCompletion,
  answerForSample,
} from "../utils/Format.mjs";

import { SampleScoreView } from "./SampleScoreView.mjs";

export const SampleView = ({
  id,
  index,
  sample,
  sampleDescriptor,
  toggleSample,
  context,
  expanded = false,
  noHighlight = false,
}) => {
  const sampleColTextStyle = {
    fontSize: "0.7rem",
    fontWeight: "500",
  };
  const tabBodyStyle = {
    margin: "0.8rem",
  };

  // Tab ids
  const baseId = `sample-${index}`;
  const msgTabId = `${baseId}-messages`;
  const scoringTabId = `${baseId}-scoring`;
  const metdataTabId = `${baseId}-metadata`;

  const [selectedTab, setSelectedTab] = useState(undefined);
  // reset tabs when sample changes
  useEffect(() => {
    setSelectedTab(msgTabId);
  }, [sample]);

  const input = summarizeInput(sample.input);

  const onSelectedTab = (e) => {
    const id = e.currentTarget.id;
    setSelectedTab(id);
    return false;
  };

  const tabs = [
    html`<${Tab} id=${msgTabId} title="Messages" onSelected=${onSelectedTab} selected=${
      selectedTab === msgTabId || selectedTab === undefined
    }>
          <${ChatView} messages=${sample.messages} style=${tabBodyStyle}/>
        </${Tab}>`,
    html`<${Tab} id=${scoringTabId} title="Scoring" onSelected=${onSelectedTab} selected=${
      selectedTab === scoringTabId
    }>
            <${SampleScoreView}
              sample=${sample}
              context=${context}
              sampleDescriptor=${sampleDescriptor}
              style=${tabBodyStyle}
            />
        </${Tab}>`,
  ];

  const sampleMetadatas = [];
  if (Object.keys(sample?.metadata).length > 0) {
    sampleMetadatas.push(html` <${MetaDataView}
      id="task-sample-metadata-${id}"
      classes="tab-pane"
      entries="${sample?.metadata}"
      style=${{ marginTop: "1em" }}
      context=${context}
    />`);
  }

  if (
    sample?.score?.metadata &&
    Object.keys(sample?.score?.metadata).length > 0
  ) {
    sampleMetadatas.push(html` <${MetaDataView}
      id="task-sample-metadata-${id}"
      classes="tab-pane"
      entries="${sample?.score?.metadata}"
      style=${{ marginTop: "1em" }}
      context=${context}
      expanded=${true}
    />`);
  }

  if (sampleMetadatas.length > 0) {
    tabs.push(
      html`<${Tab} id=${metdataTabId} title="Metadata" onSelected=${onSelectedTab} selected=${
        selectedTab === metdataTabId
      }>
              <div style=${tabBodyStyle}>
              ${sampleMetadatas}
              </div>
          </${Tab}>`
    );
  }

  return html`
    <div class="accordion-item ${noHighlight ? "no-highlight" : ""}" id="${id}">
      <div
        class="container-fluid accordion-header"
        style=${{
          justifyContent: "space-between",
          marginLeft: "0",
          paddingLeft: "0",
          paddingRight: "0",
          display: "flex",
        }}
      >
        <div
          class="row accordion-button toggle-rotated${
            expanded ? "" : " collapsed"
          }"
          type="button"
          data-bs-toggle="collapse"
          data-bs-target="#${id}-collapse"
          aria-expanded="${expanded ? "true" : "false"}"
          aria-controls="${id}-collapse"
          style=${{
            marginLeft: "0",
            marginRight: "0",
            padding: "0",
            flexWrap: "nowrap",
            minHeight: "2em",
            boxShadow: "none",
          }}
          onclick=${() => {
            toggleSample(sample.id);
          }}
        >
          <div
            style=${{
              fontSize: "0.8em",
              fontWeight: "600",
              display: "inline-flex",
              justifyContent: "center",
              height: "100%",
              alignItems: "center",
              flex: "1 1 5em",
            }}
          >
            <div style=${{
              whiteSpace: "pre-wrap",
              wordWrap: "anywhere",
              color: "var(--bs-secondary)",
            }}>
              ${index}
            </div>
          </div>

          <div
            style=${{
              display: "flex",
              flexShrink: "1",
              paddingTop: ".4rem",
              paddingBottom: ".4rem",
              paddingLeft: ".7rem",
              paddingRight: ".7rem",
              alignItems: "center",
            }}
          >
            <div
              class="tight-paragraphs col"
              style=${{
                display: "flex",
                fontSize: "0.8rem",
                paddingLeft: "0",
                paddingRight: "1rem",
                ...sharedStyles.scoreGrid.titleCol,
              }}
            >
              <div style=${{
                ...sharedStyles.threeLineClamp,
                flexBasis: "100%",
                wordWrap: "anywhere",
              }}>
              ${input}
              </DIV>
            </div>
            <div
              class="col"
              style=${{
                ...sampleColTextStyle,
                ...sharedStyles.scoreGrid.targetCol,
                ...sharedStyles.threeLineClamp,
                marginLeft: ".8em",
              }}
            >
              ${arrayToString(sample?.target)}
            </div>
            <div
              class="col"
              style=${{
                ...sampleColTextStyle,
                ...sharedStyles.scoreGrid.answerCol,
                ...sharedStyles.threeLineClamp,
                marginLeft: "1em",
              }}
            >
              ${sample ? shortenCompletion(answerForSample(sample)) : ""}
            </div>
            <div
              class="col"
              style=${{
                fontSize: "0.8rem",
                marginLeft: "1rem",
                ...sharedStyles.scoreGrid.scoreCol,
                flexBasis: "3.2em",
              }}
            >
              ${
                sampleDescriptor.scoreDescriptor.render
                  ? sampleDescriptor.scoreDescriptor.render(
                      sample?.score?.value
                    )
                  : sample?.score?.value === null
                  ? "null"
                  : sample?.score?.value
              }
            </div>
          </div>
        </div>
      </div>

      <div
        class="accordion-collapse collapse${
          expanded ? " show" : ""
        } highlight-when-expanded"
        id="${id}-collapse"
        style=${{
          padding: "8px 1em 0 1rem",
        }}
      >

        <div style=${{
          paddingTop: "0",
          paddingBottom: "1rem",
          marginLeft: ".5rem",
        }}>
          <${TabSet} id="task-sample-details-tab-${id}" style=${{
    marginTop: "0.5rem",
  }}>
          ${tabs}
        </${TabSet}>
        </div>
      </div>
    </div>
  `;
};

const summarizeInput = (input) => {
  if (typeof input === "string") {
    // Simple input string
    return html`<${MarkdownDiv} markdown=${input.trim()} />`;
  } else {
    // First the first user message and use it's text as the input
    const userMessage = input.find((msg) => {
      return msg.role === "user";
    });
    if (userMessage) {
      const userContent = userMessage.content;
      if (Array.isArray(userContent)) {
        const textInput = userContent.find((content) => {
          return content.type === "text";
        });
        if (textInput) {
          return html`<${MarkdownDiv} markdown=${textInput.text.trim()} />`;
        } else {
          return "[Image Input]";
        }
      } else {
        if (typeof userContent === "object") {
          return html`<${MarkdownDiv}
            markdown=${userContent.content.trim()}
          />`;
        } else {
          return html`<${MarkdownDiv} markdown=${userContent.trim()} />`;
        }
      }
    } else {
      return "[Unknown Input]";
    }
  }
};
