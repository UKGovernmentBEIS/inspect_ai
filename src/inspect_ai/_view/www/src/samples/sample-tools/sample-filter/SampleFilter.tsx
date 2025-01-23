import { autocompletion, startCompletion } from "@codemirror/autocomplete";
import {
  bracketMatching,
  HighlightStyle,
  syntaxHighlighting,
} from "@codemirror/language";
import { Diagnostic, linter } from "@codemirror/lint";
import {
  Compartment,
  EditorState,
  Transaction,
  TransactionSpec,
} from "@codemirror/state";
import { tags } from "@lezer/highlight";
import clsx from "clsx";
import { EditorView, minimalSetup } from "codemirror";
import { useEffect, useMemo, useRef, useState } from "react";
import { ScoreFilter } from "../../../Types.mjs";
import { EvalDescriptor } from "../../SamplesDescriptor.mjs";
import { FilterError, filterSamples, scoreFilterItems } from "../filters";
import { getCompletions } from "./completions";
import { language } from "./tokenize";

import styles from "./SampleFilter.module.css";

interface FilteringResult {
  numSamples: number;
  error?: FilterError;
}

/**
 * Makes sure that the filter expression is a single line.
 */
function ensureOneLine(tr: Transaction): TransactionSpec {
  const newDoc = tr.newDoc.toString();
  if (newDoc.includes("\n")) {
    if (tr.isUserEvent("input.paste")) {
      const newDocAdjusted = newDoc.replace(/\n/g, " ").trim();
      return {
        changes: {
          from: 0,
          to: tr.startState.doc.length,
          insert: newDocAdjusted,
        },
      };
    } else {
      return {};
    }
  }
  return tr;
}

const highlightStyle = HighlightStyle.define([
  { tag: tags.string, class: "token string" },
  { tag: tags.number, class: "token number" },
  { tag: tags.keyword, class: "token keyword" },
]);

function getLints(view: EditorView, filterError?: FilterError): Diagnostic[] {
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
    color: "var(--inspect-input-foreground)",
    backgroundColor: "var(--inspect-input-background)",
    border: "1px solid var(--inspect-input-border)",
    borderRadius: "var(--bs-border-radius)",
  },
  ".cm-cursor.cm-cursor-primary": {
    borderLeftColor: "var(--bs-body-color)",
  },
  ".cm-selectionBackground": {
    backgroundColor: "var(--inspect-inactive-selection-background)",
  },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer > .cm-selectionBackground":
    {
      backgroundColor: "var(--inspect-active-selection-background)",
    },
  "&.cm-focused": {
    outline: "none",
    borderColor: "var(--inspect-focus-border-color)",
    boxShadow: "var(--inspect-focus-border-shadow)",
  },
  ".filter-pending > &.cm-focused": {
    borderColor: "var(--inspect-focus-border-gray-color)",
    boxShadow: "var(--inspect-focus-border-gray-shadow)",
  },
  ".cm-tooltip": {
    backgroundColor: "var(--bs-light)",
    border: "1px solid var(--bs-border-color)",
    color: "var(--bs-body-color)",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li": {
    color: "var(--bs-body-color)",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "var(--inspect-active-selection-background)",
    color: "var(--bs-body-color)",
  },
  ".cm-scroller": {
    overflow: "hidden",
  },
});

const getFilteringResult = (
  evalDescriptor: EvalDescriptor,
  filterValue: string,
): FilteringResult => {
  const { result, error } = filterSamples(
    evalDescriptor,
    evalDescriptor.samples,
    filterValue,
  );
  return { numSamples: result.length, error };
};

interface SampleFilterProps {
  evalDescriptor: EvalDescriptor;
  filter: ScoreFilter;
  filterChanged: (filter: ScoreFilter) => void;
}
/**
 * Renders the Sample Filter Control
 */
export const SampleFilter: React.FC<SampleFilterProps> = ({
  evalDescriptor,
  filter,
  filterChanged,
}) => {
  const editorRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView>(null);
  const linterCompartment = useRef<Compartment>(new Compartment());
  const autocompletionCompartment = useRef<Compartment>(new Compartment());
  const updateListenerCompartment = useRef<Compartment>(new Compartment());
  const filterItems = useMemo(
    () => scoreFilterItems(evalDescriptor),
    [evalDescriptor],
  );
  // Result of applying the filter expression in the editor, which might be
  // different from the active filter.
  const [filteringResultInstant, setFilteringResultInstant] =
    useState<FilteringResult | null>(null);

  const handleFocus = (event: FocusEvent, view: EditorView) => {
    if (event.isTrusted && view.state.doc.toString() === "") {
      setTimeout(() => startCompletion(view), 0);
    }
  };

  const makeAutocompletion = () =>
    autocompletion({
      override: [(context) => getCompletions(context, filterItems)],
      activateOnCompletion: (c) => c.label.endsWith(" "), // see autoSpaceAfter
    });
  const makeLinter = () =>
    // CodeMirror debounces the linter, so even instant error updates are not annoying
    linter((view) => getLints(view, filteringResultInstant?.error));
  const makeUpdateListener = () =>
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        const newValue = update.state.doc.toString();
        const filteringResult = getFilteringResult(evalDescriptor, newValue);
        if (!filteringResult.error) {
          filterChanged({ value: newValue });
        }
        setFilteringResultInstant(filteringResult);
      }
    });

  // Initialize editor when component mounts
  useEffect(() => {
    editorViewRef.current?.destroy();
    editorViewRef.current = new EditorView({
      parent: editorRef.current !== null ? editorRef.current : undefined,
      state: EditorState.create({
        doc: filter.value || "",
        extensions: [
          minimalSetup,
          bracketMatching(),
          editorTheme,
          EditorState.transactionFilter.of(ensureOneLine),
          updateListenerCompartment.current.of(makeUpdateListener()),
          EditorView.domEventHandlers({
            focus: handleFocus,
          }),
          language,
          syntaxHighlighting(highlightStyle),
          autocompletionCompartment.current.of(makeAutocompletion()),
          linterCompartment.current.of(makeLinter()),
        ],
      }),
    });
    return () => {
      editorViewRef.current?.destroy();
    };
  }, []);

  useEffect(() => {
    if (
      editorViewRef.current &&
      filter.value !== editorViewRef.current.state.doc.toString()
    ) {
      setFilteringResultInstant(
        getFilteringResult(evalDescriptor, filter.value || ""),
      );
      editorViewRef.current.dispatch({
        changes: {
          from: 0,
          to: editorViewRef.current.state.doc.length,
          insert: filter.value || "",
        },
      });
    }
  }, [evalDescriptor, filter.value]);

  useEffect(() => {
    if (editorViewRef.current) {
      editorViewRef.current.dispatch({
        effects:
          updateListenerCompartment.current.reconfigure(makeUpdateListener()),
      });
    }
  }, [evalDescriptor]);

  useEffect(() => {
    if (editorViewRef.current) {
      editorViewRef.current.dispatch({
        effects:
          autocompletionCompartment.current.reconfigure(makeAutocompletion()),
      });
    }
  }, [filterItems]);

  useEffect(() => {
    if (editorViewRef.current) {
      editorViewRef.current.dispatch({
        effects: linterCompartment.current.reconfigure(makeLinter()),
      });
    }
  }, [filteringResultInstant?.error]);

  return (
    <div style={{ display: "flex" }}>
      <span
        className={clsx(
          "sample-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles.label,
        )}
      >
        Filter:
      </span>
      <div
        ref={editorRef}
        className={clsx(
          filteringResultInstant?.error ? ["filter-pending"] : [],
          styles.input,
        )}
      ></div>
      <span
        className={clsx("bi", "bi-question-circle", styles.help)}
        data-tooltip={filterTooltip}
        data-tooltip-position="bottom-left"
      ></span>
    </div>
  );
};

const filterTooltip = `
Filter samples by:
  • Scores
  • Input and target regex search: input_contains, target_contains

Supported expressions:
  • Arithmetic: +, -, *, /, mod, ^
  • Comparison: <, <=, >, >=, ==, !=, including chain comparisons, e.g. “10 <= x < 20”
  • Boolean: and, or, not
  • Regex matching: ~= (case-sensitive)
  • Set operations: in, not in; e.g. “x in (2, 3, 5)”
  • Functions: min, max, abs, round, floor, ceil, sqrt, log, log2, log10
`.trim();
