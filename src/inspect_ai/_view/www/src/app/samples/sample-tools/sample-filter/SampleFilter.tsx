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
import { FC, useCallback, useEffect, useMemo, useRef } from "react";

import { useEvalDescriptor } from "../../../../state/hooks";
import { useStore } from "../../../../state/store";
import { debounce } from "../../../../utils/sync";
import { FilterError } from "../../../types";
import { sampleFilterItems } from "../filters";
import { getCompletions } from "./completions";
import styles from "./SampleFilter.module.css";
import { language } from "./tokenize";

interface SampleFilterProps {}

// Constants
const FILTER_TOOLTIP = `
Filter samples by:
  • Scores
  • Samples with errors: has_error
  • Input, target and error regex search: input_contains, target_contains, error_contains
  • Samples that have been retried: has_retries

Supported expressions:
  • Arithmetic: +, -, *, /, mod, ^
  • Comparison: <, <=, >, >=, ==, !=, including chain comparisons, e.g. "10 <= x < 20"
  • Boolean: and, or, not
  • Regex matching: ~= (case-sensitive)
  • Set operations: in, not in; e.g. "x in (2, 3, 5)"
  • Functions: min, max, abs, round, floor, ceil, sqrt, log, log2, log10
`.trim();

// Styles
const highlightStyle = HighlightStyle.define([
  { tag: tags.string, class: "token string" },
  { tag: tags.number, class: "token number" },
  { tag: tags.keyword, class: "token keyword" },
]);

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

const ensureOneLine = (tr: Transaction): TransactionSpec => {
  const newDoc = tr.newDoc.toString();
  if (!newDoc.includes("\n")) return tr;

  if (tr.isUserEvent("input.paste")) {
    return {
      changes: {
        from: 0,
        to: tr.startState.doc.length,
        insert: newDoc.replace(/\n/g, " ").trim(),
      },
    };
  }
  return {};
};

const getLints = (
  view: EditorView,
  filterError?: FilterError,
): Diagnostic[] => {
  if (!filterError) return [];
  return [
    {
      from: Math.min(filterError.from || 0, view.state.doc.length),
      to: Math.min(
        filterError.to || view.state.doc.length,
        view.state.doc.length,
      ),
      severity: filterError.severity,
      message: filterError.message,
    },
  ];
};

// Main component
export const SampleFilter: FC<SampleFilterProps> = () => {
  const editorRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView>(null);
  const linterCompartment = useRef<Compartment>(new Compartment());
  const autocompletionCompartment = useRef<Compartment>(new Compartment());
  const updateListenerCompartment = useRef<Compartment>(new Compartment());
  const evalDescriptor = useEvalDescriptor();

  const filterItems = useMemo(
    () => (evalDescriptor ? sampleFilterItems(evalDescriptor) : []),
    [evalDescriptor],
  );

  const filter = useStore((state) => state.log.filter);
  const filterError = useStore((state) => state.log.filterError);
  const setFilter = useStore((state) => state.logActions.setFilter);

  const handleFocus = useCallback((event: FocusEvent, view: EditorView) => {
    if (event.isTrusted && view.state.doc.toString() === "") {
      setTimeout(() => startCompletion(view), 0);
    }
  }, []);

  const makeAutocompletion = useCallback(
    () =>
      autocompletion({
        override: [(context) => getCompletions(context, filterItems)],
        activateOnCompletion: (c) => c.label.endsWith(" "),
      }),
    [],
  );

  const makeLinter = useCallback(
    () => linter((view) => getLints(view, filterError)),
    [filterError],
  );

  const debounceSetFilter = useCallback(
    debounce((value: string) => {
      setFilter(value);
    }, 200),
    [setFilter],
  );

  const makeUpdateListener = useCallback(
    () =>
      EditorView.updateListener.of((update) => {
        if (update.docChanged && evalDescriptor) {
          const newValue = update.state.doc.toString();
          debounceSetFilter(newValue);
        }
      }),
    [setFilter],
  );

  // Initialize editor
  useEffect(() => {
    editorViewRef.current?.destroy();

    editorViewRef.current = new EditorView({
      parent: editorRef.current ?? undefined,
      state: EditorState.create({
        doc: filter || "",
        extensions: [
          minimalSetup,
          bracketMatching(),
          editorTheme,
          EditorState.transactionFilter.of(ensureOneLine),
          updateListenerCompartment.current.of(makeUpdateListener()),
          EditorView.domEventHandlers({ focus: handleFocus }),
          language,
          syntaxHighlighting(highlightStyle),
          autocompletionCompartment.current.of(makeAutocompletion()),
          linterCompartment.current.of(makeLinter()),
        ],
      }),
    });

    return () => editorViewRef.current?.destroy();
  }, []);

  // Handle filter value changes
  useEffect(() => {
    if (!editorViewRef.current) return;

    const currentValue = editorViewRef.current.state.doc.toString();
    if (filter === currentValue) return;

    editorViewRef.current.dispatch({
      changes: {
        from: 0,
        to: currentValue.length,
        insert: filter || "",
      },
    });
  }, [filter]);

  // Update compartments when dependencies change
  useEffect(() => {
    editorViewRef.current?.dispatch({
      effects:
        updateListenerCompartment.current.reconfigure(makeUpdateListener()),
    });
  }, [evalDescriptor]);

  useEffect(() => {
    editorViewRef.current?.dispatch({
      effects:
        autocompletionCompartment.current.reconfigure(makeAutocompletion()),
    });
  }, [filterItems]);

  useEffect(() => {
    editorViewRef.current?.dispatch({
      effects: linterCompartment.current.reconfigure(makeLinter()),
    });
  }, [filterError]);

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
        className={clsx(filterError && "filter-pending", styles.input)}
      />
      <span
        className={clsx("bi", "bi-question-circle", styles.help)}
        data-tooltip={FILTER_TOOLTIP}
        data-tooltip-position="bottom-left"
      />
    </div>
  );
};
