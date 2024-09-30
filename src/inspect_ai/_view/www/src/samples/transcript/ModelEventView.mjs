// @ts-check
/// <reference path="../../types/prism.d.ts" />
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";

import { html } from "htm/preact";
import { useEffect, useRef } from "preact/hooks";
import { ChatView } from "../../components/ChatView.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { EventSection } from "./EventSection.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { ModelUsagePanel } from "../../usage/UsageCard.mjs";
import { formatNumber } from "../../utils/Format.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ModelEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @param {string} props.baseId - The baseId of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ModelEventView = ({ id, event, style }) => {
  const totalUsage = event.output.usage?.total_tokens;
  const subtitle = totalUsage ? `(${formatNumber(totalUsage)} tokens)` : "";

  // Note: despite the type system saying otherwise, this has appeared empircally
  // to sometimes be undefined
  const outputMessages = event.output.choices?.map((choice) => {
    return choice.message;
  });

  const entries = { ...event.config };
  entries["tool_choice"] = event.tool_choice;
  delete entries["max_connections"];

  const tableSectionStyle = {
    width: "fit-content",
    alignSelf: "start",
    justifySelf: "start",
  };

  // For any user messages which immediately preceded this model call, including a
  // panel and display those user messages
  const userMessages = [];
  for (const msg of event.input.reverse()) {
    if (msg.role === "user") {
      userMessages.push(msg);
    } else {
      break;
    }
  }

  return html`
  <${EventPanel} id=${id} title="Model Call: ${event.model} ${subtitle}" icon=${ApplicationIcons.model} style=${style}>
  
    <div name="Summary" style=${{ margin: "0.5em 0" }}>
    <${ChatView}
      id="${id}-model-output"
      messages=${[...userMessages, ...(outputMessages || [])]}
      style=${{ paddingTop: "1em" }}
      numbered=${false}
      />
    </div>

    <div name="All" style=${{ margin: "0.5em 0" }}>

      <div style=${{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: "1em" }}>
      <${EventSection} title="Configuration" style=${tableSectionStyle}>
        <${MetaDataGrid} entries=${entries} plain=${true}/>
      </${EventSection}>

      <${EventSection} title="Usage" style=${tableSectionStyle}>
        <${ModelUsagePanel} usage=${event.output.usage}/>
      </${EventSection}>

      <${EventSection} title="Tools" style=${{ gridColumn: "-1/1", ...tableSectionStyle }}>
        <${ToolsConfig} tools=${event.tools}/>
      </${EventSection}>

      </div>

      <${EventSection} title="Messages">
        <${ChatView}
          id="${id}-model-input-full"
          messages=${[...event.input, ...(outputMessages || [])]}
          />      
      </${EventSection}>

    </div>

    ${event.call ? html`<${APIView} name="API" call=${event.call} style=${{ margin: "0.5em 0", width: "100%" }} />` : ""}
   
  </${EventPanel}>`;
};

export const APIView = ({ call, style }) => {
  if (!call) {
    return "";
  }

  return html`<div style=${style}>

    <${EventSection} title="Request">
      <${APICodeCell} contents=${call.request} />
    </${EventSection}>
    <${EventSection} title="Response">
      <${APICodeCell} contents=${call.response} />
    </${EventSection}>

    </div>`;
};

export const APICodeCell = ({ id, contents }) => {
  if (!contents) {
    return "";
  }

  const sourceCode = JSON.stringify(contents, undefined, 2);
  const codeRef = useRef();

  useEffect(() => {
    if (codeRef.current) {
      // @ts-ignore
      codeRef.current.innerHTML = Prism.highlight(
        sourceCode,
        Prism.languages.javascript,
        "javacript",
      );
    }
  }, [codeRef.current, contents]);

  return html`<div>
    <pre
      style=${{
        background: "var(--bs-light)",
        width: "100%",
        padding: "0.5em",
        borderRadius: "var(--bs-border-radius)",
      }}
    >
      <code 
        id=${id} 
        ref=${codeRef}
        class="sourceCode-js" 
        style=${{
      fontSize: FontSize.small,
      whiteSpace: "pre-wrap",
      wordWrap: "anywhere",
    }}>
      </code>
      </pre>
  </div>`;
};

const ToolsConfig = ({ tools }) => {
  const toolEls = tools.map((tool) => {
    return html`<div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
        ${tool.name}
      </div>
      <div>${tool.description}</div>`;
  });

  return html`<div
    style=${{
      display: "grid",
      gridTemplateColumns: "max-content auto",
      columnGap: "1em",
      rowGap: "0.5em",
    }}
  >
    ${toolEls}
  </div>`;
};
