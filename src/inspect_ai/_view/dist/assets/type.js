//#region ../../packages/util/src/type.ts
/**
* Checks if a given value is numeric.
*/ var isNumeric = (n) => {
	return !isNaN(parseFloat(String(n))) && isFinite(Number(n));
};
/**
* Ensures the value is an array
*
* @param {*} val - The value to ensure is an array.
* @returns {Array} - an Array
*/ var toArray = (val) => {
	if (Array.isArray(val)) return val;
	else return [val];
};
/**
* Narrows a `T | ReadonlyArray<T>` union, which `Array.isArray` cannot do on
* its own — its signature only knows about mutable arrays. Unsound if `T` is
* itself an array type.
*/ var isReadonlyArray = (value) => Array.isArray(value);
/**
* Checks if a given value is a Record.
*/ var isRecord = (value) => {
	return typeof value === "object" && value !== null && !Array.isArray(value);
};
//#endregion
export { toArray as i, isReadonlyArray as n, isRecord as r, isNumeric as t };

//# sourceMappingURL=type.js.map