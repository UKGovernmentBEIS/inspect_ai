const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["./lib-CBtriEt5.js","./chunk-DfAF0w94.js","./wgxpath.install-node-Csk64Aj9.js"])))=>i.map(i=>d[i]);
import { n as __exportAll } from "./rolldown-runtime.js";
import { t as __vitePreload } from "./preload-helper.js";
import { t as l } from "./chunk-DfAF0w94.js";
//#region ../../node_modules/.pnpm/mathxyjax3@0.8.3/node_modules/mathxyjax3/dist/index.js
var dist_exports = /* @__PURE__ */ __exportAll({ tex2svgHtml: () => a });
var t = {
	"xmldom-sre": await __vitePreload(() => import("./lib-CBtriEt5.js").then(l(1)), __vite__mapDeps([0,1]), import.meta.url),
	"wicked-good-xpath": await __vitePreload(() => import("./wgxpath.install-node-Csk64Aj9.js").then(l(1)), __vite__mapDeps([2,1]), import.meta.url),
	commander: {},
	fs: {}
};
var n = (e) => t[e];
globalThis.MathJax_require = n;
var r = {
	"mathjax/es5/adaptors/liteDOM.js": () => __vitePreload(() => import("./liteDOM-Cp0aN3bP.js"), [], import.meta.url),
	"xyjax/build/xypic.js": () => __vitePreload(() => import("./xypic-DrMJn58R.js"), [], import.meta.url)
};
var i = (e) => r[e]();
globalThis.MathJax = {
	loader: {
		source: {},
		require: i,
		load: [`adaptors/liteDOM`, `[custom]/xypic`],
		paths: {
			mathjax: `mathjax/es5`,
			custom: `xyjax/build`
		}
	},
	tex: { packages: { "[+]": [`xypic`] } },
	svg: { fontCache: `none` },
	startup: { typeset: !1 }
}, await __vitePreload(() => import("./tex-svg-full-BI3fonbT.js"), [], import.meta.url), await globalThis.MathJax.startup?.promise;
function a(e = ``, t = {}) {
	let n = globalThis.MathJax.tex2svg(e, {
		display: !0,
		...t
	}), r = globalThis.MathJax.startup.adaptor, i = r.textContent(globalThis.MathJax.svgStylesheet()), a = r.outerHTML(n), o = `mjx-${Math.random().toString(16).substring(8)}`;
	return `
    <span id="${o}">
      <style>
      #${o}{
        display:contents;
        mjx-assistive-mml {
          user-select: text !important;
          clip: auto !important;
          color: rgba(0,0,0,0);
        }
        ${i}
      }
      </style>
      ${a}
    </span>
  `;
}
//#endregion
//#region ../../node_modules/.pnpm/markdown-it-mathjax3@5.2.0/node_modules/markdown-it-mathjax3/dist/index.js
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __esm = (fn, res) => function() {
	return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __commonJS = (cb, mod) => function() {
	return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var __copyProps = (to, from, except, desc) => {
	if (from && typeof from === "object" || typeof from === "function") for (var keys = __getOwnPropNames(from), i = 0, n = keys.length, key; i < n; i++) {
		key = keys[i];
		if (!__hasOwnProp.call(to, key) && key !== except) __defProp(to, key, {
			get: ((k) => from[k]).bind(null, key),
			enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
		});
	}
	return to;
};
var __reExport = (target, mod, secondTarget) => (__copyProps(target, mod, "default"), secondTarget && __copyProps(secondTarget, mod, "default"));
var mathjax_exports = {};
__reExport(mathjax_exports, dist_exports);
var init_mathjax = __esm({ "src/mathjax.mts": (() => {}) });
var dist_default = (/* @__PURE__ */ __commonJS({ "src/index.ts": ((exports, module) => {
	init_mathjax();
	function isValidDelim(state, pos) {
		let max = state.posMax, can_open = true, can_close = true;
		const prevChar = pos > 0 ? state.src.charCodeAt(pos - 1) : -1, nextChar = pos + 1 <= max ? state.src.charCodeAt(pos + 1) : -1;
		if (prevChar === 32 || prevChar === 9 || nextChar >= 48 && nextChar <= 57) can_close = false;
		if (nextChar === 32 || nextChar === 9) can_open = false;
		return {
			can_open,
			can_close
		};
	}
	function math_inline(state, silent) {
		if (state.src[state.pos] !== "$") return false;
		let res = isValidDelim(state, state.pos);
		if (!res.can_open) {
			if (!silent) state.pending += "$";
			state.pos += 1;
			return true;
		}
		const start = state.pos + 1;
		let match = start;
		while ((match = state.src.indexOf("$", match)) !== -1) {
			let pos = match - 1;
			while (state.src[pos] === "\\") pos -= 1;
			if ((match - pos) % 2 == 1) break;
			match += 1;
		}
		if (match === -1) {
			if (!silent) state.pending += "$";
			state.pos = start;
			return true;
		}
		if (match - start === 0) {
			if (!silent) state.pending += "$$";
			state.pos = start + 1;
			return true;
		}
		res = isValidDelim(state, match);
		if (!res.can_close) {
			if (!silent) state.pending += "$";
			state.pos = start;
			return true;
		}
		if (!silent) {
			const token = state.push("math_inline", "math", 0);
			token.markup = "$";
			token.content = state.src.slice(start, match);
		}
		state.pos = match + 1;
		return true;
	}
	function math_block(state, start, end, silent) {
		let next, lastPos;
		let found = false, pos = state.bMarks[start] + state.tShift[start], max = state.eMarks[start], lastLine = "";
		if (pos + 2 > max) return false;
		if (state.src.slice(pos, pos + 2) !== "$$") return false;
		pos += 2;
		let firstLine = state.src.slice(pos, max);
		if (silent) return true;
		if (firstLine.trim().slice(-2) === "$$") {
			firstLine = firstLine.trim().slice(0, -2);
			found = true;
		}
		for (next = start; !found;) {
			next++;
			if (next >= end) break;
			pos = state.bMarks[next] + state.tShift[next];
			max = state.eMarks[next];
			if (pos < max && state.tShift[next] < state.blkIndent) break;
			if (state.src.slice(pos, max).trim().slice(-2) === "$$") {
				lastPos = state.src.slice(0, max).lastIndexOf("$$");
				lastLine = state.src.slice(pos, lastPos);
				found = true;
			}
		}
		state.line = next + 1;
		const token = state.push("math_block", "math", 0);
		token.block = true;
		token.content = (firstLine && firstLine.trim() ? firstLine + "\n" : "") + state.getLines(start + 1, next, state.tShift[start], true) + (lastLine && lastLine.trim() ? lastLine : "");
		token.map = [start, state.line];
		token.markup = "$$";
		return true;
	}
	const plugin = (md) => {
		md.inline.ruler.after("escape", "math_inline", math_inline);
		md.block.ruler.after("blockquote", "math_block", math_block, { alt: [
			"paragraph",
			"reference",
			"blockquote",
			"list"
		] });
		md.renderer.rules.math_inline = function(tokens, idx) {
			return mathjax_exports.tex2svgHtml(tokens[idx].content, { display: false });
		};
		md.renderer.rules.math_block = function(tokens, idx) {
			return mathjax_exports.tex2svgHtml(tokens[idx].content, { display: true });
		};
	};
	plugin.default = plugin;
	module.exports = plugin;
}) }))();
//#endregion
export { dist_default as default };

//# sourceMappingURL=dist.js.map