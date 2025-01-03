import { autocompletion } from "@codemirror/autocomplete";
import {
  HighlightStyle,
  StreamLanguage,
  syntaxHighlighting,
  bracketMatching,
} from "@codemirror/language";
import { linter } from "@codemirror/lint";
import { Compartment, EditorState } from "@codemirror/state";
import { tags } from "@lezer/highlight";
import { EditorView, minimalSetup } from "codemirror";
import { html } from "htm/preact";
import { useEffect, useMemo, useRef } from "preact/hooks";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { scoreFilterItems } from "./filters.mjs";

const KEYWORDS = ["and", "or", "not", "in", "not in", "mod"];

const MATH_FUNCTIONS = [
  ["min", "Minimum of two or more values"],
  ["max", "Maximum of two or more values"],
  ["abs", "Absolute value"],
  ["round", "Round to the nearest integer"],
  ["floor", "Round down to the nearest integer"],
  ["ceil", "Round up to the nearest integer"],
  ["sqrt", "Square root"],
  ["log", "Natural logarithm"],
  ["log2", "Base 2 logarithm"],
  ["log10", "Base 10 logarithm"],
];

const SAMPLE_FUNCTIONS = [
  ["input_contains", "Checks if input contains a regular expression"],
  ["target_contains", "Checks if target contains a regular expression"],
];

/**
 * Makes sure that the filter expression is a single line.
 * @param {import("@codemirror/state").Transaction} tr - The transaction to join lines in.
 * @returns {import("@codemirror/state").TransactionSpec} The transaction with joined lines, if any.
 */
const joinLines = (tr) => {
  if (tr.newDoc.toString().includes("\n")) {
    const newContent = tr.newDoc.toString().replace(/\n/g, " ").trim();
    return {
      changes: { from: 0, to: tr.startState.doc.length, insert: newContent },
      selection: { anchor: newContent.length },
    };
  }
  return tr;
};

// Based on CodeMirror default theme: https://codemirror.net/5/lib/codemirror.css
const highlightStyle = HighlightStyle.define([
  { tag: tags.string, color: "#a11" },
  { tag: tags.number, color: "#164" },
  { tag: tags.keyword, color: "#708" },
  { tag: tags.function(tags.variableName), color: "#00c" },
]);

const simpleHighlighter = StreamLanguage.define({
  token(stream) {
    const wordsRe = (words) => new RegExp(`^(${words.join("|")})\\b`);
    const functions = [...MATH_FUNCTIONS, ...SAMPLE_FUNCTIONS].map(
      ([label]) => label,
    );
    if (stream.match(/"[^"]*"/)) return "string";
    if (stream.match(/^-?\d*\.?\d+/)) return "number";
    if (stream.match(wordsRe(KEYWORDS))) return "keyword";
    if (stream.match(wordsRe(functions))) return "function";
    stream.next();
    return null;
  },
  tokenTable: {
    function: tags.function(tags.variableName),
  },
});

/**
 * @param {import("@codemirror/autocomplete").CompletionContext} context
 * @param {import("../../samples/tools/filters.mjs").ScoreFilterItem[]} filterItems
 * @returns {import("@codemirror/autocomplete").CompletionResult}
 */
function getCompletions(context, filterItems) {
  let word = context.matchBefore(/\w*/);
  if (word.from == word.to && !context.explicit) return null;

  /** @type {import("@codemirror/autocomplete").Completion[]} */
  const keywordCompletions = KEYWORDS.map((k) => ({
    label: k,
    type: "keyword",
    boost: -20,
  }));
  /** @type {import("@codemirror/autocomplete").Completion[]} */
  const mathFunctionCompletions = MATH_FUNCTIONS.map(([label, info]) => ({
    label,
    type: "function",
    info,
    boost: -10,
  }));
  /** @type {import("@codemirror/autocomplete").Completion[]} */
  const sampleFunctionCompletions = SAMPLE_FUNCTIONS.map(([label, info]) => ({
    label,
    type: "function",
    info,
    boost: 0,
  }));
  /** @type {import("@codemirror/autocomplete").Completion[]} */
  const variableCompletions = filterItems.map((item) => ({
    label: item.canonicalName,
    type: "variable",
    info: item.tooltip,
    boost: 20,
  }));
  return {
    from: word.from,
    options: [
      ...keywordCompletions,
      ...mathFunctionCompletions,
      ...sampleFunctionCompletions,
      ...variableCompletions,
    ],
  };
}

/**
 * @param {import("codemirror").EditorView} view
 * @param {import("./filters.mjs").FilterError | undefined} filterError
 * @returns {import("@codemirror/lint").Diagnostic[]}
 */
function getLints(view, filterError) {
  if (!filterError) return [];
  return [
    {
      from: filterError.from || 0,
      to: filterError.to || view.state.doc.length,
      severity: filterError.severity,
      message: filterError.message,
    },
  ];
}

// Emulate `form-control` style to make it look like a text input.
const editorTheme = EditorView.theme({
  "&": {
    fontSize: "inherit",
    color: "var(--bs-body-color)",
    backgroundColor: "var(--bs-body-bg)",
    border: "1px solid var(--bs-border-color)",
    borderRadius: "var(--bs-border-radius)",
  },
  "&.cm-focused": {
    outline: "none",
    borderColor: "#86b7fe",
    boxShadow: "0 0 0 0.25rem rgba(13, 110, 253, 0.25)",
  },
});

/**
 * Renders the Sample Filter Control
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} props.evalDescriptor
 * @param {(filter: import("../../Types.mjs").ScoreFilter) => void} props.filterChanged - Filter changed function
 * @param {import("../../Types.mjs").ScoreFilter} props.filter - Capabilities of the application host
 * @param {import("./filters.mjs").FilterError | undefined} props.filterError - The error in the filter expression, if any.
 * @returns {import("preact").JSX.Element | string} The TranscriptView component.
 */
export const SampleFilter = ({
  evalDescriptor,
  filter,
  filterError,
  filterChanged,
}) => {
  const editorRef = useRef(/** @type {HTMLElement|null} */ (null));
  const editorViewRef = useRef(
    /** @type {import("codemirror").EditorView|null} */ (null),
  );
  const lastFilterRef = useRef(/** @type {string|null} */ (null));
  const linterCompartment = useRef(new Compartment());
  const autocompletionCompartment = useRef(new Compartment());
  const filterItems = useMemo(
    () => scoreFilterItems(evalDescriptor),
    [evalDescriptor],
  );

  // Initialize editor when component mounts
  useEffect(() => {
    editorViewRef.current?.destroy();
    editorViewRef.current = new EditorView({
      parent: editorRef.current,
      state: EditorState.create({
        doc: filter.value || "",
        extensions: [
          minimalSetup,
          bracketMatching(),
          editorTheme,
          EditorState.transactionFilter.of(joinLines),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              const newFilter = update.state.doc.toString();
              lastFilterRef.current = newFilter;
              filterChanged({ value: newFilter });
            }
          }),
          simpleHighlighter,
          syntaxHighlighting(highlightStyle),
          autocompletionCompartment.current.of(
            autocompletion({
              override: [(context) => getCompletions(context, filterItems)],
            }),
          ),
          linterCompartment.current.of(
            linter((view) => getLints(view, filterError)),
          ),
        ],
      }),
    });
    return () => {
      editorViewRef.current?.destroy();
    };
  }, []);

  useEffect(() => {
    if (editorViewRef.current && filter.value !== lastFilterRef.current) {
      lastFilterRef.current = filter.value;
      editorViewRef.current.dispatch({
        changes: {
          from: 0,
          to: editorViewRef.current.state.doc.length,
          insert: filter.value || "",
        },
      });
      editorViewRef.current.focus();
      editorViewRef.current.dispatch({
        selection: { anchor: editorViewRef.current.state.doc.length },
      });
    }
  }, [filter.value]);

  useEffect(() => {
    if (editorViewRef.current) {
      editorViewRef.current.dispatch({
        effects: autocompletionCompartment.current.reconfigure(
          autocompletion({
            override: [(context) => getCompletions(context, filterItems)],
          }),
        ),
      });
    }
  }, [filterItems]);

  useEffect(() => {
    if (editorViewRef.current) {
      editorViewRef.current.dispatch({
        effects: linterCompartment.current.reconfigure(
          linter((view) => getLints(view, filterError)),
        ),
      });
    }
  }, [filterError]);

  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="sample-filter-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Filter:</span
      >
      <div ref=${editorRef} style=${{ width: "300px" }}></div>
      <span
        class="bi bi-info-circle"
        style=${{
          position: "relative",
          marginLeft: "0.5em",
          cursor: "help",
          alignSelf: "center",
        }}
        data-tooltip=${filterTooltip}
        data-tooltip-position="bottom-left"
      ></span>
    </div>
  `;
};

const filterTooltip = `
Filter samples by:
  • Scores (click on the score name above to add it to the filter)
  • Input and target regex search: input_contains, target_contains
Supported expressions:
  • Arithmetic: +, -, *, /, mod, ^
  • Comparison: <, <=, >, >=, ==, !=, including chain comparisons, e.g. “10 <= x < 20”
  • Boolean: and, or, not
  • Regex matching: ~= (case-sensitive)
  • Set operations: in, not in; e.g. “x in (2, 3, 5)”
  • Functions: min, max, abs, round, floor, ceil, sqrt, log, log2, log10
`.trim();
