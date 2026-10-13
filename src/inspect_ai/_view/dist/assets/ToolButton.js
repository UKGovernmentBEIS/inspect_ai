import { i as __toESM } from "./rolldown-runtime.js";
import { n as require_react, r as require_jsx_runtime, t as require_compiler_runtime } from "./compiler-runtime.js";
//#region ../../node_modules/.pnpm/clsx@2.1.1/node_modules/clsx/dist/clsx.mjs
var import_jsx_runtime = require_jsx_runtime();
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
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
//#region ../../packages/react/src/components/ComponentIconContext.tsx
var ComponentIconContext = /*#__PURE__*/ (0, import_react.createContext)(null);
var ComponentIconProvider = (t0) => {
	const $ = (0, import_compiler_runtime.c)(3);
	const { icons, children } = t0;
	let t1;
	if ($[0] !== children || $[1] !== icons) {
		t1 = /*#__PURE__*/ (0, import_jsx_runtime.jsx)(ComponentIconContext.Provider, {
			value: icons,
			children
		});
		$[0] = children;
		$[1] = icons;
		$[2] = t1;
	} else t1 = $[2];
	return t1;
};
var useComponentIcons = () => {
	const icons = (0, import_react.useContext)(ComponentIconContext);
	if (!icons) throw new Error("useComponentIcons must be used within a ComponentIconProvider");
	return icons;
};
var AnsiDisplay_module_default = {
	ansiDisplayContainer: "_ansiDisplayContainer_33le5_1",
	ansiDisplay: "_ansiDisplay_33le5_1",
	ansiDisplayRaw: "_ansiDisplayRaw_33le5_28",
	"ansi-display-run-blink": "_ansi-display-run-blink_33le5_1"
};
var ToolButton_module_default = {
	toolButton: "_toolButton_13erz_1",
	marginRight: "_marginRight_13erz_7",
	subtle: "_subtle_13erz_19",
	latched: "_latched_13erz_23"
};
//#endregion
//#region ../../packages/react/src/components/ToolButton.tsx
var ToolButton = /*#__PURE__*/ (0, import_react.forwardRef)((t0, ref) => {
	const $ = (0, import_compiler_runtime.c)(22);
	let className;
	let icon;
	let label;
	let latched;
	let rest;
	let subtle;
	let t1;
	if ($[0] !== t0) {
		({label, classes: t1, icon, className, latched, subtle, ...rest} = t0);
		$[0] = t0;
		$[1] = className;
		$[2] = icon;
		$[3] = label;
		$[4] = latched;
		$[5] = rest;
		$[6] = subtle;
		$[7] = t1;
	} else {
		className = $[1];
		icon = $[2];
		label = $[3];
		latched = $[4];
		rest = $[5];
		subtle = $[6];
		t1 = $[7];
	}
	const classes = t1 === void 0 ? "" : t1;
	const t2 = latched ? ToolButton_module_default.latched : void 0;
	const t3 = subtle ? ToolButton_module_default.subtle : void 0;
	let t4;
	if ($[8] !== className || $[9] !== classes || $[10] !== t2 || $[11] !== t3) {
		t4 = clsx("btn", "btn-tools", ToolButton_module_default.toolButton, classes, className, t2, t3);
		$[8] = className;
		$[9] = classes;
		$[10] = t2;
		$[11] = t3;
		$[12] = t4;
	} else t4 = $[12];
	let t5;
	if ($[13] !== icon || $[14] !== label) {
		t5 = icon && /*#__PURE__*/ (0, import_jsx_runtime.jsx)("i", { className: clsx(icon, label ? ToolButton_module_default.marginRight : void 0) });
		$[13] = icon;
		$[14] = label;
		$[15] = t5;
	} else t5 = $[15];
	let t6;
	if ($[16] !== label || $[17] !== ref || $[18] !== rest || $[19] !== t4 || $[20] !== t5) {
		t6 = /*#__PURE__*/ (0, import_jsx_runtime.jsxs)("button", {
			ref,
			type: "button",
			className: t4,
			...rest,
			children: [t5, label]
		});
		$[16] = label;
		$[17] = ref;
		$[18] = rest;
		$[19] = t4;
		$[20] = t5;
		$[21] = t6;
	} else t6 = $[21];
	return t6;
});
ToolButton.displayName = "ToolButton";
//#endregion
export { clsx as a, useComponentIcons as i, AnsiDisplay_module_default as n, ComponentIconProvider as r, ToolButton as t };

//# sourceMappingURL=ToolButton.js.map