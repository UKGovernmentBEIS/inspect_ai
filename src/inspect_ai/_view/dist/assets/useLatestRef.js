import { i as __toESM } from "./rolldown-runtime.js";
import { n as require_react, t as require_compiler_runtime } from "./compiler-runtime.js";
//#region ../../packages/react/src/hooks/useLatestRef.ts
var import_compiler_runtime = require_compiler_runtime();
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
/**
* Returns a ref that always holds the latest `value`.
*
* The named replacement for the hand-rolled "mirror a value into a ref"
* effect: lets stable callbacks (subscriptions, timers, imperative handles)
* read current state/props without listing them as dependencies.
*/ function useLatestRef(value) {
	const $ = (0, import_compiler_runtime.c)(2);
	const ref = (0, import_react.useRef)(value);
	let t0;
	if ($[0] !== value) {
		t0 = () => {
			ref.current = value;
		};
		$[0] = value;
		$[1] = t0;
	} else t0 = $[1];
	(0, import_react.useLayoutEffect)(t0);
	return ref;
}
//#endregion
export { useLatestRef as t };

//# sourceMappingURL=useLatestRef.js.map