import { i as __toESM } from "./rolldown-runtime.js";
import { n as require_react, r as require_jsx_runtime, t as require_compiler_runtime } from "./compiler-runtime.js";
//#region ../../packages/util/src/object.ts
var printObject = (val, size = 50) => {
	const envelope = ["{", "}"];
	const ellipsis = "…";
	const separator = ", ";
	const kvSeparator = ": ";
	let remainingSize = size - (envelope[0]?.length || 0) - (envelope[1]?.length || 0);
	const entries = Object.entries(val);
	const headItems = [];
	const tailItems = [];
	let headIdx = 0;
	let tailIdx = entries.length - 1;
	while (headIdx <= tailIdx) {
		const headPair = `${entries[headIdx]?.[0]}${kvSeparator}${JSON.stringify(entries[headIdx]?.[1])}`;
		const tailPair = `${entries[tailIdx]?.[0]}${kvSeparator}${JSON.stringify(entries[tailIdx]?.[1])}`;
		if (headIdx === tailIdx) {
			if (headPair.length <= remainingSize) headItems.push(headPair);
			else headItems.push(ellipsis);
			break;
		}
		const bothSize = headPair.length + tailPair.length + 2;
		if (bothSize <= remainingSize) {
			headItems.push(headPair);
			tailItems.unshift(tailPair);
			remainingSize -= bothSize;
			headIdx++;
			tailIdx--;
		} else if (headPair.length + 2 + 1 <= remainingSize) {
			headItems.push(headPair);
			headItems.push(ellipsis);
			break;
		} else {
			headItems.push(ellipsis);
			break;
		}
	}
	if (headItems.length === 0 && entries.length > 0) {
		const firstPair = `${entries[0]?.[0]}${kvSeparator}${JSON.stringify(entries[0]?.[1])}`;
		const truncateSize = remainingSize - 1 - 2;
		if (truncateSize > 0) {
			headItems.push(firstPair.slice(0, truncateSize) + ellipsis);
			headItems.push(ellipsis);
		} else headItems.push(ellipsis);
	}
	const allItems = [...headItems, ...tailItems];
	return envelope[0] + allItems.join(separator) + envelope[1];
};
/**
* Own-property read of a string-keyed record. Plain indexing walks the
* prototype chain, so a key taken from untrusted data (a log's uuid, score
* name, attachment id, ...) that happens to be `constructor`, `toString` or
* `__proto__` resolves to a builtin instead of "absent"; this returns
* `undefined` for any key the record does not own.
*/ var getOwn = (record, key) => record !== void 0 && Object.hasOwn(record, key) ? record[key] : void 0;
/**
* Record with a null prototype built from a Map. `Object.fromEntries` alone
* only makes *present* keys own properties; an absent prototype-named key
* would still resolve through Object.prototype at read sites, and a present
* `__proto__` key could not be assigned onto a plain object at all.
*/ var nullProtoRecord = (entries) => {
	const record = Object.fromEntries(entries);
	Object.setPrototypeOf(record, null);
	return record;
};
//#endregion
//#region ../../node_modules/.pnpm/clsx@2.1.1/node_modules/clsx/dist/clsx.mjs
var import_jsx_runtime = require_jsx_runtime();
var import_compiler_runtime = require_compiler_runtime();
function r(e) {
	var t, f, n = "";
	if ("string" == typeof e || "number" == typeof e) n += e;
	else if ("object" == typeof e) if (Array.isArray(e)) {
		var o = e.length;
		for (t = 0; t < o; t++) e[t] && (f = r(e[t])) && (n && (n += " "), n += f);
	} else for (f in e) e[f] && (n && (n += " "), n += f);
	return n;
}
function clsx() {
	for (var e, t, f = 0, n = "", o = arguments.length; f < o; f++) (e = arguments[f]) && (t = r(e)) && (n && (n += " "), n += t);
	return n;
}
//#endregion
//#region ../../node_modules/.pnpm/bootstrap-icons@1.13.2/node_modules/bootstrap-icons/font/bootstrap-icons.css
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
//#endregion
//#region ../../packages/react/src/icons/icons.ts
/**
* Every icon the apps and shared packages render, keyed by meaning. Values
* are Bootstrap Icons classes, except the search toggles (Codicons, to match
* VS Code's find widget) and the `ii` classes (our own SVGs, see icons.css).
*/ var iconClasses = {
	activity: "bi bi-activity",
	add: "bi bi-plus-lg",
	agent: "bi bi-grid",
	approvalApprove: "bi bi-shield-check",
	approvalEscalate: "bi bi-box-arrow-up",
	approvalModify: "bi bi-pencil-square",
	approvalReject: "bi bi-shield-x",
	approvalTerminate: "bi bi-shield-exclamation",
	approve: "bi bi-shield",
	arrowDown: "bi bi-arrow-down",
	arrowDownUp: "bi bi-arrow-down-up",
	arrowRight: "bi bi-arrow-right",
	arrowUp: "bi bi-arrow-up",
	cancel: "bi bi-x-circle",
	changeAdd: "bi bi-plus",
	changeRemove: "bi bi-dash",
	checkboxChecked: "bi bi-check-circle",
	checkboxUnchecked: "bi bi-circle",
	checkpoint: "bi bi-bookmark-check-fill",
	chevronDown: "bi bi-chevron-down",
	chevronLeft: "bi bi-chevron-left",
	chevronRight: "bi bi-chevron-right",
	chevronUp: "bi bi-chevron-up",
	clearText: "bi bi-x-circle-fill",
	close: "bi bi-x",
	closeLarge: "bi bi-x-lg",
	code: "bi bi-code-slash",
	codeSquare: "bi bi-code-square",
	collapseAll: "bi bi-arrows-collapse",
	columns: "bi bi-layout-three-columns",
	compaction: "bi bi-arrows-collapse-vertical",
	computer: "bi bi-display",
	config: "bi bi-gear",
	confirm: "bi bi-check",
	copy: "bi bi-copy",
	display: "bi bi-card-text",
	download: "bi bi-download",
	edit: "bi bi-pencil-square",
	error: "bi bi-exclamation-circle-fill",
	exclamation: "bi bi-exclamation",
	expandAll: "bi bi-arrows-expand",
	file: "bi bi-file-code",
	fileImage: "bi bi-file-image",
	filePdf: "bi bi-file-pdf",
	fileText: "bi bi-file-earmark-text",
	fileUnknown: "bi bi-file-earmark",
	filter: "bi bi-funnel",
	flag: "bi bi-flag-fill",
	flow: "ii inspect-flow",
	focusEnter: "bi bi-arrows-angle-expand",
	focusExit: "bi bi-arrows-angle-contract",
	folder: "bi bi-folder",
	fork: "bi bi-sign-intersection-y-fill",
	globe: "bi bi-globe2",
	graph: "bi bi-graph-up",
	gridView: "bi bi-grid-3x3-gap",
	help: "bi bi-question-circle",
	highlight: "bi bi-highlighter",
	history: "bi bi-clock-history",
	info: "bi bi-info-circle",
	input: "bi bi-terminal",
	inspectFile: "ii inspect-icon-file",
	interrupt: "bi bi-slash-circle",
	lightbulb: "bi bi-lightbulb",
	limitCost: "bi bi-currency-dollar",
	limitCustom: "bi bi-exclamation-triangle",
	limitExecution: "bi bi-stopwatch",
	limitMessages: "bi bi-chat-right-text",
	limitOperator: "bi bi-person-workspace",
	limitTime: "bi bi-clock",
	limitTokens: "bi bi-list",
	limitTurns: "bi bi-arrow-repeat",
	link: "bi bi-link-45deg",
	listCheck: "bi bi-list-check",
	listView: "bi bi-list-ul",
	loading: "bi bi-arrow-clockwise",
	logCritical: "bi bi-fire",
	logDebug: "bi bi-bug",
	logError: "bi bi-x-circle",
	logHttp: "bi bi-download",
	logInfo: "bi bi-info-square",
	logNotset: "bi bi-card-text",
	logWarning: "bi bi-exclamation-triangle",
	matchCase: "codicon codicon-case-sensitive",
	matchRegex: "codicon codicon-regex",
	matchWholeWord: "codicon codicon-whole-word",
	metrics: "bi bi-clipboard-data",
	model: "bi bi-grid-3x3-gap",
	move: "bi bi-box-arrow-right",
	navBack: "ii inspect-icon-back",
	navForward: "ii inspect-icon-forward",
	navHome: "ii inspect-icon-home",
	navTasks: "ii inspect-icon-tasks",
	next: "bi bi-chevron-right",
	noSamples: "bi bi-ban",
	options: "bi bi-gear",
	pencil: "bi bi-pencil",
	pendingTask: "bi bi-clock-fill",
	pendingTaskSubtle: "bi bi-clock",
	people: "bi bi-people",
	play: "bi bi-play-fill",
	playCircle: "bi bi-play-circle-fill",
	plug: "bi bi-plug",
	previous: "bi bi-chevron-left",
	print: "bi bi-printer",
	refresh: "bi bi-arrow-clockwise",
	refuse: "bi bi-ban",
	retry: "bi bi-arrow-repeat",
	running: "bi bi-stars",
	sample: "bi bi-database",
	samples: "bi bi-file-spreadsheet",
	sandbox: "bi bi-box-seam",
	scanner: "bi bi-radar",
	scorer: "bi bi-calculator",
	search: "bi bi-search",
	selectionChecked: "bi bi-check-lg",
	selectionClear: "bi bi-x-lg",
	selectionSelect: "bi bi-square",
	selectionSelecting: "bi bi-check2-square",
	sentinel: "bi bi-binoculars",
	sentinelFill: "bi bi-binoculars-fill",
	sidebar: "bi bi-list",
	signpost: "bi bi-signpost-split",
	solverDefault: "bi bi-arrow-return-right",
	solverUseTools: "bi bi-tools",
	sortDown: "bi bi-sort-down",
	sortUp: "bi bi-sort-up",
	success: "bi bi-check-circle-fill",
	successSubtle: "bi bi-check-circle",
	terminal: "bi bi-terminal",
	themeDark: "bi bi-moon-stars-fill",
	themeLight: "bi bi-sun-fill",
	threeDots: "bi bi-three-dots",
	toggleOff: "bi bi-toggle2-off",
	toggleOn: "bi bi-toggle-on",
	tools: "bi bi-tools",
	transcript: "bi bi-list-columns-reverse",
	trash: "bi bi-trash",
	treeClosed: "bi bi-caret-right-fill",
	treeOpen: "bi bi-caret-down-fill",
	validation: "bi bi-patch-check",
	warning: "bi bi-exclamation-triangle",
	window: "bi bi-window",
	wrap: "bi bi-text-wrap"
};
var kLogLevelIcons = nullProtoRecord(/* @__PURE__ */ new Map([
	["notset", "logNotset"],
	["debug", "logDebug"],
	["http", "logHttp"],
	["info", "logInfo"],
	["warning", "logWarning"],
	["error", "logError"],
	["critical", "logCritical"]
]));
/** Icon for a logger level; `undefined` for a level we don't recognise. */ var logLevelIcon = (level) => kLogLevelIcons[level.toLowerCase()];
var iconForMimeType = (mimeType) => {
	if (mimeType === "application/pdf") return "filePdf";
	else if (mimeType.startsWith("image/")) return "fileImage";
	else return "fileUnknown";
};
//#endregion
//#region ../../packages/react/src/icons/Icon.tsx
/** Decorative by default; pass `aria-hidden={false}` with an `aria-label` when the icon carries meaning on its own. */ var Icon = (t0) => {
	const $ = (0, import_compiler_runtime.c)(10);
	let className;
	let name;
	let rest;
	if ($[0] !== t0) {
		({name, className, ...rest} = t0);
		$[0] = t0;
		$[1] = className;
		$[2] = name;
		$[3] = rest;
	} else {
		className = $[1];
		name = $[2];
		rest = $[3];
	}
	const t1 = iconClasses[name];
	let t2;
	if ($[4] !== className || $[5] !== t1) {
		t2 = clsx(t1, className);
		$[4] = className;
		$[5] = t1;
		$[6] = t2;
	} else t2 = $[6];
	let t3;
	if ($[7] !== rest || $[8] !== t2) {
		t3 = /*#__PURE__*/ (0, import_jsx_runtime.jsx)("i", {
			"aria-hidden": "true",
			...rest,
			className: t2
		});
		$[7] = rest;
		$[8] = t2;
		$[9] = t3;
	} else t3 = $[9];
	return t3;
};
var AnsiDisplay_module_default = {
	ansiDisplayContainer: "_ansiDisplayContainer_33le5_1",
	ansiDisplay: "_ansiDisplay_33le5_1",
	ansiDisplayRaw: "_ansiDisplayRaw_33le5_28",
	"ansi-display-run-blink": "_ansi-display-run-blink_33le5_1"
};
var ToolButton_module_default = {
	toolButton: "_toolButton_1nf6j_1",
	marginRight: "_marginRight_1nf6j_7",
	subtle: "_subtle_1nf6j_19",
	latched: "_latched_1nf6j_23",
	collapsibleLabel: "_collapsibleLabel_1nf6j_31"
};
//#endregion
//#region ../../packages/react/src/components/ToolButton.tsx
var ToolButton = /*#__PURE__*/ (0, import_react.forwardRef)((t0, ref) => {
	const $ = (0, import_compiler_runtime.c)(33);
	let className;
	let collapseLabel;
	let icon;
	let label;
	let latched;
	let rest;
	let subtle;
	let t1;
	let title;
	if ($[0] !== t0) {
		({label, classes: t1, icon, className, latched, subtle, collapseLabel, title, ...rest} = t0);
		$[0] = t0;
		$[1] = className;
		$[2] = collapseLabel;
		$[3] = icon;
		$[4] = label;
		$[5] = latched;
		$[6] = rest;
		$[7] = subtle;
		$[8] = t1;
		$[9] = title;
	} else {
		className = $[1];
		collapseLabel = $[2];
		icon = $[3];
		label = $[4];
		latched = $[5];
		rest = $[6];
		subtle = $[7];
		t1 = $[8];
		title = $[9];
	}
	const classes = t1 === void 0 ? "" : t1;
	const t2 = latched ? ToolButton_module_default.latched : void 0;
	const t3 = subtle ? ToolButton_module_default.subtle : void 0;
	let t4;
	if ($[10] !== className || $[11] !== classes || $[12] !== t2 || $[13] !== t3) {
		t4 = clsx("btn", "btn-tools", ToolButton_module_default.toolButton, classes, className, t2, t3);
		$[10] = className;
		$[11] = classes;
		$[12] = t2;
		$[13] = t3;
		$[14] = t4;
	} else t4 = $[14];
	let t5;
	if ($[15] !== collapseLabel || $[16] !== label || $[17] !== title) {
		t5 = title ?? (collapseLabel ? labelTitle(label) : void 0);
		$[15] = collapseLabel;
		$[16] = label;
		$[17] = title;
		$[18] = t5;
	} else t5 = $[18];
	let t6;
	if ($[19] !== collapseLabel || $[20] !== icon || $[21] !== label) {
		t6 = icon && /*#__PURE__*/ (0, import_jsx_runtime.jsx)(Icon, {
			name: icon,
			className: label && !collapseLabel ? ToolButton_module_default.marginRight : void 0
		});
		$[19] = collapseLabel;
		$[20] = icon;
		$[21] = label;
		$[22] = t6;
	} else t6 = $[22];
	let t7;
	if ($[23] !== collapseLabel || $[24] !== label) {
		t7 = collapseLabel && label ? /*#__PURE__*/ (0, import_jsx_runtime.jsx)("span", {
			className: ToolButton_module_default.collapsibleLabel,
			children: label
		}) : label;
		$[23] = collapseLabel;
		$[24] = label;
		$[25] = t7;
	} else t7 = $[25];
	let t8;
	if ($[26] !== ref || $[27] !== rest || $[28] !== t4 || $[29] !== t5 || $[30] !== t6 || $[31] !== t7) {
		t8 = /*#__PURE__*/ (0, import_jsx_runtime.jsxs)("button", {
			ref,
			type: "button",
			className: t4,
			title: t5,
			...rest,
			children: [t6, t7]
		});
		$[26] = ref;
		$[27] = rest;
		$[28] = t4;
		$[29] = t5;
		$[30] = t6;
		$[31] = t7;
		$[32] = t8;
	} else t8 = $[32];
	return t8;
});
var labelTitle = (label) => typeof label === "string" ? label : void 0;
ToolButton.displayName = "ToolButton";
//#endregion
export { logLevelIcon as a, nullProtoRecord as c, iconForMimeType as i, printObject as l, AnsiDisplay_module_default as n, clsx as o, Icon as r, getOwn as s, ToolButton as t };

//# sourceMappingURL=ToolButton.js.map