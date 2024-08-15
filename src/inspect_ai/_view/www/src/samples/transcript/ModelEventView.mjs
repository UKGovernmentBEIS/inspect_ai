// @ts-check
import { html } from "htm/preact";
import { useRef } from "preact/hooks";
import { ChatView } from "../../components/ChatView.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import Prism from "prismjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").ModelEvent} props.event - The event object to display.
 * @param {string} props.baseId - The baseId of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ModelEventView = ({ id, depth, event }) => {
  const totalUsage = event.output.usage?.total_tokens;
  const subtitle = totalUsage ? `(${totalUsage} tokens)` : "";

  // Note: despite the type system saying otherwise, this has appeared empircally
  // to sometimes be undefined
  const outputMessages = event.output.choices?.map((choice) => {
    return choice.message;
  });

  const entries = { ...event.config };
  if (event.tools) {
    entries["tools"] = event.tools;
    entries["tool_choice"] = event.tool_choice;
  }

  return html`
  <${EventPanel} id=${id} depth=${depth} title="Model Call: ${event.model} ${subtitle}" icon=${ApplicationIcons.model}>
  
    <div name="Answer">
    <${ChatView}
      id="${id}-model-output"
      messages=${[...(outputMessages || [])]}
      />
    </div>

    <div name="All">
      <${MetaDataGrid} entries=${entries} style=${{ margin: "1em 0" }}/>

      <${ChatView}
        id="${id}-model-input-full"
        messages=${[...event.input, ...(outputMessages || [])]}
        />      
    </div>

    <${APIView} name="API" call=${event.call} style=${{ margin: "1em 0" }} />
   

  </${EventPanel}>`;
};

export const APIView = ({ call, style }) => {
  if (!call) {
    return "";
  }

  return html`<div style=${style}>
    <div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>Request</div>
    <${APICodeCell} contents=${call.request} />
    <div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
      Response
    </div>
    <${APICodeCell} contents=${call.response} />
  </div>`;
};

export const APICodeCell = ({ id, contents }) => {
  if (!contents) {
    return "";
  }

  const sourceCode = JSON.stringify(contents, undefined, 2);
  const codeRef = useRef();

  if (codeRef.current) {
    codeRef.current.innerHTML = Prism.highlight(
      sourceCode,
      Prism.languages.javascript,
      "javacript",
    );
  }

  return html`<div>
    <pre
      style=${{
        background: "var(--bs-light)",
        width: "100%",
        padding: "0.5em",
        borderRadius: "3px",
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
