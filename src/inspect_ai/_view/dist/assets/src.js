import { i as __toESM, n as __exportAll, t as __commonJSMin } from "./rolldown-runtime.js";
//#region ../../packages/util/src/ansi.ts
var kAnsiEscapePattern = /\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|\][^\x07\x1b\n\r\u2028\u2029]*(?:\x07|\x1b\\)|[^[\]>])/;
/**
* Detects if text contains ANSI escape sequences.
*
* This function checks for various ANSI escape codes including:
* - CSI (Control Sequence Introducer) sequences: ESC [ ... (colors, cursor movement, etc.)
* - OSC (Operating System Command) sequences: ESC ] ... (terminal titles, hyperlinks)
* - Simple escape sequences: ESC followed by a single character
*
* @param text - The text to check for ANSI escape sequences
* @returns true if ANSI escape sequences are detected, false otherwise
*/ var isAnsiOutput = (text) => kAnsiEscapePattern.test(text);
var kAnsiEscapesGlobal = new RegExp(kAnsiEscapePattern.source, "g");
/** `text` with its ANSI escape sequences removed. */ var stripAnsi = (text) => text.replace(kAnsiEscapesGlobal, "");
//#endregion
//#region ../../node_modules/.pnpm/@uwdata+flechette@2.5.0/node_modules/@uwdata/flechette/src/util/arrays.js
/**
* @import { Int64ArrayConstructor, IntArrayConstructor, IntegerArray, TypedArray } from '../types.js'
*/
var uint8Array = Uint8Array;
var uint32Array = Uint32Array;
BigUint64Array;
var int32Array = Int32Array;
var int64Array = BigInt64Array;
var buf = (/* @__PURE__ */ new Float64Array(2)).buffer;
new int64Array(buf);
new uint32Array(buf);
new int32Array(buf);
new uint8Array(buf);
new TextDecoder("utf-8");
new TextEncoder();
new Uint16Array(new Uint8Array([1, 0]).buffer)[0];
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/bin.js
/**
* Truncate a value to a bin boundary.
* Useful for creating equal-width histograms.
* Values outside the [min, max] range will be mapped to
* -Infinity (< min) or +Infinity (> max).
* @param {number} value The value to bin.
* @param {number} min The minimum bin boundary.
* @param {number} max The maximum bin boundary.
* @param {number} step The step size between bin boundaries.
* @param {number} [offset=0] Offset in steps by which to adjust
*  the bin value. An offset of 1 will return the next boundary.
*/
function bin(value, min, max, step, offset) {
	return value == null ? null : value < min ? -Infinity : value > max ? Infinity : (value = Math.max(min, Math.min(value, max)), min + step * Math.floor(1e-14 + (value - min) / step + (offset || 0)));
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-date.js
/**
* @param {*} value
* @returns {value is Date}
*/
function isDate(value) {
	return value instanceof Date;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-regexp.js
/**
* @param {*} value
* @returns {value is RegExp}
*/
function isRegExp(value) {
	return value instanceof RegExp;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-object.js
function isObject(value) {
	return value === Object(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/equal.js
/**
* Compare two values for equality, using join semantics in which null
* !== null. If the inputs are object-valued, a deep equality check
* of array entries or object key-value pairs is performed.
* @param {*} a The first input.
* @param {*} b The second input.
* @return {boolean} True if equal, false if not.
*/
function equal(a, b) {
	return a == null || b == null || a !== a || b !== b ? false : a === b ? true : isDate(a) || isDate(b) ? +a === +b : isRegExp(a) && isRegExp(b) ? a + "" === b + "" : isObject(a) && isObject(b) ? deepEqual(a, b) : false;
}
function deepEqual(a, b) {
	if (Object.getPrototypeOf(a) !== Object.getPrototypeOf(b)) return false;
	if (a.length || b.length) return arrayEqual(a, b);
	const keysA = Object.keys(a);
	const keysB = Object.keys(b);
	if (keysA.length !== keysB.length) return false;
	keysA.sort();
	keysB.sort();
	if (!arrayEqual(keysA, keysB, (a, b) => a === b)) return false;
	const n = keysA.length;
	for (let i = 0; i < n; ++i) {
		const k = keysA[i];
		if (!equal(a[k], b[k])) return false;
	}
	return true;
}
function arrayEqual(a, b, test = equal) {
	const n = a.length;
	if (n !== b.length) return false;
	for (let i = 0; i < n; ++i) if (!test(a[i], b[i])) return false;
	return true;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/recode.js
/**
* Recodes an input value to an alternative value, based on a provided
* value map. If a fallback value is specified, it will be returned when
* a matching value is not found in the map; otherwise, the input value
* is returned unchanged.
* @template T
* @param {T} value The value to recode. The value must be safely
*  coercible to a string for lookup against the value map.
* @param {Map|Record<string,any>} map An object or Map with input values
*  for keys and output recoded values as values. If a non-Map object, only
*  the object's own properties will be considered.
* @param {T} [fallback] A default fallback value to use if the input
*  value is not found in the value map.
* @return {T} The recoded value.
*/
function recode(value, map, fallback) {
	if (map instanceof Map) {
		if (map.has(value)) return map.get(value);
	} else {
		const key = `${value}`;
		if (Object.hasOwn(map, key)) return map[key];
	}
	return fallback !== void 0 ? fallback : value;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/sequence.js
/**
* Returns an array containing an arithmetic sequence from the start value
* to the stop value, in step increments. If step is positive, the last
* element is the largest start + i * step less than stop; if step is
* negative, the last element is the smallest start + i * step greater
* than stop. If the returned array would contain an infinite number of
* values, an empty range is returned.
* @param {number} [start=0] The starting value of the sequence.
* @param {number} [stop] The stopping value of the sequence.
*  The stop value is exclusive; it is not included in the result.
* @param {number} [step=1] The step increment between sequence values.
* @return {number[]} The generated sequence.
*/
function sequence(start, stop, step) {
	let n = arguments.length;
	start = +start;
	stop = +stop;
	step = n < 2 ? (stop = start, start = 0, 1) : n < 3 ? 1 : +step;
	n = Math.max(0, Math.ceil((stop - start) / step)) | 0;
	const seq = new Array(n);
	for (let i = 0; i < n; ++i) seq[i] = start + i * step;
	return seq;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-array.js
/**
* @param {*} value
* @returns {value is Array}
*/
function isArray$1(value) {
	return Array.isArray(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-typed-array.js
var TypedArray = Object.getPrototypeOf(Int8Array);
/**
* @param {*} value
* @return {value is import("../table/types.js").TypedArray}
*/
function isTypedArray(value) {
	return value instanceof TypedArray;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-array-type.js
/**
* @param {*} value
* @return {value is (any[] | import('../table/types.js').TypedArray)}
*/
function isArrayType(value) {
	return isArray$1(value) || isTypedArray(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-string.js
/**
* @param {*} value
* @return {value is String}
*/
function isString(value) {
	return typeof value === "string";
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-valid.js
function isValid(value) {
	return value != null && value === value;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/array.js
var array_exports = /* @__PURE__ */ __exportAll({
	compact: () => compact,
	concat: () => concat,
	includes: () => includes,
	indexof: () => indexof,
	join: () => join,
	lastindexof: () => lastindexof,
	length: () => length,
	pluck: () => pluck,
	reverse: () => reverse,
	slice: () => slice
});
var isSeq = (seq) => isArrayType(seq) || isString(seq);
/**
* Returns a new compacted array with invalid values
* (`null`, `undefined`, `NaN`) removed.
* @template T
* @param {T[]} array The input array.
* @return {T[]} A compacted array.
*/
function compact(array) {
	return isArrayType(array) ? array.filter((v) => isValid(v)) : array;
}
/**
* Merges two or more arrays in sequence, returning a new array.
* @template T
* @param {...(T|T[])} values The arrays to merge.
* @return {T[]} The merged array.
*/
function concat(...values) {
	return [].concat(...values);
}
/**
* Determines whether an *array* includes a certain *value* among its
* entries, returning `true` or `false` as appropriate.
* @template T
* @param {T[]} sequence The input array value.
* @param {T} value The value to search for.
* @param {number} [index=0] The integer index to start searching
*  from (default `0`).
* @return {boolean} True if the value is included, false otherwise.
*/
function includes(sequence, value, index) {
	return isSeq(sequence) ? sequence.includes(value, index) : false;
}
/**
* Returns the first index at which a given *value* can be found in the
* *sequence* (array or string), or -1 if it is not present.
* @template T
* @param {T[]|string} sequence The input array or string value.
* @param {T} value The value to search for.
* @return {number} The index of the value, or -1 if not present.
*/
function indexof(sequence, value) {
	return isSeq(sequence) ? sequence.indexOf(value) : -1;
}
/**
* Creates and returns a new string by concatenating all of the elements
* in an *array* (or an array-like object), separated by commas or a
* specified *delimiter* string. If the *array* has only one item, then
* that item will be returned without using the delimiter.
* @template T
* @param {T[]} array The input array value.
* @param {string} delim The delimiter string (default `','`).
* @return {string} The joined string.
*/
function join(array, delim) {
	return isArrayType(array) ? array.join(delim) : void 0;
}
/**
* Returns the last index at which a given *value* can be found in the
* *sequence* (array or string), or -1 if it is not present.
* @template T
* @param {T[]|string} sequence The input array or string value.
* @param {T} value The value to search for.
* @return {number} The last index of the value, or -1 if not present.
*/
function lastindexof(sequence, value) {
	return isSeq(sequence) ? sequence.lastIndexOf(value) : -1;
}
/**
* Returns the length of the input *sequence* (array or string).
* @param {Array|string} sequence The input array or string value.
* @return {number} The length of the sequence.
*/
function length(sequence) {
	return isSeq(sequence) ? sequence.length : 0;
}
/**
* Returns a new array in which the given *property* has been extracted
* for each element in the input *array*.
* @param {Array} array The input array value.
* @param {string} property The property name string to extract. Nested
*  properties are not supported: the input `"a.b"` will indicates a
*  property with that exact name, *not* a nested property `"b"` of
*  the object `"a"`.
* @return {Array} An array of plucked properties.
*/
function pluck(array, property) {
	return isArrayType(array) ? array.map((v) => isValid(v) ? v[property] : void 0) : void 0;
}
/**
* Returns a new array or string with the element order reversed: the first
* *sequence* element becomes the last, and the last *sequence* element
* becomes the first. The input *sequence* is unchanged.
* @template T
* @param {T[]|string} sequence The input array or string value.
* @return {T[]|string} The reversed sequence.
*/
function reverse(sequence) {
	return isArrayType(sequence) ? sequence.slice().reverse() : isString(sequence) ? sequence.split("").reverse().join("") : void 0;
}
/**
* Returns a copy of a portion of the input *sequence* (array or string)
* selected from *start* to *end* (*end* not included) where *start* and
* *end* represent the index of items in the sequence.
* @template T
* @param {T[]|string} sequence The input array or string value.
* @param {number} [start=0] The starting integer index to copy from
*  (inclusive, default `0`).
* @param {number} [end] The ending integer index to copy from (exclusive,
*  default `sequence.length`).
* @return {T[]|string} The sliced sequence.
*/
function slice(sequence, start, end) {
	return isSeq(sequence) ? sequence.slice(start, end) : void 0;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/pad.js
function pad(value, width, char = "0") {
	const s = value + "";
	const len = s.length;
	return len < width ? Array(width - len + 1).join(char) + s : s;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/format-date.js
var pad2 = (v) => (v < 10 ? "0" : "") + v;
var formatYear = (year) => year < 0 ? "-" + pad(-year, 6) : year > 9999 ? "+" + pad(year, 6) : pad(year, 4);
function formatISO(year, month, date, hours, min, sec, ms, utc, short) {
	const suffix = utc ? "Z" : "";
	return formatYear(year) + "-" + pad2(month + 1) + "-" + pad2(date) + (!short || ms ? "T" + pad2(hours) + ":" + pad2(min) + ":" + pad2(sec) + "." + pad(ms, 3) + suffix : sec ? "T" + pad2(hours) + ":" + pad2(min) + ":" + pad2(sec) + suffix : min || hours || !utc ? "T" + pad2(hours) + ":" + pad2(min) + suffix : "");
}
function formatDate(d, short) {
	return isNaN(d) ? "Invalid Date" : formatISO(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds(), false, short);
}
function formatUTCDate(d, short) {
	return isNaN(d) ? "Invalid Date" : formatISO(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds(), true, short);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-iso-date-string.js
var iso_re = /^([-+]\d{2})?\d{4}(-\d{2}(-\d{2})?)?(T\d{2}:\d{2}(:\d{2}(\.\d{3})?)?(Z|[-+]\d{2}:\d{2})?)?$/;
/**
* @param {string} value
* @returns {boolean}
*/
function isISODateString(value) {
	return value.match(iso_re) && !isNaN(Date.parse(value));
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/parse-iso-date.js
function parseISODate(value, parse = Date.parse) {
	return isISODateString(value) ? parse(value) : value;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/date.js
var date_exports = /* @__PURE__ */ __exportAll({
	date: () => date,
	datetime: () => datetime,
	dayofweek: () => dayofweek,
	dayofyear: () => dayofyear,
	format_date: () => format_date,
	format_utcdate: () => format_utcdate,
	hours: () => hours,
	milliseconds: () => milliseconds,
	minutes: () => minutes,
	month: () => month,
	now: () => now,
	quarter: () => quarter,
	seconds: () => seconds,
	timestamp: () => timestamp,
	utcdate: () => utcdate,
	utcdatetime: () => utcdatetime,
	utcdayofweek: () => utcdayofweek,
	utcdayofyear: () => utcdayofyear,
	utchours: () => utchours,
	utcmilliseconds: () => utcmilliseconds,
	utcminutes: () => utcminutes,
	utcmonth: () => utcmonth,
	utcquarter: () => utcquarter,
	utcseconds: () => utcseconds,
	utcweek: () => utcweek,
	utcyear: () => utcyear,
	week: () => week,
	year: () => year
});
var msMinute = 6e4;
var msDay = 864e5;
var msWeek = 6048e5;
var t0 = /* @__PURE__ */ new Date();
var t1 = /* @__PURE__ */ new Date();
var t = (d) => (t0.setTime(typeof d === "string" ? parseISODate(d) : d), t0);
/**
* Returns an [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted
* string for the given *date* in local timezone. The resulting string is
* compatible with *parse_date* and JavaScript's built-in *Date.parse*.
* @param {Date | number} date The input Date or timestamp value.
* @param {boolean} [shorten=false] A boolean flag (default `false`)
*  indicating if the formatted string should be shortened if possible.
*  For example, the local date `2001-01-01` will shorten from
*  `"2001-01-01T00:00:00.000"` to `"2001-01-01T00:00"`.
* @return {string} The formatted date string in local time.
*/
function format_date(date, shorten) {
	return formatDate(t(date), !shorten);
}
/**
* Returns an [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted
* string for the given *date* in Coordinated Universal Time (UTC). The
* resulting string is compatible with *parse_date* and JavaScript's
* built-in *Date.parse*.
* @param {Date | number} date The input Date or timestamp value.
* @param {boolean} [shorten=false] A boolean flag (default `false`)
*  indicating if the formatted string should be shortened if possible.
*  For example, the the UTC date `2001-01-01` will shorten from
*  `"2001-01-01T00:00:00.000Z"` to `"2001-01-01"`
* @return {string} The formatted date string in UTC time.
*/
function format_utcdate(date, shorten) {
	return formatUTCDate(t(date), !shorten);
}
/**
* Returns the number of milliseconds elapsed since midnight, January 1,
* 1970 Universal Coordinated Time (UTC).
* @return {number} The timestamp for now.
*/
function now() {
	return Date.now();
}
/**
* Returns the timestamp for a *date* as the number of milliseconds elapsed
* since January 1, 1970 00:00:00 UTC.
* @param {Date | number} date The input Date value.
* @return {number} The timestamp value.
*/
function timestamp(date) {
	return +t(date);
}
/**
* Creates and returns a new Date value. If no arguments are provided,
* the current date and time are used.
* @param {number} [year] The year.
* @param {number} [month=0] The (zero-based) month.
* @param {number} [date=1] The date within the month.
* @param {number} [hours=0] The hour within the day.
* @param {number} [minutes=0] The minute within the hour.
* @param {number} [seconds=0] The second within the minute.
* @param {number} [milliseconds=0] The milliseconds within the second.
* @return {Date} The Date value.
*/
function datetime(year, month, date, hours, minutes, seconds, milliseconds) {
	return !arguments.length ? new Date(Date.now()) : new Date(year, month || 0, date == null ? 1 : date, hours || 0, minutes || 0, seconds || 0, milliseconds || 0);
}
/**
* Returns the year of the specified *date* according to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The year value in local time.
*/
function year(date) {
	return t(date).getFullYear();
}
/**
* Returns the zero-based quarter of the specified *date* according to
* local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The quarter value in local time.
*/
function quarter(date) {
	return Math.floor(t(date).getMonth() / 3);
}
/**
* Returns the zero-based month of the specified *date* according to local
* time. A value of `0` indicates January, `1` indicates February, and so on.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The month value in local time.
*/
function month(date) {
	return t(date).getMonth();
}
/**
* Returns the week number of the year (0-53) for the specified *date*
* according to local time. By default, Sunday is used as the first day
* of the week. All days in a new year preceding the first Sunday are
* considered to be in week 0.
* @param {Date | number} date The input Date or timestamp value.
* @param {number} firstday The number of first day of the week (default
*  `0` for Sunday, `1` for Monday and so on).
* @return {number} The week of the year in local time.
*/
function week(date, firstday) {
	const i = firstday || 0;
	t1.setTime(+date);
	t1.setDate(t1.getDate() - (t1.getDay() + 7 - i) % 7);
	t1.setHours(0, 0, 0, 0);
	t0.setTime(+date);
	t0.setMonth(0);
	t0.setDate(1);
	t0.setDate(1 - (t0.getDay() + 7 - i) % 7);
	t0.setHours(0, 0, 0, 0);
	const tz = (t1.getTimezoneOffset() - t0.getTimezoneOffset()) * msMinute;
	return Math.floor((1 + (+t1 - +t0) - tz) / msWeek);
}
/**
* Returns the date (day of month) of the specified *date* according
* to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The date (day of month) value.
*/
function date(date) {
	return t(date).getDate();
}
/**
* Returns the day of the year (1-366) of the specified *date* according
* to local time.
* @param {Date | number} date A date or timestamp.
* @return {number} The day of the year in local time.
*/
function dayofyear(date) {
	t1.setTime(+date);
	t1.setHours(0, 0, 0, 0);
	t0.setTime(+t1);
	t0.setMonth(0);
	t0.setDate(1);
	const tz = (t1.getTimezoneOffset() - t0.getTimezoneOffset()) * msMinute;
	return Math.floor(1 + (+t1 - +t0 - tz) / msDay);
}
/**
* Returns the Sunday-based day of the week (0-6) of the specified *date*
* according to local time. A value of `0` indicates Sunday, `1` indicates
* Monday, and so on.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The day of the week value in local time.
*/
function dayofweek(date) {
	return t(date).getDay();
}
/**
* Returns the hour of the day for the specified *date* according
* to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The hour value in local time.
*/
function hours(date) {
	return t(date).getHours();
}
/**
* Returns the minute of the hour for the specified *date* according
* to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The minutes value in local time.
*/
function minutes(date) {
	return t(date).getMinutes();
}
/**
* Returns the seconds of the minute for the specified *date* according
* to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The seconds value in local time.
*/
function seconds(date) {
	return t(date).getSeconds();
}
/**
* Returns the milliseconds of the second for the specified *date* according
* to local time.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The milliseconds value in local time.
*/
function milliseconds(date) {
	return t(date).getMilliseconds();
}
/**
* Creates and returns a new Date value using Coordinated Universal Time
* (UTC). If no arguments are provided, the current date and time are used.
* @param {number} [year] The year.
* @param {number} [month=0] The (zero-based) month.
* @param {number} [date=1] The date within the month.
* @param {number} [hours=0] The hour within the day.
* @param {number} [minutes=0] The minute within the hour.
* @param {number} [seconds=0] The second within the minute.
* @param {number} [milliseconds=0] The milliseconds within the second.
* @return {Date} The Date value.
*/
function utcdatetime(year, month, date, hours, minutes, seconds, milliseconds) {
	return !arguments.length ? new Date(Date.now()) : new Date(Date.UTC(year, month || 0, date == null ? 1 : date, hours || 0, minutes || 0, seconds || 0, milliseconds || 0));
}
/**
* Returns the year of the specified *date* according to Coordinated
* Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The year value in UTC time.
*/
function utcyear(date) {
	return t(date).getUTCFullYear();
}
/**
* Returns the zero-based quarter of the specified *date* according to
* Coordinated Universal Time (UTC)
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The quarter value in UTC time.
*/
function utcquarter(date) {
	return Math.floor(t(date).getUTCMonth() / 3);
}
/**
* Returns the zero-based month of the specified *date* according to
* Coordinated Universal Time (UTC). A value of `0` indicates January,
* `1` indicates February, and so on.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The month value in UTC time.
*/
function utcmonth(date) {
	return t(date).getUTCMonth();
}
/**
* Returns the week number of the year (0-53) for the specified *date*
* according to Coordinated Universal Time (UTC). By default, Sunday is
* used as the first day of the week. All days in a new year preceding the
* first Sunday are considered to be in week 0.
* @param {Date | number} date The input Date or timestamp value.
* @param {number} firstday The number of first day of the week (default
*  `0` for Sunday, `1` for Monday and so on).
* @return {number} The week of the year in UTC time.
*/
function utcweek(date, firstday) {
	const i = firstday || 0;
	t1.setTime(+date);
	t1.setUTCDate(t1.getUTCDate() - (t1.getUTCDay() + 7 - i) % 7);
	t1.setUTCHours(0, 0, 0, 0);
	t0.setTime(+date);
	t0.setUTCMonth(0);
	t0.setUTCDate(1);
	t0.setUTCDate(1 - (t0.getUTCDay() + 7 - i) % 7);
	t0.setUTCHours(0, 0, 0, 0);
	return Math.floor((1 + (+t1 - +t0)) / msWeek);
}
/**
* Returns the date (day of month) of the specified *date* according to
* Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The date (day of month) value in UTC time.
*/
function utcdate(date) {
	return t(date).getUTCDate();
}
/**
* Returns the day of the year (1-366) of the specified *date* according
* to Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The day of the year in UTC time.
*/
function utcdayofyear(date) {
	t1.setTime(+date);
	t1.setUTCHours(0, 0, 0, 0);
	const t0 = Date.UTC(t1.getUTCFullYear(), 0, 1);
	return Math.floor(1 + (+t1 - t0) / msDay);
}
/**
* Returns the Sunday-based day of the week (0-6) of the specified *date*
* according to Coordinated Universal Time (UTC). A value of `0` indicates
* Sunday, `1` indicates Monday, and so on.
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The day of the week in UTC time.
*/
function utcdayofweek(date) {
	return t(date).getUTCDay();
}
/**
* Returns the hour of the day for the specified *date* according to
* Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The hours value in UTC time.
*/
function utchours(date) {
	return t(date).getUTCHours();
}
/**
* Returns the minute of the hour for the specified *date* according to
* Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The minutes value in UTC time.
*/
function utcminutes(date) {
	return t(date).getUTCMinutes();
}
/**
* Returns the seconds of the minute for the specified *date* according to
* Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The seconds value in UTC time.
*/
function utcseconds(date) {
	return t(date).getUTCSeconds();
}
/**
* Returns the milliseconds of the second for the specified *date* according to
* Coordinated Universal Time (UTC).
* @param {Date | number} date The input Date or timestamp value.
* @return {number} The milliseconds value in UTC time.
*/
function utcmilliseconds(date) {
	return t(date).getUTCMilliseconds();
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/json.js
var json_exports = /* @__PURE__ */ __exportAll({
	parse_json: () => parse_json,
	to_json: () => to_json
});
/**
* Parses a string *value* in JSON format, constructing the JavaScript
* value or object described by the string.
* @param {string} value The input string value.
* @return {any} The parsed JSON.
*/
function parse_json(value) {
	return JSON.parse(value);
}
/**
* Converts a JavaScript object or value to a JSON string.
* @param {*} value The value to convert to a JSON string.
* @return {string} The JSON string.
*/
function to_json(value) {
	return JSON.stringify(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/random.js
var source = Math.random;
function random$1() {
	return source();
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/math.js
var math_exports = /* @__PURE__ */ __exportAll({
	abs: () => abs,
	acos: () => acos,
	acosh: () => acosh,
	asin: () => asin,
	asinh: () => asinh,
	atan: () => atan,
	atan2: () => atan2,
	atanh: () => atanh,
	cbrt: () => cbrt,
	ceil: () => ceil,
	clz32: () => clz32,
	cos: () => cos,
	cosh: () => cosh,
	degrees: () => degrees,
	exp: () => exp,
	expm1: () => expm1,
	floor: () => floor,
	fround: () => fround,
	greatest: () => greatest,
	is_finite: () => is_finite,
	is_nan: () => is_nan,
	least: () => least,
	log: () => log,
	log10: () => log10,
	log1p: () => log1p,
	log2: () => log2,
	pow: () => pow,
	radians: () => radians,
	random: () => random,
	round: () => round,
	sign: () => sign,
	sin: () => sin,
	sinh: () => sinh,
	sqrt: () => sqrt,
	tan: () => tan,
	tanh: () => tanh,
	trunc: () => trunc
});
/**
* Return a random floating point number between 0 (inclusive) and 1
* (exclusive). By default uses *Math.random*. Use the *seed* method
* to instead use a seeded random number generator.
* @return {number} A pseudorandom number between 0 and 1.
*/
function random() {
	return random$1();
}
/**
* Tests if the input *value* is not a number (`NaN`); equivalent
* to *Number.isNaN*.
* @param {*} value The value to test.
* @return {boolean} True if the value is not a number, false otherwise.
*/
function is_nan(value) {
	return Number.isNaN(value);
}
/**
* Tests if the input *value* is finite; equivalent to *Number.isFinite*.
* @param {*} value The value to test.
* @return {boolean} True if the value is finite, false otherwise.
*/
function is_finite(value) {
	return Number.isFinite(value);
}
/**
* Returns the absolute value of the input *value*; equivalent to *Math.abs*.
* @param {number} value The input number value.
* @return {number} The absolute value.
*/
function abs(value) {
	return Math.abs(value);
}
/**
* Returns the cube root value of the input *value*; equivalent to
* *Math.cbrt*.
* @param {number} value The input number value.
* @return {number} The cube root value.
*/
function cbrt(value) {
	return Math.cbrt(value);
}
/**
* Returns the ceiling of the input *value*, the nearest integer equal to
* or greater than the input; equivalent to *Math.ceil*.
* @param {number} value The input number value.
* @return {number} The ceiling value.
*/
function ceil(value) {
	return Math.ceil(value);
}
/**
* Returns the number of leading zero bits in the 32-bit binary
* representation of a number *value*; equivalent to *Math.clz32*.
* @param {number} value The input number value.
* @return {number} The leading zero bits value.
*/
function clz32(value) {
	return Math.clz32(value);
}
/**
* Returns *e<sup>value</sup>*, where *e* is Euler's number, the base of the
* natural logarithm; equivalent to *Math.exp*.
* @param {number} value The input number value.
* @return {number} The base-e exponentiated value.
*/
function exp(value) {
	return Math.exp(value);
}
/**
* Returns *e<sup>value</sup> - 1*, where *e* is Euler's number, the base of
* the natural logarithm; equivalent to *Math.expm1*.
* @param {number} value The input number value.
* @return {number} The base-e exponentiated value minus 1.
*/
function expm1(value) {
	return Math.expm1(value);
}
/**
* Returns the floor of the input *value*, the nearest integer equal to or
* less than the input; equivalent to *Math.floor*.
* @param {number} value The input number value.
* @return {number} The floor value.
*/
function floor(value) {
	return Math.floor(value);
}
/**
* Returns the nearest 32-bit single precision float representation of the
* input number *value*; equivalent to *Math.fround*. Useful for translating
* between 64-bit `Number` values and values from a `Float32Array`.
* @param {number} value The input number value.
* @return {number} The rounded value.
*/
function fround(value) {
	return Math.fround(value);
}
/**
* Returns the greatest (maximum) value among the input *values*; equivalent
* to *Math.max*. This is _not_ an aggregate function, see *op.max* to
* compute a maximum value across multiple rows.
* @param {...number} values The input number values.
* @return {number} The greatest (maximum) value among the inputs.
*/
function greatest(...values) {
	return Math.max(...values);
}
/**
* Returns the least (minimum) value among the input *values*; equivalent
* to *Math.min*. This is _not_ an aggregate function, see *op.min* to
* compute a minimum value across multiple rows.
* @param {...number} values The input number values.
* @return {number} The least (minimum) value among the inputs.
*/
function least(...values) {
	return Math.min(...values);
}
/**
* Returns the natural logarithm (base *e*) of a number *value*; equivalent
* to *Math.log*.
* @param {number} value The input number value.
* @return {number} The base-e log value.
*/
function log(value) {
	return Math.log(value);
}
/**
* Returns the base 10 logarithm of a number *value*; equivalent
* to *Math.log10*.
* @param {number} value The input number value.
* @return {number} The base-10 log value.
*/
function log10(value) {
	return Math.log10(value);
}
/**
* Returns the natural logarithm (base *e*) of 1 + a number *value*;
* equivalent to *Math.log1p*.
* @param {number} value The input number value.
* @return {number} The base-e log of value + 1.
*/
function log1p(value) {
	return Math.log1p(value);
}
/**
* Returns the base 2 logarithm of a number *value*; equivalent
* to *Math.log2*.
* @param {number} value The input number value.
* @return {number} The base-2 log value.
*/
function log2(value) {
	return Math.log2(value);
}
/**
* Returns the *base* raised to the *exponent* power, that is,
* *base*<sup>*exponent*</sup>; equivalent to *Math.pow*.
* @param {number} base The base number value.
* @param {number} exponent The exponent number value.
* @return {number} The exponentiated value.
*/
function pow(base, exponent) {
	return Math.pow(base, exponent);
}
/**
* Returns the value of a number rounded to the nearest integer;
* equivalent to *Math.round*.
* @param {number} value The input number value.
* @return {number} The rounded value.
*/
function round(value) {
	return Math.round(value);
}
/**
* Returns either a positive or negative +/- 1, indicating the sign of the
* input *value*; equivalent to *Math.sign*.
* @param {number} value The input number value.
* @return {number} The sign of the value.
*/
function sign(value) {
	return Math.sign(value);
}
/**
* Returns the square root of the input *value*; equivalent to *Math.sqrt*.
* @param {number} value The input number value.
* @return {number} The square root value.
*/
function sqrt(value) {
	return Math.sqrt(value);
}
/**
* Returns the integer part of a number by removing any fractional digits;
* equivalent to *Math.trunc*.
* @param {number} value The input number value.
* @return {number} The truncated value.
*/
function trunc(value) {
	return Math.trunc(value);
}
/**
* Converts the input *radians* value to degrees.
* @param {number} radians The input radians value.
* @return {number} The value in degrees
*/
function degrees(radians) {
	return 180 * radians / Math.PI;
}
/**
* Converts the input *degrees* value to radians.
* @param {number} degrees The input degrees value.
* @return {number} The value in radians.
*/
function radians(degrees) {
	return Math.PI * degrees / 180;
}
/**
* Returns the arc-cosine (in radians) of a number *value*;
* equivalent to *Math.acos*.
* @param {number} value The input number value.
* @return {number} The arc-cosine value.
*/
function acos(value) {
	return Math.acos(value);
}
/**
* Returns the hyperbolic arc-cosine of a number *value*;
* equivalent to *Math.acosh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic arc-cosine value.
*/
function acosh(value) {
	return Math.acosh(value);
}
/**
* Returns the arc-sine (in radians) of a number *value*;
* equivalent to *Math.asin*.
* @param {number} value The input number value.
* @return {number} The arc-sine value.
*/
function asin(value) {
	return Math.asin(value);
}
/**
* Returns the hyperbolic arc-sine of a number *value*;
* equivalent to *Math.asinh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic arc-sine value.
*/
function asinh(value) {
	return Math.asinh(value);
}
/**
* Returns the arc-tangent (in radians) of a number *value*;
* equivalent to *Math.atan*.
* @param {number} value The input number value.
* @return {number} The arc-tangent value.
*/
function atan(value) {
	return Math.atan(value);
}
/**
* Returns the angle in the plane (in radians) between the positive x-axis
* and the ray from (0, 0) to the point (*x*, *y*);
* equivalent to *Math.atan2*.
* @param {number} y The y coordinate of the point.
* @param {number} x The x coordinate of the point.
* @return {number} The arc-tangent angle.
*/
function atan2(y, x) {
	return Math.atan2(y, x);
}
/**
* Returns the hyperbolic arc-tangent of a number *value*;
* equivalent to *Math.atanh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic arc-tangent value.
*/
function atanh(value) {
	return Math.atanh(value);
}
/**
* Returns the cosine (in radians) of a number *value*;
* equivalent to *Math.cos*.
* @param {number} value The input number value.
* @return {number} The cosine value.
*/
function cos(value) {
	return Math.cos(value);
}
/**
* Returns the hyperbolic cosine (in radians) of a number *value*;
* equivalent to *Math.cosh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic cosine value.
*/
function cosh(value) {
	return Math.cosh(value);
}
/**
* Returns the sine (in radians) of a number *value*;
* equivalent to *Math.sin*.
* @param {number} value The input number value.
* @return {number} The sine value.
*/
function sin(value) {
	return Math.sin(value);
}
/**
* Returns the hyperbolic sine (in radians) of a number *value*;
* equivalent to *Math.sinh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic sine value.
*/
function sinh(value) {
	return Math.sinh(value);
}
/**
* Returns the tangent (in radians) of a number *value*;
* equivalent to *Math.tan*.
* @param {number} value The input number value.
* @return {number} The tangent value.
*/
function tan(value) {
	return Math.tan(value);
}
/**
* Returns the hyperbolic tangent (in radians) of a number *value*;
* equivalent to *Math.tanh*.
* @param {number} value The input number value.
* @return {number} The hyperbolic tangent value.
*/
function tanh(value) {
	return Math.tanh(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-map.js
/**
* @param {*} value
* @return {value is Map}
*/
function isMap(value) {
	return value instanceof Map;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-set.js
/**
* @param {*} value
* @return {value is Set}
*/
function isSet(value) {
	return value instanceof Set;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-map-or-set.js
/**
* @param {*} value
* @return {value is Map | Set}
*/
function isMapOrSet(value) {
	return isMap(value) || isSet(value);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/object.js
var object_exports = /* @__PURE__ */ __exportAll({
	entries: () => entries$1,
	has: () => has,
	keys: () => keys,
	object: () => object,
	values: () => values
});
function array(iter) {
	return Array.from(iter);
}
/**
* Returns a boolean indicating whether the *object* has the specified *key*
* as its own property (as opposed to inheriting it). If the *object* is a
* *Map* or *Set* instance, the *has* method will be invoked directly on the
* object, otherwise *Object.hasOwnProperty* is used.
* @template {string | number} K
* @template V
* @param {Map<K, V>|Set<K>|Record<K, V>} object The object, Map, or Set to
*  test for property membership.
* @param {K} key The property key to test for.
* @return {boolean} True if the object has the given key, false otherwise.
*/
function has(object, key) {
	return isMapOrSet(object) ? object.has(key) : object != null ? Object.hasOwn(object, `${key}`) : false;
}
/**
* Returns an array of a given *object*'s own enumerable property names. If
* the *object* is a *Map* instance, the *keys* method will be invoked
* directly on the object, otherwise *Object.keys* is used.
* @template {string | number} K
* @template V
* @param {Map<K, V>|Record<K, V>} object The input object or Map value.
* @return {K[]} An array of property key name strings.
*/
function keys(object) {
	return isMap(object) ? array(object.keys()) : object != null ? Object.keys(object) : [];
}
/**
* Returns an array of a given *object*'s own enumerable property values. If
* the *object* is a *Map* or *Set* instance, the *values* method will be
* invoked directly on the object, otherwise *Object.values* is used.
* @template {string | number} K
* @template V
* @param {Map<K, V> | Set<V> | Record<K, V>} object The input object, Map,
*  or Set value.
* @return {V[]} An array of property values.
*/
function values(object) {
	return isMapOrSet(object) ? array(object.values()) : object != null ? Object.values(object) : [];
}
/**
* Returns an array of a given *object*'s own enumerable keyed property
* `[key, value]` pairs. If the *object* is a *Map* or *Set* instance, the
* *entries* method will be invoked directly on the object, otherwise
* *Object.entries* is used.
* @template {string | number} K
* @template V
* @param {Map<K, V> | Set<V> | Record<K, V>} object The input object, Map,
*  or Set value.
* @return {[K, V][]} An array of property values.
*/
function entries$1(object) {
	return isMapOrSet(object) ? array(object.entries()) : object != null ? Object.entries(object) : [];
}
/**
* Returns a new object given iterable *entries* of `[key, value]` pairs.
* This method is Arquero's version of the *Object.fromEntries* method.
* @template {string | number} K
* @template V
* @param {Iterable<[K, V]>} entries An iterable collection of `[key, value]`
*  pairs, such as an array of two-element arrays or a *Map*.
* @return {Record<K, V>} An object of consolidated key-value pairs.
*/
function object(entries) {
	return entries ? Object.fromEntries(entries) : void 0;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/string.js
var string_exports = /* @__PURE__ */ __exportAll({
	endswith: () => endswith,
	lower: () => lower,
	match: () => match,
	normalize: () => normalize,
	padend: () => padend,
	padstart: () => padstart,
	parse_date: () => parse_date,
	parse_float: () => parse_float,
	parse_int: () => parse_int,
	repeat: () => repeat,
	replace: () => replace,
	split: () => split,
	startswith: () => startswith,
	substring: () => substring,
	trim: () => trim,
	upper: () => upper
});
/**
* Parses a string *value* and returns a Date instance. Beware: this method
* uses JavaScript's *Date.parse()* functionality, which is inconsistently
* implemented across browsers. That said,
* [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted strings such
* as those produced by *op.format_date* and *op.format_utcdate* should be
* supported across platforms. Note that "bare" ISO date strings such as
* `"2001-01-01"` are interpreted by JavaScript as indicating midnight of
* that day in Coordinated Universal Time (UTC), *not* local time. To
* indicate the local timezone, an ISO string can include additional time
* components and no `Z` suffix: `"2001-01-01T00:00"`.
* @param {*} value The input value.
* @return {Date} The parsed date value.
*/
function parse_date(value) {
	return value == null ? value : new Date(value);
}
/**
* Parses a string *value* and returns a floating point number.
* @param {*} value The input value.
* @return {number} The parsed number value.
*/
function parse_float(value) {
	return value == null ? value : Number.parseFloat(value);
}
/**
* Parses a string *value* and returns an integer of the specified radix
* (the base in mathematical numeral systems).
* @param {*} value The input value.
* @param {number} [radix] An integer between 2 and 36 that represents the
*  radix (the base in mathematical numeral systems) of the string. Be
*  careful: this does not default to 10! If *radix* is `undefined`, `0`,
*  or unspecified, JavaScript assumes the following: If the input string
*  begins with `"0x"` or `"0X"` (a zero, followed by lowercase or
*  uppercase X), the radix is assumed to be 16 and the rest of the string
*  is parsed as a hexidecimal number. If the input string begins with `"0"`
*  (a zero), the radix is assumed to be 8 (octal) or 10 (decimal). Exactly
*  which radix is chosen is implementation-dependent.  If the input string
*  begins with any other value, the radix is 10 (decimal).
* @return {number} The parsed integer value.
*/
function parse_int(value, radix) {
	return value == null ? value : Number.parseInt(value, radix);
}
/**
* Determines whether a string *value* ends with the characters of a
* specified *search* string, returning `true` or `false` as appropriate.
* @param {any} value The input string value.
* @param {string} search The search string to test for.
* @param {number} [length] If provided, used as the length of *value*
*  (default `value.length`).
* @return {boolean} True if the value ends with the search string,
*  false otherwise.
*/
function endswith(value, search, length) {
	return value == null ? false : String(value).endsWith(search, length);
}
/**
* Retrieves the result of matching a string *value* against a regular
* expression *regexp*. If no *index* is specified, returns an array
* whose contents depend on the presence or absence of the regular
* expression global (`g`) flag, or `null` if no matches are found. If the
* `g` flag is used, all results matching the complete regular expression
* will be returned, but capturing groups will not. If the `g` flag is not
* used, only the first complete match and its related capturing groups are
* returned.
*
* If specified, the *index* looks up a value of the resulting match. If
* *index* is a number, the corresponding index of the result array is
* returned. If *index* is a string, the value of the corresponding
* named capture group is returned, or `null` if there is no such group.
* @param {*} value The input string value.
* @param {*} regexp The regular expression to match against.
* @param {number|string} index The index into the match result array
*  or capture group.
* @return {string|string[]} The match result.
*/
function match(value, regexp, index) {
	const m = value == null ? value : String(value).match(regexp);
	return index == null || m == null ? m : typeof index === "number" ? m[index] : m.groups ? m.groups[index] : null;
}
/**
* Returns the Unicode normalization form of the string *value*.
* @param {*} value The input value to normalize.
* @param {string} form The Unicode normalization form, one of
*  `'NFC'` (default, canonical decomposition, followed by canonical
*  composition), `'NFD'` (canonical decomposition), `'NFKC'` (compatibility
*  decomposition, followed by canonical composition),
*  or `'NFKD'` (compatibility decomposition).
* @return {string} The normalized string value.
*/
function normalize(value, form) {
	return value == null ? value : String(value).normalize(form);
}
/**
* Pad a string *value* with a given *fill* string (applied from the end of
* *value* and repeated, if needed) so that the resulting string reaches a
* given *length*.
* @param {*} value The input value to pad.
* @param {number} length The length of the resulting string once the
*  *value* string has been padded. If the length is lower than
*  `value.length`, the *value* string will be returned as-is.
* @param {string} [fill] The string to pad the *value* string with
*  (default `''`). If *fill* is too long to stay within the target
*  *length*, it will be truncated: for left-to-right languages the
*  left-most part and for right-to-left languages the right-most will
*  be applied.
* @return {string} The padded string.
*/
function padend(value, length, fill) {
	return value == null ? value : String(value).padEnd(length, fill);
}
/**
* Pad a string *value* with a given *fill* string (applied from the start
* of *value* and repeated, if needed) so that the resulting string reaches
* a given *length*.
* @param {*} value The input value to pad.
* @param {number} length The length of the resulting string once the
*  *value* string has been padded. If the length is lower than
*  `value.length`, the *value* string will be returned as-is.
* @param {string} [fill] The string to pad the *value* string with
*  (default `''`). If *fill* is too long to stay within the target
*  *length*, it will be truncated: for left-to-right languages the
*  left-most part and for right-to-left languages the right-most will
*  be applied.
* @return {string} The padded string.
*/
function padstart(value, length, fill) {
	return value == null ? value : String(value).padStart(length, fill);
}
/**
* Returns the string *value* converted to upper case.
* @param {*} value The input string value.
* @return {string} The upper case string.
*/
function upper(value) {
	return value == null ? value : String(value).toUpperCase();
}
/**
* Returns the string *value* converted to lower case.
* @param {*} value The input string value.
* @return {string} The lower case string.
*/
function lower(value) {
	return value == null ? value : String(value).toLowerCase();
}
/**
* Returns a new string which contains the specified *number* of copies of
* the *value* string concatenated together.
* @param {*} value The input string to repeat.
* @param {*} number An integer between `0` and `+Infinity`, indicating the
*  number of times to repeat the string.
* @return {string} The repeated string.
*/
function repeat(value, number) {
	return value == null ? value : String(value).repeat(number);
}
/**
* Returns a new string with some or all matches of a *pattern* replaced by
* a *replacement*. The *pattern* can be a string or a regular expression,
* and the *replacement* must be a string. If *pattern* is a string, only
* the first occurrence will be replaced; to make multiple replacements, use
* a regular expression *pattern* with a `g` (global) flag.
* @param {*} value The input string value.
* @param {*} pattern The pattern string or regular expression to replace.
* @param {*} replacement The replacement string to use.
* @return {string} The string with patterns replaced.
*/
function replace(value, pattern, replacement) {
	return value == null ? value : String(value).replace(pattern, String(replacement));
}
/**
* Divides a string *value* into an ordered list of substrings based on a
* *separator* pattern, puts these substrings into an array, and returns the
* array.
* @param {*} value The input string value.
* @param {*} separator A string or regular expression pattern describing
*  where each split should occur.
* @param {number} [limit] An integer specifying a limit on the number of
*  substrings to be included in the array.
* @return {string[]}
*/
function split(value, separator, limit) {
	return value == null ? [] : String(value).split(separator, limit);
}
/**
* Determines whether a string *value* starts with the characters of a
* specified *search* string, returning `true` or `false` as appropriate.
* @param {*} value The input string value.
* @param {string} search The search string to test for.
* @param {number} [position=0] The position in the *value* string at which
*  to begin searching (default `0`).
* @return {boolean} True if the string starts with the search pattern,
*  false otherwise.
*/
function startswith(value, search, position) {
	return value == null ? false : String(value).startsWith(search, position);
}
/**
* Returns the part of the string *value* between the *start* and *end*
* indexes, or to the end of the string.
* @param {*} value The input string value.
* @param {number} [start=0] The index of the first character to include in
*  the returned substring (default `0`).
* @param {number} [end] The index of the first character to exclude from
*  the returned substring (default `value.length`).
* @return {string} The substring.
*/
function substring(value, start, end) {
	return value == null ? value : String(value).substring(start, end);
}
/**
* Returns a new string with whitespace removed from both ends of the input
* *value* string. Whitespace in this context is all the whitespace
* characters (space, tab, no-break space, etc.) and all the line terminator
* characters (LF, CR, etc.).
* @param {*} value The input string value to trim.
* @return {string} The trimmed string.
*/
function trim(value) {
	return value == null ? value : String(value).trim();
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/functions/index.js
var functions = {
	bin,
	equal,
	recode,
	sequence,
	...array_exports,
	...date_exports,
	...json_exports,
	...math_exports,
	...object_exports,
	...string_exports
};
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-bigint.js
/**
* @param {*} value
* @returns {value is bigint}
*/
function isBigInt(value) {
	return typeof value === "bigint";
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/to-string.js
function toString$1(v) {
	return v === void 0 ? v + "" : isBigInt(v) ? v + "n" : JSON.stringify(v);
}
/**
* Generate an object representing the current table row.
* @param {...string} names The column names to include in the object.
*  If unspecified, all columns are included.
* @return {Struct} The generated row object.
*/
({ ...functions });
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/error.js
function error(message, cause) {
	throw Error(message, { cause });
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-function.js
/**
* @param {*} value
* @returns {value is Function}
*/
function isFunction(value) {
	return typeof value === "function";
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/bins.js
function bins(min, max, maxbins = 15, nice = true, minstep = 0, step) {
	const base = 10;
	const logb = Math.LN10;
	if (step == null) {
		const level = Math.ceil(Math.log(maxbins) / logb);
		const span = max - min || Math.abs(min) || 1;
		const div = [5, 2];
		step = Math.max(minstep, Math.pow(base, Math.round(Math.log(span) / logb) - level));
		while (Math.ceil(span / step) > maxbins) step *= base;
		const n = div.length;
		for (let i = 0; i < n; ++i) {
			const v = step / div[i];
			if (v >= minstep && span / v <= maxbins) step = v;
		}
	}
	if (nice) {
		let v = Math.log(step);
		const precision = v >= 0 ? 0 : ~~(-v / logb) + 1;
		const eps = Math.pow(base, -precision - 1);
		v = Math.floor(min / step + eps) * step;
		min = min < v ? v - step : v;
		max = Math.ceil(max / step) * step;
	}
	return [
		min,
		max === min ? min + step : max,
		step
	];
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/key-function.js
function key(value) {
	const type = typeof value;
	return type === "string" ? `"${value}"` : type !== "object" || !value ? value : isDate(value) ? +value : isArray$1(value) || isTypedArray(value) ? `[${value.map(key)}]` : isRegExp(value) ? value + "" : objectKey(value);
}
function objectKey(value) {
	let s = "{";
	let i = -1;
	for (const k in value) {
		if (++i > 0) s += ",";
		s += `"${k}":${key(value[k])}`;
	}
	s += "}";
	return s;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/distinct-map.js
function distinctMap() {
	const map = /* @__PURE__ */ new Map();
	return {
		count() {
			return map.size;
		},
		values() {
			return Array.from(map.values(), (_) => _.v);
		},
		increment(v) {
			const k = key(v);
			const e = map.get(k);
			e ? ++e.n : map.set(k, {
				v,
				n: 1
			});
		},
		decrement(v) {
			const k = key(v);
			const e = map.get(k);
			e.n === 1 ? map.delete(k) : --e.n;
		},
		forEach(fn) {
			map.forEach(({ v, n }) => fn(v, n));
		}
	};
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/no-op.js
function noop() {}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/product.js
function product(values, start = 0, stop = values.length) {
	let prod = values[start++];
	for (let i = start; i < stop; ++i) prod *= values[i];
	return prod;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/aggregate-functions.js
/**
* Initialize an aggregate operator.
*/
function initOp(op) {
	op.init = op.init || noop;
	op.add = op.add || noop;
	op.rem = op.rem || noop;
	return op;
}
function initProduct(s, value) {
	s.product_v = false;
	return s.product = value;
}
/**
* Initialize an aggregate operator.
* @callback AggregateInit
* @param {object} state The aggregate state object.
* @return {void}
*/
/**
* Add a value to an aggregate operator.
* @callback AggregateAdd
* @param {object} state The aggregate state object.
* @param {*} value The value to add.
* @return {void}
*/
/**
* Remove a value from an aggregate operator.
* @callback AggregateRem
* @param {object} state The aggregate state object.
* @param {*} value The value to remove.
* @return {void}
*/
/**
* Retrive an output value from an aggregate operator.
* @callback AggregateValue
* @param {object} state The aggregate state object.
* @return {*} The output value.
*/
/**
* An operator instance for an aggregate function.
* @typedef {object} AggregateOperator
* @property {AggregateInit} init Initialize the operator.
* @property {AggregateAdd} [add] Add a value to the operator state.
* @property {AggregateRem} [rem] Remove a value from the operator state.
* @property {AggregateValue} value Retrieve an output value.
*/
/**
* Create a new aggregate operator instance.
* @callback AggregateCreate
* @param {...any} params The aggregate operator parameters.
* @return {AggregateOperator} The instantiated aggregate operator.
*/
/**
* An operator definition for an aggregate function.
* @typedef {object} AggregateDef
* @property {AggregateCreate} create Create a new operator instance.
* @property {number[]} param Two-element array containing the
*  counts of input fields and additional parameters.
* @property {string[]} [req] Names of operators required by this one.
* @property {string[]} [stream] Names of operators required by this one
*  for streaming operations (value removes).
*/
/**
* Aggregate operator definitions.
*/
var aggregateFunctions = {
	/** @type {AggregateDef} */
	count: {
		create: () => initOp({ value: (s) => s.count }),
		param: []
	},
	/** @type {AggregateDef} */
	array_agg: {
		create: () => initOp({
			init: (s) => s.values = true,
			value: (s) => s.list.values(s.stream)
		}),
		param: [1]
	},
	/** @type {AggregateDef} */
	object_agg: {
		create: () => initOp({
			init: (s) => s.values = true,
			value: (s) => Object.fromEntries(s.list.values())
		}),
		param: [2]
	},
	/** @type {AggregateDef} */
	map_agg: {
		create: () => initOp({
			init: (s) => s.values = true,
			value: (s) => new Map(s.list.values())
		}),
		param: [2]
	},
	/** @type {AggregateDef} */
	entries_agg: {
		create: () => initOp({
			init: (s) => s.values = true,
			value: (s) => s.list.values(s.stream)
		}),
		param: [2]
	},
	/** @type {AggregateDef} */
	any: {
		create: () => initOp({
			add: (s, v) => {
				if (s.any == null) s.any = v;
			},
			value: (s) => s.valid ? s.any : void 0
		}),
		param: [1]
	},
	/** @type {AggregateDef} */
	valid: {
		create: () => initOp({ value: (s) => s.valid }),
		param: [1]
	},
	/** @type {AggregateDef} */
	invalid: {
		create: () => initOp({ value: (s) => s.count - s.valid }),
		param: [1]
	},
	/** @type {AggregateDef} */
	distinct: {
		create: () => ({
			init: (s) => s.distinct = distinctMap(),
			value: (s) => s.distinct.count() + (s.valid === s.count ? 0 : 1),
			add: (s, v) => s.distinct.increment(v),
			rem: (s, v) => s.distinct.decrement(v)
		}),
		param: [1]
	},
	/** @type {AggregateDef} */
	array_agg_distinct: {
		create: () => initOp({ value: (s) => s.distinct.values() }),
		param: [1],
		req: ["distinct"]
	},
	/** @type {AggregateDef} */
	mode: {
		create: () => initOp({ value: (s) => {
			let mode = void 0;
			let max = 0;
			s.distinct.forEach((value, count) => {
				if (count > max) {
					max = count;
					mode = value;
				}
			});
			return mode;
		} }),
		param: [1],
		req: ["distinct"]
	},
	/** @type {AggregateDef} */
	sum: {
		create: () => ({
			init: (s) => s.sum = 0,
			value: (s) => s.valid ? s.sum : void 0,
			add: (s, v) => isBigInt(v) ? s.sum === 0 ? s.sum = v : s.sum += v : s.sum += +v,
			rem: (s, v) => s.sum -= v
		}),
		param: [1]
	},
	/** @type {AggregateDef} */
	product: {
		create: () => ({
			init: (s) => initProduct(s, 1),
			value: (s) => s.valid ? s.product_v ? initProduct(s, product(s.list.values())) : s.product : void 0,
			add: (s, v) => isBigInt(v) ? s.product === 1 ? s.product = v : s.product *= v : s.product *= v,
			rem: (s, v) => v == 0 || v === Infinity || v === -Infinity ? s.product_v = true : s.product /= v
		}),
		param: [1],
		stream: ["array_agg"]
	},
	/** @type {AggregateDef} */
	mean: {
		create: () => ({
			init: (s) => s.mean = 0,
			value: (s) => s.valid ? s.mean : void 0,
			add: (s, v) => {
				s.mean_d = v - s.mean;
				s.mean += s.mean_d / s.valid;
			},
			rem: (s, v) => {
				s.mean_d = v - s.mean;
				s.mean -= s.valid ? s.mean_d / s.valid : s.mean;
			}
		}),
		param: [1]
	},
	/** @type {AggregateDef} */
	average: {
		create: () => initOp({ value: (s) => s.valid ? s.mean : void 0 }),
		param: [1],
		req: ["mean"]
	},
	/** @type {AggregateDef} */
	variance: {
		create: () => ({
			init: (s) => s.dev = 0,
			value: (s) => s.valid > 1 ? s.dev / (s.valid - 1) : void 0,
			add: (s, v) => s.dev += s.mean_d * (v - s.mean),
			rem: (s, v) => s.dev -= s.mean_d * (v - s.mean)
		}),
		param: [1],
		req: ["mean"]
	},
	/** @type {AggregateDef} */
	variancep: {
		create: () => initOp({ value: (s) => s.valid > 1 ? s.dev / s.valid : void 0 }),
		param: [1],
		req: ["variance"]
	},
	/** @type {AggregateDef} */
	stdev: {
		create: () => initOp({ value: (s) => s.valid > 1 ? Math.sqrt(s.dev / (s.valid - 1)) : void 0 }),
		param: [1],
		req: ["variance"]
	},
	/** @type {AggregateDef} */
	stdevp: {
		create: () => initOp({ value: (s) => s.valid > 1 ? Math.sqrt(s.dev / s.valid) : void 0 }),
		param: [1],
		req: ["variance"]
	},
	/** @type {AggregateDef} */
	min: {
		create: () => ({
			init: (s) => s.min = void 0,
			value: (s) => s.min = Number.isNaN(s.min) ? s.list.min() : s.min,
			add: (s, v) => {
				if (v < s.min || s.min === void 0) s.min = v;
			},
			rem: (s, v) => {
				if (v <= s.min) s.min = NaN;
			}
		}),
		param: [1],
		stream: ["array_agg"]
	},
	/** @type {AggregateDef} */
	max: {
		create: () => ({
			init: (s) => s.max = void 0,
			value: (s) => s.max = Number.isNaN(s.max) ? s.list.max() : s.max,
			add: (s, v) => {
				if (v > s.max || s.max === void 0) s.max = v;
			},
			rem: (s, v) => {
				if (v >= s.max) s.max = NaN;
			}
		}),
		param: [1],
		stream: ["array_agg"]
	},
	/** @type {AggregateDef} */
	quantile: {
		create: (p) => initOp({ value: (s) => s.list.quantile(p) }),
		param: [1, 1],
		req: ["array_agg"]
	},
	/** @type {AggregateDef} */
	median: {
		create: () => initOp({ value: (s) => s.list.quantile(.5) }),
		param: [1],
		req: ["array_agg"]
	},
	/** @type {AggregateDef} */
	covariance: {
		create: () => ({
			init: (s) => {
				s.cov = s.mean_x = s.mean_y = s.dev_x = s.dev_y = 0;
			},
			value: (s) => s.valid > 1 ? s.cov / (s.valid - 1) : void 0,
			add: (s, x, y) => {
				const dx = x - s.mean_x;
				const dy = y - s.mean_y;
				s.mean_x += dx / s.valid;
				s.mean_y += dy / s.valid;
				const dy2 = y - s.mean_y;
				s.dev_x += dx * (x - s.mean_x);
				s.dev_y += dy * dy2;
				s.cov += dx * dy2;
			},
			rem: (s, x, y) => {
				const dx = x - s.mean_x;
				const dy = y - s.mean_y;
				s.mean_x -= s.valid ? dx / s.valid : s.mean_x;
				s.mean_y -= s.valid ? dy / s.valid : s.mean_y;
				const dy2 = y - s.mean_y;
				s.dev_x -= dx * (x - s.mean_x);
				s.dev_y -= dy * dy2;
				s.cov -= dx * dy2;
			}
		}),
		param: [2]
	},
	/** @type {AggregateDef} */
	covariancep: {
		create: () => initOp({ value: (s) => s.valid > 1 ? s.cov / s.valid : void 0 }),
		param: [2],
		req: ["covariance"]
	},
	/** @type {AggregateDef} */
	corr: {
		create: () => initOp({ value: (s) => s.valid > 1 ? s.cov / (Math.sqrt(s.dev_x) * Math.sqrt(s.dev_y)) : void 0 }),
		param: [2],
		req: ["covariance"]
	},
	/** @type {AggregateDef} */
	bins: {
		create: (maxbins, nice, minstep, step) => initOp({ value: (s) => bins(s.min, s.max, maxbins, nice, minstep, step) }),
		param: [1, 4],
		req: ["min", "max"]
	}
};
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/window-functions.js
/**
* Initialize a window operator.
* @callback WindowInit
* @return {void}
*/
/**
* A storage object for the state of the window.
* @typedef {import('../verbs/window/window-state.js').windowState} WindowState
*/
/**
* Retrieve an output value from a window operator.
* @callback WindowValue
* @param {WindowState} state The window state object.
* @return {*} The output value.
*/
/**
* Initialize an aggregate operator.
* @typedef {import('./aggregate-functions.js').AggregateInit} AggregateInit
*/
/**
* Retrive an output value from an aggregate operator.
* @typedef {import('./aggregate-functions.js').AggregateValue} AggregateValue
*/
/**
* An operator instance for a window function.
* @typedef {object} WindowOperator
* @property {AggregateInit} init Initialize the operator.
* @property {AggregateValue} value Retrieve an output value.
*/
/**
* Create a new window operator instance.
* @callback WindowCreate
* @param {...any} params The aggregate operator parameters.
* @return {WindowOperator} The instantiated window operator.
*/
/**
* Create a new aggregate operator instance.
* @typedef {import('./aggregate-functions.js').AggregateCreate} AggregateCreate
*/
/**
* An operator definition for a window function.
* @typedef {object} WindowDef
* @property {AggregateCreate} create Create a new operator instance.
* @property {number[]} param Two-element array containing the
*  counts of input fields and additional parameters.
*/
var rank = {
	create() {
		let rank;
		return {
			init: () => rank = 1,
			value: (w) => {
				const i = w.index;
				return i && !w.peer(i) ? rank = i + 1 : rank;
			}
		};
	},
	param: []
};
var cume_dist = {
	create() {
		let cume;
		return {
			init: () => cume = 0,
			value: (w) => {
				const { index, peer, size } = w;
				let i = index;
				if (cume < i) {
					while (i + 1 < size && peer(i + 1)) ++i;
					cume = i;
				}
				return (1 + cume) / size;
			}
		};
	},
	param: []
};
/**
* Window operator definitions.
*/
var windowFunctions = {
	/** @type {WindowDef} */
	row_number: {
		create() {
			return {
				init: noop,
				value: (w) => w.index + 1
			};
		},
		param: []
	},
	/** @type {WindowDef} */
	rank,
	/** @type {WindowDef} */
	avg_rank: {
		create() {
			let j, rank;
			return {
				init: () => (j = -1, rank = 1),
				value: (w) => {
					const i = w.index;
					if (i >= j) {
						for (rank = j = i + 1; w.peer(j); rank += ++j);
						rank /= j - i;
					}
					return rank;
				}
			};
		},
		param: []
	},
	/** @type {WindowDef} */
	dense_rank: {
		create() {
			let drank;
			return {
				init: () => drank = 1,
				value: (w) => {
					const i = w.index;
					return i && !w.peer(i) ? ++drank : drank;
				}
			};
		},
		param: []
	},
	/** @type {WindowDef} */
	percent_rank: {
		create() {
			const { init, value } = rank.create();
			return {
				init,
				value: (w) => (value(w) - 1) / (w.size - 1)
			};
		},
		param: []
	},
	/** @type {WindowDef} */
	cume_dist,
	/** @type {WindowDef} */
	ntile: {
		create(num) {
			num = +num;
			if (!(num > 0)) error("ntile num must be greater than zero.");
			const { init, value } = cume_dist.create();
			return {
				init,
				value: (w) => Math.ceil(num * value(w))
			};
		},
		param: [0, 1]
	},
	/** @type {WindowDef} */
	lag: {
		create(offset, defaultValue = void 0) {
			offset = +offset || 1;
			return {
				init: noop,
				value: (w, f) => {
					const i = w.index - offset;
					return i >= 0 ? w.value(i, f) : defaultValue;
				}
			};
		},
		param: [1, 2]
	},
	/** @type {WindowDef} */
	lead: {
		create(offset, defaultValue = void 0) {
			offset = +offset || 1;
			return {
				init: noop,
				value: (w, f) => {
					const i = w.index + offset;
					return i < w.size ? w.value(i, f) : defaultValue;
				}
			};
		},
		param: [1, 2]
	},
	/** @type {WindowDef} */
	first_value: {
		create() {
			return {
				init: noop,
				value: (w, f) => w.value(w.i0, f)
			};
		},
		param: [1]
	},
	/** @type {WindowDef} */
	last_value: {
		create() {
			return {
				init: noop,
				value: (w, f) => w.value(w.i1 - 1, f)
			};
		},
		param: [1]
	},
	/** @type {WindowDef} */
	nth_value: {
		create(nth) {
			nth = +nth;
			if (!(nth > 0)) error("nth_value nth must be greater than zero.");
			return {
				init: noop,
				value: (w, f) => {
					const i = w.i0 + (nth - 1);
					return i < w.i1 ? w.value(i, f) : void 0;
				}
			};
		},
		param: [1, 1]
	},
	/** @type {WindowDef} */
	fill_down: {
		create(defaultValue = void 0) {
			let value;
			return {
				init: () => value = defaultValue,
				value: (w, f) => {
					const v = w.value(w.index, f);
					return isValid(v) ? value = v : value;
				}
			};
		},
		param: [1, 1]
	},
	/** @type {WindowDef} */
	fill_up: {
		create(defaultValue = void 0) {
			let value, idx;
			return {
				init: () => (value = defaultValue, idx = -1),
				value: (w, f) => w.index <= idx ? value : (idx = find(w, f, w.index)) >= 0 ? value = w.value(idx, f) : (idx = w.size, value = defaultValue)
			};
		},
		param: [1, 1]
	}
};
function find(w, f, i) {
	for (const n = w.size; i < n; ++i) if (isValid(w.value(i, f))) return i;
	return -1;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/index.js
/**
* Check if an aggregate function with the given name exists.
* @param {string} name The name of the aggregate function.
* @return {boolean} True if found, false otherwise.
*/
function hasAggregate(name) {
	return Object.hasOwn(aggregateFunctions, name);
}
/**
* Check if a window function with the given name exists.
* @param {string} name The name of the window function.
* @return {boolean} True if found, false otherwise.
*/
function hasWindow(name) {
	return Object.hasOwn(windowFunctions, name);
}
/**
* Check if an expression function with the given name exists.
* @param {string} name The name of the function.
* @return {boolean} True if found, false otherwise.
*/
function hasFunction(name) {
	return Object.hasOwn(functions, name) || name === "row_object";
}
/**
* Get an aggregate function definition.
* @param {string} name The name of the aggregate function.
* @return {import('./aggregate-functions.js').AggregateDef}
*  The aggregate function definition, or undefined if not found.
*/
function getAggregate(name) {
	return hasAggregate(name) && aggregateFunctions[name];
}
/**
* Get a window function definition.
* @param {string} name The name of the window function.
* @return {import('./window-functions.js').WindowDef}
*  The window function definition, or undefined if not found.
*/
function getWindow(name) {
	return hasWindow(name) && windowFunctions[name];
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/entries.js
function entries(value) {
	return isArray$1(value) ? value : isMap(value) ? value.entries() : value ? Object.entries(value) : [];
}
var Literal = "Literal";
var ObjectExpression = "ObjectExpression";
var Property = "Property";
var Column = "Column";
var Constant = "Constant";
var Dictionary = "Dictionary";
var Function$1 = "Function";
var Parameter = "Parameter";
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/ast/walk.js
function walk(node, ctx, visitors, parent) {
	const visit = visitors[node.type] || visitors["Default"];
	if (visit && visit(node, ctx, parent) === false) return;
	const walker = walkers[node.type];
	if (walker) walker(node, ctx, visitors);
}
var unary = (node, ctx, visitors) => {
	walk(node.argument, ctx, visitors, node);
};
var binary = (node, ctx, visitors) => {
	walk(node.left, ctx, visitors, node);
	walk(node.right, ctx, visitors, node);
};
var ternary = (node, ctx, visitors) => {
	walk(node.test, ctx, visitors, node);
	walk(node.consequent, ctx, visitors, node);
	if (node.alternate) walk(node.alternate, ctx, visitors, node);
};
var func = (node, ctx, visitors) => {
	list$1(node.params, ctx, visitors, node);
	walk(node.body, ctx, visitors, node);
};
var call = (node, ctx, visitors) => {
	walk(node.callee, ctx, visitors, node);
	list$1(node.arguments, ctx, visitors, node);
};
var list$1 = (nodes, ctx, visitors, node) => {
	nodes.forEach((item) => walk(item, ctx, visitors, node));
};
var walkers = {
	TemplateLiteral: (node, ctx, visitors) => {
		list$1(node.expressions, ctx, visitors, node);
		list$1(node.quasis, ctx, visitors, node);
	},
	MemberExpression: (node, ctx, visitors) => {
		walk(node.object, ctx, visitors, node);
		walk(node.property, ctx, visitors, node);
	},
	CallExpression: call,
	NewExpression: call,
	ArrayExpression: (node, ctx, visitors) => {
		list$1(node.elements, ctx, visitors, node);
	},
	AssignmentExpression: binary,
	AwaitExpression: unary,
	BinaryExpression: binary,
	LogicalExpression: binary,
	UnaryExpression: unary,
	UpdateExpression: unary,
	ConditionalExpression: ternary,
	ObjectExpression: (node, ctx, visitors) => {
		list$1(node.properties, ctx, visitors, node);
	},
	Property: (node, ctx, visitors) => {
		walk(node.key, ctx, visitors, node);
		walk(node.value, ctx, visitors, node);
	},
	ArrowFunctionExpression: func,
	FunctionExpression: func,
	FunctionDeclaration: func,
	VariableDeclaration: (node, ctx, visitors) => {
		list$1(node.declarations, ctx, visitors, node);
	},
	VariableDeclarator: (node, ctx, visitors) => {
		walk(node.id, ctx, visitors, node);
		walk(node.init, ctx, visitors, node);
	},
	SpreadElement: (node, ctx, visitors) => {
		walk(node.argument, ctx, visitors, node);
	},
	BlockStatement: (node, ctx, visitors) => {
		list$1(node.body, ctx, visitors, node);
	},
	ExpressionStatement: (node, ctx, visitors) => {
		walk(node.expression, ctx, visitors, node);
	},
	IfStatement: ternary,
	ForStatement: (node, ctx, visitors) => {
		walk(node.init, ctx, visitors, node);
		walk(node.test, ctx, visitors, node);
		walk(node.update, ctx, visitors, node);
		walk(node.body, ctx, visitors, node);
	},
	WhileStatement: (node, ctx, visitors) => {
		walk(node.test, ctx, visitors, node);
		walk(node.body, ctx, visitors, node);
	},
	DoWhileStatement: (node, ctx, visitors) => {
		walk(node.body, ctx, visitors, node);
		walk(node.test, ctx, visitors, node);
	},
	SwitchStatement: (node, ctx, visitors) => {
		walk(node.discriminant, ctx, visitors, node);
		list$1(node.cases, ctx, visitors, node);
	},
	SwitchCase: (node, ctx, visitors) => {
		if (node.test) walk(node.test, ctx, visitors, node);
		list$1(node.consequent, ctx, visitors, node);
	},
	ReturnStatement: unary,
	Program: (node, ctx, visitors) => {
		walk(node.body[0], ctx, visitors, node);
	}
};
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/ast/util.js
function is(type, node) {
	return node && node.type === type;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/rewrite.js
var dictOps = {
	"==": 1,
	"!=": 1,
	"===": 1,
	"!==": 1
};
/**
* Rewrite AST node to be a table column reference.
* Additionally optimizes dictionary column operations.
* @param {object} ref AST node to rewrite to a column reference.
* @param {string} name The name of the column.
* @param {number} [index] The table index of the column.
* @param {object} [col] The actual table column instance.
* @param {object} [op] Parent AST node operating on the column reference.
*/
function rewrite(ref, name, index = 0, col = void 0, op = void 0) {
	ref.type = Column;
	ref.name = name;
	ref.table = index;
	if (isArrayType(col)) ref.array = true;
	if (op && col && isFunction(col.keyFor)) {
		const lit = dictOps[op.operator] ? op.left === ref ? op.right : op.left : op.callee && op.callee.name === "equal" ? op.arguments[op.arguments[0] === ref ? 1 : 0] : null;
		if (lit && lit.type === "Literal") rewriteDictionary(op, ref, lit, col.keyFor(lit.value));
	}
	return ref;
}
function rewriteDictionary(op, ref, lit, key) {
	if (key < 0) {
		op.type = Literal;
		op.value = false;
		op.raw = "false";
	} else {
		ref.type = Dictionary;
		lit.value = key;
		lit.raw = key + "";
	}
	return true;
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/row-object.js
var ROW_OBJECT = "row_object";
function rowObjectExpression(node, table, props = table.columnNames()) {
	node.type = ObjectExpression;
	const p = node.properties = [];
	for (const prop of entries(props)) {
		const [name, key] = isArray$1(prop) ? prop : [prop, prop];
		p.push({
			type: Property,
			key: {
				type: Literal,
				raw: toString$1(key)
			},
			value: rewrite({ computed: true }, name, 0, table.column(name))
		});
	}
	return node;
}
//#endregion
//#region ../../node_modules/.pnpm/acorn@8.18.0/node_modules/acorn/dist/acorn.mjs
var astralIdentifierCodes = [
	509,
	0,
	227,
	0,
	150,
	4,
	294,
	9,
	1368,
	2,
	2,
	1,
	6,
	3,
	41,
	2,
	5,
	0,
	166,
	1,
	574,
	3,
	9,
	9,
	7,
	9,
	32,
	4,
	318,
	1,
	78,
	5,
	71,
	10,
	50,
	3,
	123,
	2,
	54,
	14,
	32,
	10,
	3,
	1,
	11,
	3,
	46,
	10,
	8,
	0,
	46,
	9,
	7,
	2,
	37,
	13,
	2,
	9,
	6,
	1,
	45,
	0,
	13,
	2,
	49,
	13,
	9,
	3,
	2,
	11,
	83,
	11,
	7,
	0,
	3,
	0,
	158,
	11,
	6,
	9,
	7,
	3,
	56,
	1,
	2,
	6,
	3,
	1,
	3,
	2,
	10,
	0,
	11,
	1,
	3,
	6,
	4,
	4,
	68,
	8,
	2,
	0,
	3,
	0,
	2,
	3,
	2,
	4,
	2,
	0,
	15,
	1,
	83,
	17,
	10,
	9,
	5,
	0,
	82,
	19,
	13,
	9,
	214,
	6,
	3,
	8,
	28,
	1,
	83,
	16,
	16,
	9,
	82,
	12,
	9,
	9,
	7,
	19,
	58,
	14,
	5,
	9,
	243,
	14,
	166,
	9,
	71,
	5,
	2,
	1,
	3,
	3,
	2,
	0,
	2,
	1,
	13,
	9,
	120,
	6,
	3,
	6,
	4,
	0,
	29,
	9,
	41,
	6,
	2,
	3,
	9,
	0,
	10,
	10,
	47,
	15,
	199,
	7,
	137,
	9,
	54,
	7,
	2,
	7,
	17,
	9,
	57,
	21,
	2,
	13,
	123,
	5,
	4,
	0,
	2,
	1,
	2,
	6,
	2,
	0,
	9,
	9,
	49,
	4,
	2,
	1,
	2,
	4,
	9,
	9,
	55,
	9,
	266,
	3,
	10,
	1,
	2,
	0,
	49,
	6,
	4,
	4,
	14,
	10,
	5350,
	0,
	7,
	14,
	11465,
	27,
	2343,
	9,
	87,
	9,
	39,
	4,
	60,
	6,
	26,
	9,
	535,
	9,
	470,
	0,
	2,
	54,
	8,
	3,
	82,
	0,
	12,
	1,
	19628,
	1,
	4178,
	9,
	519,
	45,
	3,
	22,
	543,
	4,
	4,
	5,
	9,
	7,
	3,
	6,
	31,
	3,
	149,
	2,
	1418,
	49,
	513,
	54,
	5,
	49,
	9,
	0,
	15,
	0,
	23,
	4,
	2,
	14,
	1361,
	6,
	2,
	16,
	3,
	6,
	2,
	1,
	2,
	4,
	101,
	0,
	161,
	6,
	10,
	9,
	357,
	0,
	62,
	13,
	499,
	13,
	245,
	1,
	2,
	9,
	233,
	0,
	3,
	0,
	8,
	1,
	6,
	0,
	475,
	6,
	110,
	6,
	6,
	9,
	4759,
	9,
	787719,
	239
];
var astralIdentifierStartCodes = [
	0,
	11,
	2,
	25,
	2,
	18,
	2,
	1,
	2,
	14,
	3,
	13,
	35,
	122,
	70,
	52,
	268,
	28,
	4,
	48,
	48,
	31,
	14,
	29,
	6,
	37,
	11,
	29,
	3,
	35,
	5,
	7,
	2,
	4,
	43,
	157,
	19,
	35,
	5,
	35,
	5,
	39,
	9,
	51,
	13,
	10,
	2,
	14,
	2,
	6,
	2,
	1,
	2,
	10,
	2,
	14,
	2,
	6,
	2,
	1,
	4,
	51,
	13,
	310,
	10,
	21,
	11,
	7,
	25,
	5,
	2,
	41,
	2,
	8,
	70,
	5,
	3,
	0,
	2,
	43,
	2,
	1,
	4,
	0,
	3,
	22,
	11,
	22,
	10,
	30,
	66,
	18,
	2,
	1,
	11,
	21,
	11,
	25,
	7,
	25,
	39,
	55,
	7,
	1,
	65,
	0,
	16,
	3,
	2,
	2,
	2,
	28,
	43,
	28,
	4,
	28,
	36,
	7,
	2,
	27,
	28,
	53,
	11,
	21,
	11,
	18,
	14,
	17,
	111,
	72,
	56,
	50,
	14,
	50,
	14,
	35,
	39,
	27,
	10,
	22,
	251,
	41,
	7,
	1,
	17,
	5,
	57,
	28,
	11,
	0,
	9,
	21,
	43,
	17,
	47,
	20,
	28,
	22,
	13,
	52,
	58,
	1,
	3,
	0,
	14,
	44,
	33,
	24,
	27,
	35,
	30,
	0,
	3,
	0,
	9,
	34,
	4,
	0,
	13,
	47,
	15,
	3,
	22,
	0,
	2,
	0,
	36,
	17,
	2,
	24,
	20,
	1,
	64,
	6,
	2,
	0,
	2,
	3,
	2,
	14,
	2,
	9,
	8,
	46,
	39,
	7,
	3,
	1,
	3,
	21,
	2,
	6,
	2,
	1,
	2,
	4,
	4,
	0,
	19,
	0,
	13,
	4,
	31,
	9,
	2,
	0,
	3,
	0,
	2,
	37,
	2,
	0,
	26,
	0,
	2,
	0,
	45,
	52,
	19,
	3,
	21,
	2,
	31,
	47,
	21,
	1,
	2,
	0,
	185,
	46,
	42,
	3,
	37,
	47,
	21,
	0,
	60,
	42,
	14,
	0,
	72,
	26,
	38,
	6,
	186,
	43,
	117,
	63,
	32,
	7,
	3,
	0,
	3,
	7,
	2,
	1,
	2,
	23,
	16,
	0,
	2,
	0,
	95,
	7,
	3,
	38,
	17,
	0,
	2,
	0,
	29,
	0,
	11,
	39,
	8,
	0,
	22,
	0,
	12,
	45,
	20,
	0,
	19,
	72,
	200,
	32,
	32,
	8,
	2,
	36,
	18,
	0,
	50,
	29,
	113,
	6,
	2,
	1,
	2,
	37,
	22,
	0,
	26,
	5,
	2,
	1,
	2,
	31,
	15,
	0,
	24,
	43,
	261,
	18,
	16,
	0,
	2,
	12,
	2,
	33,
	125,
	0,
	80,
	921,
	103,
	110,
	18,
	195,
	2637,
	96,
	16,
	1071,
	18,
	5,
	26,
	3994,
	6,
	582,
	6842,
	29,
	1763,
	568,
	8,
	30,
	18,
	78,
	18,
	29,
	19,
	47,
	17,
	3,
	32,
	20,
	6,
	18,
	433,
	44,
	212,
	63,
	33,
	24,
	3,
	24,
	45,
	74,
	6,
	0,
	67,
	12,
	65,
	1,
	2,
	0,
	15,
	4,
	10,
	7381,
	42,
	31,
	98,
	114,
	8702,
	3,
	2,
	6,
	2,
	1,
	2,
	290,
	16,
	0,
	30,
	2,
	3,
	0,
	15,
	3,
	9,
	395,
	2309,
	106,
	6,
	12,
	4,
	8,
	8,
	9,
	5991,
	84,
	2,
	70,
	2,
	1,
	3,
	0,
	3,
	1,
	3,
	3,
	2,
	11,
	2,
	0,
	2,
	6,
	2,
	64,
	2,
	3,
	3,
	7,
	2,
	6,
	2,
	27,
	2,
	3,
	2,
	4,
	2,
	0,
	4,
	6,
	2,
	339,
	3,
	24,
	2,
	24,
	2,
	30,
	2,
	24,
	2,
	30,
	2,
	24,
	2,
	30,
	2,
	24,
	2,
	30,
	2,
	24,
	2,
	7,
	1845,
	30,
	7,
	5,
	262,
	61,
	147,
	44,
	11,
	6,
	17,
	0,
	322,
	29,
	19,
	43,
	485,
	27,
	229,
	29,
	3,
	0,
	208,
	30,
	2,
	2,
	2,
	1,
	2,
	6,
	3,
	4,
	10,
	1,
	225,
	6,
	2,
	3,
	2,
	1,
	2,
	14,
	2,
	196,
	60,
	67,
	8,
	0,
	1205,
	3,
	2,
	26,
	2,
	1,
	2,
	0,
	3,
	0,
	2,
	9,
	2,
	3,
	2,
	0,
	2,
	0,
	7,
	0,
	5,
	0,
	2,
	0,
	2,
	0,
	2,
	2,
	2,
	1,
	2,
	0,
	3,
	0,
	2,
	0,
	2,
	0,
	2,
	0,
	2,
	0,
	2,
	1,
	2,
	0,
	3,
	3,
	2,
	6,
	2,
	3,
	2,
	3,
	2,
	0,
	2,
	9,
	2,
	16,
	6,
	2,
	2,
	4,
	2,
	16,
	4421,
	42719,
	33,
	4381,
	3,
	5773,
	3,
	7472,
	16,
	621,
	2467,
	541,
	1507,
	4938,
	6,
	8489
];
var nonASCIIidentifierChars = "‌‍·̀-ͯ·҃-֑҇-ׇֽֿׁׂׅׄؐ-ًؚ-٩ٰۖ-ۜ۟-۪ۤۧۨ-ۭ۰-۹ܑܰ-݊ަ-ް߀-߉߫-߽߳ࠖ-࠙ࠛ-ࠣࠥ-ࠧࠩ-࡙࠭-࡛ࢗ-࢟࣊-ࣣ࣡-ःऺ-़ा-ॏ॑-ॗॢॣ०-९ঁ-ঃ়া-ৄেৈো-্ৗৢৣ০-৯৾ਁ-ਃ਼ਾ-ੂੇੈੋ-੍ੑ੦-ੱੵઁ-ઃ઼ા-ૅે-ૉો-્ૢૣ૦-૯ૺ-૿ଁ-ଃ଼ା-ୄେୈୋ-୍୕-ୗୢୣ୦-୯ஂா-ூெ-ைொ-்ௗ௦-௯ఀ-ఄ఼ా-ౄె-ైొ-్ౕౖౢౣ౦-౯ಁ-ಃ಼ಾ-ೄೆ-ೈೊ-್ೕೖೢೣ೦-೯ೳഀ-ഃ഻഼ാ-ൄെ-ൈൊ-്ൗൢൣ൦-൯ඁ-ඃ්ා-ුූෘ-ෟ෦-෯ෲෳัิ-ฺ็-๎๐-๙ັິ-ຼ່-໎໐-໙༘༙༠-༩༹༵༷༾༿ཱ-྄྆྇ྍ-ྗྙ-ྼ࿆ါ-ှ၀-၉ၖ-ၙၞ-ၠၢ-ၤၧ-ၭၱ-ၴႂ-ႍႏ-ႝ፝-፟፩-፱ᜒ-᜕ᜲ-᜴ᝒᝓᝲᝳ឴-៓៝០-៩᠋-᠍᠏-᠙ᢩᤠ-ᤫᤰ-᤻᥆-᥏᧐-᧚ᨗ-ᨛᩕ-ᩞ᩠-᩿᩼-᪉᪐-᪙᪰-᪽ᪿ-᫝᫠-᫫ᬀ-ᬄ᬴-᭄᭐-᭙᭫-᭳ᮀ-ᮂᮡ-ᮭ᮰-᮹᯦-᯳ᰤ-᰷᱀-᱉᱐-᱙᳐-᳔᳒-᳨᳭᳴᳷-᳹᷀-᷿‌‍‿⁀⁔⃐-⃥⃜⃡-⃰⳯-⵿⳱ⷠ-〪ⷿ-゙゚〯・꘠-꘩꙯ꙴ-꙽ꚞꚟ꛰꛱ꠂ꠆ꠋꠣ-ꠧ꠬ꢀꢁꢴ-ꣅ꣐-꣙꣠-꣱ꣿ-꤉ꤦ-꤭ꥇ-꥓ꦀ-ꦃ꦳-꧀꧐-꧙ꧥ꧰-꧹ꨩ-ꨶꩃꩌꩍ꩐-꩙ꩻ-ꩽꪰꪲ-ꪴꪷꪸꪾ꪿꫁ꫫ-ꫯꫵ꫶ꯣ-ꯪ꯬꯭꯰-꯹ﬞ︀-️︠-︯︳︴﹍-﹏０-９＿･";
var nonASCIIidentifierStartChars = "ªµºÀ-ÖØ-öø-ˁˆ-ˑˠ-ˤˬˮͰ-ʹͶͷͺ-ͽͿΆΈ-ΊΌΎ-ΡΣ-ϵϷ-ҁҊ-ԯԱ-Ֆՙՠ-ֈא-תׯ-ײؠ-يٮٯٱ-ۓەۥۦۮۯۺ-ۼۿܐܒ-ܯݍ-ޥޱߊ-ߪߴߵߺࠀ-ࠕࠚࠤࠨࡀ-ࡘࡠ-ࡪࡰ-ࢇࢉ-࢏ࢠ-ࣉऄ-हऽॐक़-ॡॱ-ঀঅ-ঌএঐও-নপ-রলশ-হঽৎড়ঢ়য়-ৡৰৱৼਅ-ਊਏਐਓ-ਨਪ-ਰਲਲ਼ਵਸ਼ਸਹਖ਼-ੜਫ਼ੲ-ੴઅ-ઍએ-ઑઓ-નપ-રલળવ-હઽૐૠૡૹଅ-ଌଏଐଓ-ନପ-ରଲଳଵ-ହଽଡ଼ଢ଼ୟ-ୡୱஃஅ-ஊஎ-ஐஒ-கஙசஜஞடணதந-பம-ஹௐఅ-ఌఎ-ఐఒ-నప-హఽౘ-ౚ౜ౝౠౡಀಅ-ಌಎ-ಐಒ-ನಪ-ಳವ-ಹಽ೜-ೞೠೡೱೲഄ-ഌഎ-ഐഒ-ഺഽൎൔ-ൖൟ-ൡൺ-ൿඅ-ඖක-නඳ-රලව-ෆก-ะาำเ-ๆກຂຄຆ-ຊຌ-ຣລວ-ະາຳຽເ-ໄໆໜ-ໟༀཀ-ཇཉ-ཬྈ-ྌက-ဪဿၐ-ၕၚ-ၝၡၥၦၮ-ၰၵ-ႁႎႠ-ჅჇჍა-ჺჼ-ቈቊ-ቍቐ-ቖቘቚ-ቝበ-ኈኊ-ኍነ-ኰኲ-ኵኸ-ኾዀዂ-ዅወ-ዖዘ-ጐጒ-ጕጘ-ፚᎀ-ᎏᎠ-Ᏽᏸ-ᏽᐁ-ᙬᙯ-ᙿᚁ-ᚚᚠ-ᛪᛮ-ᛸᜀ-ᜑᜟ-ᜱᝀ-ᝑᝠ-ᝬᝮ-ᝰក-ឳៗៜᠠ-ᡸᢀ-ᢨᢪᢰ-ᣵᤀ-ᤞᥐ-ᥭᥰ-ᥴᦀ-ᦫᦰ-ᧉᨀ-ᨖᨠ-ᩔᪧᬅ-ᬳᭅ-ᭌᮃ-ᮠᮮᮯᮺ-ᯥᰀ-ᰣᱍ-ᱏᱚ-ᱽᲀ-ᲊᲐ-ᲺᲽ-Ჿᳩ-ᳬᳮ-ᳳᳵᳶᳺᴀ-ᶿḀ-ἕἘ-Ἕἠ-ὅὈ-Ὅὐ-ὗὙὛὝὟ-ώᾀ-ᾴᾶ-ᾼιῂ-ῄῆ-ῌῐ-ΐῖ-Ίῠ-Ῥῲ-ῴῶ-ῼⁱⁿₐ-ₜℂℇℊ-ℓℕ℘-ℝℤΩℨK-ℹℼ-ℿⅅ-ⅉⅎⅠ-ↈⰀ-ⳤⳫ-ⳮⳲⳳⴀ-ⴥⴧⴭⴰ-ⵧⵯⶀ-ⶖⶠ-ⶦⶨ-ⶮⶰ-ⶶⶸ-ⶾⷀ-ⷆⷈ-ⷎⷐ-ⷖⷘ-ⷞ々-〇〡-〩〱-〵〸-〼ぁ-ゖ゛-ゟァ-ヺー-ヿㄅ-ㄯㄱ-ㆎㆠ-ㆿㇰ-ㇿ㐀-䶿一-ꒌꓐ-ꓽꔀ-ꘌꘐ-ꘟꘪꘫꙀ-ꙮꙿ-ꚝꚠ-ꛯꜗ-ꜟꜢ-ꞈꞋ-Ƛ꟱-ꠁꠃ-ꠅꠇ-ꠊꠌ-ꠢꡀ-ꡳꢂ-ꢳꣲ-ꣷꣻꣽꣾꤊ-ꤥꤰ-ꥆꥠ-ꥼꦄ-ꦲꧏꧠ-ꧤꧦ-ꧯꧺ-ꧾꨀ-ꨨꩀ-ꩂꩄ-ꩋꩠ-ꩶꩺꩾ-ꪯꪱꪵꪶꪹ-ꪽꫀꫂꫛ-ꫝꫠ-ꫪꫲ-ꫴꬁ-ꬆꬉ-ꬎꬑ-ꬖꬠ-ꬦꬨ-ꬮꬰ-ꭚꭜ-ꭩꭰ-ꯢ가-힣ힰ-ퟆퟋ-ퟻ豈-舘並-龎ﬀ-ﬆﬓ-ﬗיִײַ-ﬨשׁ-זּטּ-לּמּנּסּףּפּצּ-ﮱﯓ-ﴽﵐ-ﶏﶒ-ﷇﷰ-ﷻﹰ-ﹴﹶ-ﻼＡ-Ｚａ-ｚｦ-ﾾￂ-ￇￊ-ￏￒ-ￗￚ-ￜ";
var reservedWords = {
	3: "abstract boolean byte char class double enum export extends final float goto implements import int interface long native package private protected public short static super synchronized throws transient volatile",
	5: "class enum extends super const export import",
	6: "enum",
	strict: "implements interface let package private protected public static yield",
	strictBind: "eval arguments"
};
var ecma5AndLessKeywords = "break case catch continue debugger default do else finally for function if return switch throw try var while with null true false instanceof typeof void delete new in this";
var keywords$1 = {
	5: ecma5AndLessKeywords,
	"5module": ecma5AndLessKeywords + " export import",
	6: ecma5AndLessKeywords + " const class extends export import super"
};
var keywordRelationalOperator = /^in(stanceof)?$/;
var nonASCIIidentifierStart = new RegExp("[" + nonASCIIidentifierStartChars + "]");
var nonASCIIidentifier = new RegExp("[" + nonASCIIidentifierStartChars + nonASCIIidentifierChars + "]");
function isInAstralSet(code, set) {
	var pos = 65536;
	for (var i = 0; i < set.length; i += 2) {
		pos += set[i];
		if (pos > code) return false;
		pos += set[i + 1];
		if (pos >= code) return true;
	}
	return false;
}
function isIdentifierStart(code, astral) {
	if (code < 65) return code === 36;
	if (code < 91) return true;
	if (code < 97) return code === 95;
	if (code < 123) return true;
	if (code <= 65535) return code >= 170 && nonASCIIidentifierStart.test(String.fromCharCode(code));
	if (astral === false) return false;
	return isInAstralSet(code, astralIdentifierStartCodes);
}
function isIdentifierChar(code, astral) {
	if (code < 48) return code === 36;
	if (code < 58) return true;
	if (code < 65) return false;
	if (code < 91) return true;
	if (code < 97) return code === 95;
	if (code < 123) return true;
	if (code <= 65535) return code >= 170 && nonASCIIidentifier.test(String.fromCharCode(code));
	if (astral === false) return false;
	return isInAstralSet(code, astralIdentifierStartCodes) || isInAstralSet(code, astralIdentifierCodes);
}
var TokenType = function TokenType(label, conf) {
	if (conf === void 0) conf = {};
	this.label = label;
	this.keyword = conf.keyword;
	this.beforeExpr = !!conf.beforeExpr;
	this.startsExpr = !!conf.startsExpr;
	this.isLoop = !!conf.isLoop;
	this.isAssign = !!conf.isAssign;
	this.prefix = !!conf.prefix;
	this.postfix = !!conf.postfix;
	this.binop = conf.binop || null;
	this.updateContext = null;
};
function binop(name, prec) {
	return new TokenType(name, {
		beforeExpr: true,
		binop: prec
	});
}
var beforeExpr = { beforeExpr: true };
var startsExpr = { startsExpr: true };
var keywords = {};
function kw(name, options) {
	if (options === void 0) options = {};
	options.keyword = name;
	return keywords[name] = new TokenType(name, options);
}
var types$1 = {
	num: new TokenType("num", startsExpr),
	regexp: new TokenType("regexp", startsExpr),
	string: new TokenType("string", startsExpr),
	name: new TokenType("name", startsExpr),
	privateId: new TokenType("privateId", startsExpr),
	eof: new TokenType("eof"),
	bracketL: new TokenType("[", {
		beforeExpr: true,
		startsExpr: true
	}),
	bracketR: new TokenType("]"),
	braceL: new TokenType("{", {
		beforeExpr: true,
		startsExpr: true
	}),
	braceR: new TokenType("}"),
	parenL: new TokenType("(", {
		beforeExpr: true,
		startsExpr: true
	}),
	parenR: new TokenType(")"),
	comma: new TokenType(",", beforeExpr),
	semi: new TokenType(";", beforeExpr),
	colon: new TokenType(":", beforeExpr),
	dot: new TokenType("."),
	question: new TokenType("?", beforeExpr),
	questionDot: new TokenType("?."),
	arrow: new TokenType("=>", beforeExpr),
	template: new TokenType("template"),
	invalidTemplate: new TokenType("invalidTemplate"),
	ellipsis: new TokenType("...", beforeExpr),
	backQuote: new TokenType("`", startsExpr),
	dollarBraceL: new TokenType("${", {
		beforeExpr: true,
		startsExpr: true
	}),
	eq: new TokenType("=", {
		beforeExpr: true,
		isAssign: true
	}),
	assign: new TokenType("_=", {
		beforeExpr: true,
		isAssign: true
	}),
	incDec: new TokenType("++/--", {
		prefix: true,
		postfix: true,
		startsExpr: true
	}),
	prefix: new TokenType("!/~", {
		beforeExpr: true,
		prefix: true,
		startsExpr: true
	}),
	logicalOR: binop("||", 1),
	logicalAND: binop("&&", 2),
	bitwiseOR: binop("|", 3),
	bitwiseXOR: binop("^", 4),
	bitwiseAND: binop("&", 5),
	equality: binop("==/!=/===/!==", 6),
	relational: binop("</>/<=/>=", 7),
	bitShift: binop("<</>>/>>>", 8),
	plusMin: new TokenType("+/-", {
		beforeExpr: true,
		binop: 9,
		prefix: true,
		startsExpr: true
	}),
	modulo: binop("%", 10),
	star: binop("*", 10),
	slash: binop("/", 10),
	starstar: new TokenType("**", { beforeExpr: true }),
	coalesce: binop("??", 1),
	_break: kw("break"),
	_case: kw("case", beforeExpr),
	_catch: kw("catch"),
	_continue: kw("continue"),
	_debugger: kw("debugger"),
	_default: kw("default", beforeExpr),
	_do: kw("do", {
		isLoop: true,
		beforeExpr: true
	}),
	_else: kw("else", beforeExpr),
	_finally: kw("finally"),
	_for: kw("for", { isLoop: true }),
	_function: kw("function", startsExpr),
	_if: kw("if"),
	_return: kw("return", beforeExpr),
	_switch: kw("switch"),
	_throw: kw("throw", beforeExpr),
	_try: kw("try"),
	_var: kw("var"),
	_const: kw("const"),
	_while: kw("while", { isLoop: true }),
	_with: kw("with"),
	_new: kw("new", {
		beforeExpr: true,
		startsExpr: true
	}),
	_this: kw("this", startsExpr),
	_super: kw("super", startsExpr),
	_class: kw("class", startsExpr),
	_extends: kw("extends", beforeExpr),
	_export: kw("export"),
	_import: kw("import", startsExpr),
	_null: kw("null", startsExpr),
	_true: kw("true", startsExpr),
	_false: kw("false", startsExpr),
	_in: kw("in", {
		beforeExpr: true,
		binop: 7
	}),
	_instanceof: kw("instanceof", {
		beforeExpr: true,
		binop: 7
	}),
	_typeof: kw("typeof", {
		beforeExpr: true,
		prefix: true,
		startsExpr: true
	}),
	_void: kw("void", {
		beforeExpr: true,
		prefix: true,
		startsExpr: true
	}),
	_delete: kw("delete", {
		beforeExpr: true,
		prefix: true,
		startsExpr: true
	})
};
var lineBreak = /\r\n?|\n|\u2028|\u2029/;
var lineBreakG = new RegExp(lineBreak.source, "g");
function isNewLine(code) {
	return code === 10 || code === 13 || code === 8232 || code === 8233;
}
function nextLineBreak(code, from, end) {
	if (end === void 0) end = code.length;
	for (var i = from; i < end; i++) {
		var next = code.charCodeAt(i);
		if (isNewLine(next)) return i < end - 1 && next === 13 && code.charCodeAt(i + 1) === 10 ? i + 2 : i + 1;
	}
	return -1;
}
var nonASCIIwhitespace = /[\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]/;
var skipWhiteSpace = /(?:\s|\/\/.*|\/\*[^]*?\*\/)*/g;
var ref = Object.prototype;
var hasOwnProperty = ref.hasOwnProperty;
var toString = ref.toString;
var hasOwn = Object.hasOwn || (function(obj, propName) {
	return hasOwnProperty.call(obj, propName);
});
var isArray = Array.isArray || (function(obj) {
	return toString.call(obj) === "[object Array]";
});
var regexpCache = Object.create(null);
function wordsRegexp(words) {
	return regexpCache[words] || (regexpCache[words] = new RegExp("^(?:" + words.replace(/ /g, "|") + ")$"));
}
function codePointToString(code) {
	if (code <= 65535) return String.fromCharCode(code);
	code -= 65536;
	return String.fromCharCode((code >> 10) + 55296, (code & 1023) + 56320);
}
var loneSurrogate = /(?:[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?:[^\uD800-\uDBFF]|^)[\uDC00-\uDFFF])/;
var Position = function Position(line, col) {
	this.line = line;
	this.column = col;
};
Position.prototype.offset = function offset(n) {
	return new Position(this.line, this.column + n);
};
var SourceLocation = function SourceLocation(p, start, end) {
	this.start = start;
	this.end = end;
	if (p.sourceFile !== null) this.source = p.sourceFile;
};
function getLineInfo(input, offset) {
	for (var line = 1, cur = 0;;) {
		var nextBreak = nextLineBreak(input, cur, offset);
		if (nextBreak < 0) return new Position(line, offset - cur);
		++line;
		cur = nextBreak;
	}
}
var defaultOptions = {
	ecmaVersion: null,
	sourceType: "script",
	strict: false,
	onInsertedSemicolon: null,
	onTrailingComma: null,
	allowReserved: null,
	allowReturnOutsideFunction: false,
	allowImportExportEverywhere: false,
	allowAwaitOutsideFunction: null,
	allowSuperOutsideMethod: null,
	allowHashBang: false,
	checkPrivateFields: true,
	locations: false,
	startLocation: null,
	onToken: null,
	onComment: null,
	ranges: false,
	program: null,
	sourceFile: null,
	directSourceFile: null,
	preserveParens: false
};
var warnedAboutEcmaVersion = false;
function getOptions(opts) {
	var options = {};
	for (var opt in defaultOptions) options[opt] = opts && hasOwn(opts, opt) ? opts[opt] : defaultOptions[opt];
	if (options.ecmaVersion === "latest") options.ecmaVersion = 1e8;
	else if (options.ecmaVersion == null) {
		if (!warnedAboutEcmaVersion && typeof console === "object" && console.warn) {
			warnedAboutEcmaVersion = true;
			console.warn("Since Acorn 8.0.0, options.ecmaVersion is required.\nDefaulting to 2020, but this will stop working in the future.");
		}
		options.ecmaVersion = 11;
	} else if (options.ecmaVersion >= 2015) options.ecmaVersion -= 2009;
	if (options.allowReserved == null) options.allowReserved = options.ecmaVersion < 5;
	if (!opts || opts.allowHashBang == null) options.allowHashBang = options.ecmaVersion >= 14;
	if (isArray(options.onToken)) {
		var tokens = options.onToken;
		options.onToken = function(token) {
			return tokens.push(token);
		};
	}
	if (isArray(options.onComment)) options.onComment = pushComment(options, options.onComment);
	if (options.sourceType === "commonjs" && options.allowAwaitOutsideFunction) throw new Error("Cannot use allowAwaitOutsideFunction with sourceType: commonjs");
	return options;
}
function pushComment(options, array) {
	return function(block, text, start, end, startLoc, endLoc) {
		var comment = {
			type: block ? "Block" : "Line",
			value: text,
			start,
			end
		};
		if (options.locations) comment.loc = new SourceLocation(this, startLoc, endLoc);
		if (options.ranges) comment.range = [start, end];
		array.push(comment);
	};
}
var SCOPE_TOP = 1;
var SCOPE_FUNCTION = 2;
var SCOPE_ASYNC = 4;
var SCOPE_GENERATOR = 8;
var SCOPE_ARROW = 16;
var SCOPE_SIMPLE_CATCH = 32;
var SCOPE_SUPER = 64;
var SCOPE_DIRECT_SUPER = 128;
var SCOPE_CLASS_STATIC_BLOCK = 256;
var SCOPE_CLASS_FIELD_INIT = 512;
var SCOPE_SWITCH = 1024;
var SCOPE_VAR = SCOPE_TOP | SCOPE_FUNCTION | SCOPE_CLASS_STATIC_BLOCK;
function functionFlags(async, generator) {
	return SCOPE_FUNCTION | (async ? SCOPE_ASYNC : 0) | (generator ? SCOPE_GENERATOR : 0);
}
var BIND_NONE = 0;
var BIND_VAR = 1;
var BIND_LEXICAL = 2;
var BIND_FUNCTION = 3;
var BIND_SIMPLE_CATCH = 4;
var BIND_OUTSIDE = 5;
var Parser = function Parser(options, input, startPos) {
	this.options = options = getOptions(options);
	this.sourceFile = options.sourceFile;
	this.keywords = wordsRegexp(keywords$1[options.ecmaVersion >= 6 ? 6 : options.sourceType === "module" ? "5module" : 5]);
	var reserved = "";
	if (options.allowReserved !== true) {
		reserved = reservedWords[options.ecmaVersion >= 6 ? 6 : options.ecmaVersion === 5 ? 5 : 3];
		if (options.sourceType === "module") reserved += " await";
	}
	this.reservedWords = wordsRegexp(reserved);
	var reservedStrict = (reserved ? reserved + " " : "") + reservedWords.strict;
	this.reservedWordsStrict = wordsRegexp(reservedStrict);
	this.reservedWordsStrictBind = wordsRegexp(reservedStrict + " " + reservedWords.strictBind);
	this.input = String(input);
	this.containsEsc = false;
	this.pos = startPos || 0;
	this.curLine = 1;
	if (options.startLocation) {
		this.lineStart = this.pos - options.startLocation.column;
		this.curLine = options.startLocation.line;
	} else if (startPos) {
		this.lineStart = this.input.lastIndexOf("\n", startPos - 1) + 1;
		if (this.options.locations) this.curLine = this.input.slice(0, this.lineStart).split(lineBreak).length;
	} else this.lineStart = 0;
	this.type = types$1.eof;
	this.value = null;
	this.start = this.end = this.pos;
	this.startLoc = this.endLoc = this.curPosition();
	this.lastTokEndLoc = this.lastTokStartLoc = null;
	this.lastTokStart = this.lastTokEnd = this.pos;
	this.context = this.initialContext();
	this.exprAllowed = true;
	this.inModule = options.sourceType === "module";
	this.strict = this.inModule || options.strict === true || this.strictDirective(this.pos);
	this.potentialArrowAt = -1;
	this.potentialArrowInForAwait = false;
	this.yieldPos = this.awaitPos = this.awaitIdentPos = 0;
	this.labels = [];
	this.undefinedExports = Object.create(null);
	if (this.pos === 0 && options.allowHashBang && this.input.slice(0, 2) === "#!") this.skipLineComment(2);
	this.scopeStack = [];
	this.enterScope(this.options.sourceType === "commonjs" ? SCOPE_FUNCTION : SCOPE_TOP);
	this.regexpState = null;
	this.privateNameStack = [];
};
var prototypeAccessors = {
	inFunction: { configurable: true },
	inGenerator: { configurable: true },
	inAsync: { configurable: true },
	canAwait: { configurable: true },
	allowReturn: { configurable: true },
	allowSuper: { configurable: true },
	allowDirectSuper: { configurable: true },
	treatFunctionsAsVar: { configurable: true },
	allowNewDotTarget: { configurable: true },
	allowUsing: { configurable: true },
	inClassStaticBlock: { configurable: true }
};
Parser.prototype.parse = function parse() {
	var this$1$1 = this;
	var node = this.options.program || this.startNode();
	this.nextToken();
	return this.catchStackOverflow(function() {
		return this$1$1.parseTopLevel(node);
	});
};
prototypeAccessors.inFunction.get = function() {
	return (this.currentVarScope().flags & SCOPE_FUNCTION) > 0;
};
prototypeAccessors.inGenerator.get = function() {
	return (this.currentVarScope().flags & SCOPE_GENERATOR) > 0;
};
prototypeAccessors.inAsync.get = function() {
	return (this.currentVarScope().flags & SCOPE_ASYNC) > 0;
};
prototypeAccessors.canAwait.get = function() {
	for (var i = this.scopeStack.length - 1; i >= 0; i--) {
		var flags = this.scopeStack[i].flags;
		if (flags & (SCOPE_CLASS_STATIC_BLOCK | SCOPE_CLASS_FIELD_INIT)) return false;
		if (flags & SCOPE_FUNCTION) return (flags & SCOPE_ASYNC) > 0;
	}
	return this.inModule && this.options.ecmaVersion >= 13 || this.options.allowAwaitOutsideFunction;
};
prototypeAccessors.allowReturn.get = function() {
	if (this.inFunction) return true;
	if (this.options.allowReturnOutsideFunction && this.currentVarScope().flags & SCOPE_TOP) return true;
	return false;
};
prototypeAccessors.allowSuper.get = function() {
	return (this.currentThisScope().flags & SCOPE_SUPER) > 0 || this.options.allowSuperOutsideMethod;
};
prototypeAccessors.allowDirectSuper.get = function() {
	return (this.currentThisScope().flags & SCOPE_DIRECT_SUPER) > 0;
};
prototypeAccessors.treatFunctionsAsVar.get = function() {
	return this.treatFunctionsAsVarInScope(this.currentScope());
};
prototypeAccessors.allowNewDotTarget.get = function() {
	for (var i = this.scopeStack.length - 1; i >= 0; i--) {
		var flags = this.scopeStack[i].flags;
		if (flags & (SCOPE_CLASS_STATIC_BLOCK | SCOPE_CLASS_FIELD_INIT) || flags & SCOPE_FUNCTION && !(flags & SCOPE_ARROW)) return true;
	}
	return false;
};
prototypeAccessors.allowUsing.get = function() {
	var flags = this.currentScope().flags;
	if (flags & SCOPE_SWITCH) return false;
	if (!this.inModule && flags & SCOPE_TOP) return false;
	return true;
};
prototypeAccessors.inClassStaticBlock.get = function() {
	return (this.currentVarScope().flags & SCOPE_CLASS_STATIC_BLOCK) > 0;
};
Parser.extend = function extend() {
	var plugins = [], len = arguments.length;
	while (len--) plugins[len] = arguments[len];
	var cls = this;
	for (var i = 0; i < plugins.length; i++) cls = plugins[i](cls);
	return cls;
};
Parser.parse = function parse(input, options) {
	return new this(options, input).parse();
};
Parser.parseExpressionAt = function parseExpressionAt(input, pos, options) {
	var parser = new this(options, input, pos);
	parser.nextToken();
	return parser.parseExpression();
};
Parser.tokenizer = function tokenizer(input, options) {
	return new this(options, input);
};
Object.defineProperties(Parser.prototype, prototypeAccessors);
var pp$9 = Parser.prototype;
var literal = /^(?:'((?:\\[^]|[^'\\])*?)'|"((?:\\[^]|[^"\\])*?)")/;
pp$9.strictDirective = function(start) {
	if (this.options.ecmaVersion < 5) return false;
	for (;;) {
		skipWhiteSpace.lastIndex = start;
		start += skipWhiteSpace.exec(this.input)[0].length;
		var match = literal.exec(this.input.slice(start));
		if (!match) return false;
		if ((match[1] || match[2]) === "use strict") {
			skipWhiteSpace.lastIndex = start + match[0].length;
			var spaceAfter = skipWhiteSpace.exec(this.input), end = spaceAfter.index + spaceAfter[0].length;
			var next = this.input.charAt(end);
			return next === ";" || next === "}" || lineBreak.test(spaceAfter[0]) && !(/[(`.[+\-/*%<>=,?^&]/.test(next) || next === "!" && this.input.charAt(end + 1) === "=");
		}
		start += match[0].length;
		skipWhiteSpace.lastIndex = start;
		start += skipWhiteSpace.exec(this.input)[0].length;
		if (this.input[start] === ";") start++;
	}
};
pp$9.eat = function(type) {
	if (this.type === type) {
		this.next();
		return true;
	} else return false;
};
pp$9.isContextual = function(name) {
	return this.type === types$1.name && this.value === name && !this.containsEsc;
};
pp$9.eatContextual = function(name) {
	if (!this.isContextual(name)) return false;
	this.next();
	return true;
};
pp$9.catchStackOverflow = function(f) {
	try {
		return f();
	} catch (e) {
		if (e instanceof Error && (/\bstack\b.*\b(exceeded|overflow)\b/i.test(e.message) || /\btoo much recursion\b/i.test(e.message))) this.raise(this.start, "Not enough stack space to parse input");
		else throw e;
	}
};
pp$9.expectContextual = function(name) {
	if (!this.eatContextual(name)) this.unexpected();
};
pp$9.canInsertSemicolon = function() {
	return this.type === types$1.eof || this.type === types$1.braceR || lineBreak.test(this.input.slice(this.lastTokEnd, this.start));
};
pp$9.insertSemicolon = function() {
	if (this.canInsertSemicolon()) {
		if (this.options.onInsertedSemicolon) this.options.onInsertedSemicolon(this.lastTokEnd, this.lastTokEndLoc);
		return true;
	}
};
pp$9.semicolon = function() {
	if (!this.eat(types$1.semi) && !this.insertSemicolon()) this.unexpected();
};
pp$9.afterTrailingComma = function(tokType, notNext) {
	if (this.type === tokType) {
		if (this.options.onTrailingComma) this.options.onTrailingComma(this.lastTokStart, this.lastTokStartLoc);
		if (!notNext) this.next();
		return true;
	}
};
pp$9.expect = function(type) {
	this.eat(type) || this.unexpected();
};
pp$9.unexpected = function(pos) {
	this.raise(pos != null ? pos : this.start, "Unexpected token");
};
var DestructuringErrors = function DestructuringErrors() {
	this.shorthandAssign = this.trailingComma = this.parenthesizedAssign = this.parenthesizedBind = this.doubleProto = -1;
};
pp$9.checkPatternErrors = function(refDestructuringErrors, isAssign) {
	if (!refDestructuringErrors) return;
	if (refDestructuringErrors.trailingComma > -1) this.raiseRecoverable(refDestructuringErrors.trailingComma, "Comma is not permitted after the rest element");
	var parens = isAssign ? refDestructuringErrors.parenthesizedAssign : refDestructuringErrors.parenthesizedBind;
	if (parens > -1) this.raiseRecoverable(parens, isAssign ? "Assigning to rvalue" : "Parenthesized pattern");
};
pp$9.checkExpressionErrors = function(refDestructuringErrors, andThrow) {
	if (!refDestructuringErrors) return false;
	var shorthandAssign = refDestructuringErrors.shorthandAssign;
	var doubleProto = refDestructuringErrors.doubleProto;
	if (!andThrow) return shorthandAssign >= 0 || doubleProto >= 0;
	if (shorthandAssign >= 0) this.raise(shorthandAssign, "Shorthand property assignments are valid only in destructuring patterns");
	if (doubleProto >= 0) this.raiseRecoverable(doubleProto, "Redefinition of __proto__ property");
};
pp$9.checkYieldAwaitInDefaultParams = function() {
	if (this.yieldPos && (!this.awaitPos || this.yieldPos < this.awaitPos)) this.raise(this.yieldPos, "Yield expression cannot be a default value");
	if (this.awaitPos) this.raise(this.awaitPos, "Await expression cannot be a default value");
};
pp$9.isSimpleAssignTarget = function(expr) {
	if (expr.type === "ParenthesizedExpression") return this.isSimpleAssignTarget(expr.expression);
	return expr.type === "Identifier" || expr.type === "MemberExpression";
};
var pp$8 = Parser.prototype;
pp$8.parseTopLevel = function(node) {
	var exports$1 = Object.create(null);
	if (!node.body) node.body = [];
	while (this.type !== types$1.eof) {
		var stmt = this.parseStatement(null, true, exports$1);
		node.body.push(stmt);
	}
	if (this.inModule) for (var i = 0, list = Object.keys(this.undefinedExports); i < list.length; i += 1) {
		var name = list[i];
		this.raiseRecoverable(this.undefinedExports[name].start, "Export '" + name + "' is not defined");
	}
	this.adaptDirectivePrologue(node.body);
	this.next();
	node.sourceType = this.options.sourceType === "commonjs" ? "script" : this.options.sourceType;
	return this.finishNode(node, "Program");
};
var loopLabel = { kind: "loop" };
var switchLabel = { kind: "switch" };
pp$8.isLet = function(context) {
	if (this.options.ecmaVersion < 6 || !this.isContextual("let")) return false;
	skipWhiteSpace.lastIndex = this.pos;
	var skip = skipWhiteSpace.exec(this.input);
	var next = this.pos + skip[0].length, nextCh = this.fullCharCodeAt(next);
	if (nextCh === 91 || nextCh === 92) return true;
	if (context) return false;
	if (nextCh === 123) return true;
	if (isIdentifierStart(nextCh)) {
		var start = next;
		do
			next += nextCh <= 65535 ? 1 : 2;
		while (isIdentifierChar(nextCh = this.fullCharCodeAt(next)));
		if (nextCh === 92) return true;
		var ident = this.input.slice(start, next);
		if (!keywordRelationalOperator.test(ident)) return true;
	}
	return false;
};
pp$8.isAsyncFunction = function() {
	if (this.options.ecmaVersion < 8 || !this.isContextual("async")) return false;
	skipWhiteSpace.lastIndex = this.pos;
	var skip = skipWhiteSpace.exec(this.input);
	var next = this.pos + skip[0].length, after;
	return !lineBreak.test(this.input.slice(this.pos, next)) && this.input.slice(next, next + 8) === "function" && (next + 8 === this.input.length || !(isIdentifierChar(after = this.fullCharCodeAt(next + 8)) || after === 92));
};
pp$8.isUsingKeyword = function(isAwaitUsing, isFor) {
	if (this.options.ecmaVersion < 17 || !this.isContextual(isAwaitUsing ? "await" : "using")) return false;
	skipWhiteSpace.lastIndex = this.pos;
	var skip = skipWhiteSpace.exec(this.input);
	var next = this.pos + skip[0].length;
	if (lineBreak.test(this.input.slice(this.pos, next))) return false;
	if (isAwaitUsing) {
		var usingEndPos = next + 5, after;
		if (this.input.slice(next, usingEndPos) !== "using" || usingEndPos === this.input.length || isIdentifierChar(after = this.fullCharCodeAt(usingEndPos)) || after === 92) return false;
		skipWhiteSpace.lastIndex = usingEndPos;
		var skipAfterUsing = skipWhiteSpace.exec(this.input);
		next = usingEndPos + skipAfterUsing[0].length;
		if (skipAfterUsing && lineBreak.test(this.input.slice(usingEndPos, next))) return false;
	}
	var ch = this.fullCharCodeAt(next);
	if (!isIdentifierStart(ch) && ch !== 92) return false;
	var idStart = next;
	do
		next += ch <= 65535 ? 1 : 2;
	while (isIdentifierChar(ch = this.fullCharCodeAt(next)));
	if (ch === 92) return true;
	var id = this.input.slice(idStart, next);
	if (keywordRelationalOperator.test(id)) return false;
	if (isFor && !isAwaitUsing && id === "of") {
		skipWhiteSpace.lastIndex = next;
		var skipAfterOf = skipWhiteSpace.exec(this.input);
		next = next + skipAfterOf[0].length;
		if (this.input.charCodeAt(next) !== 61 || (ch = this.input.charCodeAt(next + 1)) === 61 || ch === 62) return false;
	}
	return true;
};
pp$8.isAwaitUsing = function(isFor) {
	return this.isUsingKeyword(true, isFor);
};
pp$8.isUsing = function(isFor) {
	return this.isUsingKeyword(false, isFor);
};
pp$8.parseStatement = function(context, topLevel, exports$1) {
	var starttype = this.type, node = this.startNode(), kind;
	if (this.isLet(context)) {
		starttype = types$1._var;
		kind = "let";
	}
	switch (starttype) {
		case types$1._break:
		case types$1._continue: return this.parseBreakContinueStatement(node, starttype.keyword);
		case types$1._debugger: return this.parseDebuggerStatement(node);
		case types$1._do: return this.parseDoStatement(node);
		case types$1._for: return this.parseForStatement(node);
		case types$1._function:
			if (context && (this.strict || context !== "if" && context !== "label") && this.options.ecmaVersion >= 6) this.unexpected();
			return this.parseFunctionStatement(node, false, !context);
		case types$1._class:
			if (context) this.unexpected();
			return this.parseClass(node, true);
		case types$1._if: return this.parseIfStatement(node);
		case types$1._return: return this.parseReturnStatement(node);
		case types$1._switch: return this.parseSwitchStatement(node);
		case types$1._throw: return this.parseThrowStatement(node);
		case types$1._try: return this.parseTryStatement(node);
		case types$1._const:
		case types$1._var:
			kind = kind || this.value;
			if (context && kind !== "var") this.unexpected();
			return this.parseVarStatement(node, kind);
		case types$1._while: return this.parseWhileStatement(node);
		case types$1._with: return this.parseWithStatement(node);
		case types$1.braceL: return this.parseBlock(true, node);
		case types$1.semi: return this.parseEmptyStatement(node);
		case types$1._export:
		case types$1._import:
			if (this.options.ecmaVersion > 10 && starttype === types$1._import) {
				skipWhiteSpace.lastIndex = this.pos;
				var skip = skipWhiteSpace.exec(this.input);
				var next = this.pos + skip[0].length, nextCh = this.input.charCodeAt(next);
				if (nextCh === 40 || nextCh === 46) return this.parseExpressionStatement(node, this.parseExpression());
			}
			if (!this.options.allowImportExportEverywhere) {
				if (!topLevel) this.raise(this.start, "'import' and 'export' may only appear at the top level");
				if (!this.inModule) this.raise(this.start, "'import' and 'export' may appear only with 'sourceType: module'");
			}
			return starttype === types$1._import ? this.parseImport(node) : this.parseExport(node, exports$1);
		default:
			if (this.isAsyncFunction()) {
				if (context) this.unexpected();
				this.next();
				return this.parseFunctionStatement(node, true, !context);
			}
			var usingKind = this.isAwaitUsing(false) ? "await using" : this.isUsing(false) ? "using" : null;
			if (usingKind) {
				if (!this.allowUsing) this.raise(this.start, "Using declaration cannot appear in the top level when source type is `script` or in the bare case statement");
				if (context) this.raise(this.start, "Using declaration is not allowed in single-statement positions");
				if (usingKind === "await using") {
					if (!this.canAwait) this.raise(this.start, "Await using cannot appear outside of async function");
					this.next();
				}
				this.next();
				this.parseVar(node, false, usingKind);
				this.semicolon();
				return this.finishNode(node, "VariableDeclaration");
			}
			var maybeName = this.value, expr = this.parseExpression();
			if (starttype === types$1.name && expr.type === "Identifier" && this.eat(types$1.colon)) return this.parseLabeledStatement(node, maybeName, expr, context);
			else return this.parseExpressionStatement(node, expr);
	}
};
pp$8.parseBreakContinueStatement = function(node, keyword) {
	var isBreak = keyword === "break";
	this.next();
	if (this.eat(types$1.semi) || this.insertSemicolon()) node.label = null;
	else if (this.type !== types$1.name) this.unexpected();
	else {
		node.label = this.parseIdent();
		this.semicolon();
	}
	var i = 0;
	for (; i < this.labels.length; ++i) {
		var lab = this.labels[i];
		if (node.label == null || lab.name === node.label.name) {
			if (lab.kind != null && (isBreak || lab.kind === "loop")) break;
			if (node.label && isBreak) break;
		}
	}
	if (i === this.labels.length) this.raise(node.start, "Unsyntactic " + keyword);
	return this.finishNode(node, isBreak ? "BreakStatement" : "ContinueStatement");
};
pp$8.parseDebuggerStatement = function(node) {
	this.next();
	this.semicolon();
	return this.finishNode(node, "DebuggerStatement");
};
pp$8.parseDoStatement = function(node) {
	this.next();
	this.labels.push(loopLabel);
	node.body = this.parseStatement("do");
	this.labels.pop();
	this.expect(types$1._while);
	node.test = this.parseParenExpression();
	if (this.options.ecmaVersion >= 6) this.eat(types$1.semi);
	else this.semicolon();
	return this.finishNode(node, "DoWhileStatement");
};
pp$8.parseForStatement = function(node) {
	this.next();
	var awaitAt = this.options.ecmaVersion >= 9 && this.canAwait && this.eatContextual("await") ? this.lastTokStart : -1;
	this.labels.push(loopLabel);
	this.enterScope(0);
	this.expect(types$1.parenL);
	if (this.type === types$1.semi) {
		if (awaitAt > -1) this.unexpected(awaitAt);
		return this.parseFor(node, null);
	}
	var isLet = this.isLet();
	if (this.type === types$1._var || this.type === types$1._const || isLet) {
		var init$1 = this.startNode(), kind = isLet ? "let" : this.value;
		this.next();
		this.parseVar(init$1, true, kind);
		this.finishNode(init$1, "VariableDeclaration");
		return this.parseForAfterInit(node, init$1, awaitAt);
	}
	var startsWithLet = this.isContextual("let"), isForOf = false;
	var usingKind = this.isUsing(true) ? "using" : this.isAwaitUsing(true) ? "await using" : null;
	if (usingKind) {
		var init$2 = this.startNode();
		this.next();
		if (usingKind === "await using") {
			if (!this.canAwait) this.raise(this.start, "Await using cannot appear outside of async function");
			this.next();
		}
		this.parseVar(init$2, true, usingKind);
		this.finishNode(init$2, "VariableDeclaration");
		return this.parseForAfterInit(node, init$2, awaitAt);
	}
	var containsEsc = this.containsEsc;
	var refDestructuringErrors = new DestructuringErrors();
	var initPos = this.start;
	var init = awaitAt > -1 ? this.parseExprSubscripts(refDestructuringErrors, "await") : this.parseExpression(true, refDestructuringErrors);
	if (this.type === types$1._in || (isForOf = this.options.ecmaVersion >= 6 && this.isContextual("of"))) {
		if (awaitAt > -1) {
			if (this.type === types$1._in) this.unexpected(awaitAt);
			node.await = true;
		} else if (isForOf && this.options.ecmaVersion >= 8) {
			if (init.start === initPos && !containsEsc && init.type === "Identifier" && init.name === "async") this.unexpected();
			else if (this.options.ecmaVersion >= 9) node.await = false;
		}
		if (startsWithLet && isForOf) this.raise(init.start, "The left-hand side of a for-of loop may not start with 'let'.");
		this.toAssignable(init, false, refDestructuringErrors);
		this.checkLValPattern(init);
		return this.parseForIn(node, init);
	} else this.checkExpressionErrors(refDestructuringErrors, true);
	if (awaitAt > -1) this.unexpected(awaitAt);
	return this.parseFor(node, init);
};
pp$8.parseForAfterInit = function(node, init, awaitAt) {
	if ((this.type === types$1._in || this.options.ecmaVersion >= 6 && this.isContextual("of")) && init.declarations.length === 1) {
		if (this.type === types$1._in) {
			if ((init.kind === "using" || init.kind === "await using") && !init.declarations[0].init) this.raise(this.start, "Using declaration is not allowed in for-in loops");
			if (this.options.ecmaVersion >= 9 && awaitAt > -1) this.unexpected(awaitAt);
		} else if (this.options.ecmaVersion >= 9) node.await = awaitAt > -1;
		return this.parseForIn(node, init);
	}
	if (awaitAt > -1) this.unexpected(awaitAt);
	return this.parseFor(node, init);
};
pp$8.parseFunctionStatement = function(node, isAsync, declarationPosition) {
	this.next();
	return this.parseFunction(node, FUNC_STATEMENT | (declarationPosition ? 0 : FUNC_HANGING_STATEMENT), false, isAsync);
};
pp$8.parseIfStatement = function(node) {
	this.next();
	node.test = this.parseParenExpression();
	node.consequent = this.parseStatement("if");
	node.alternate = this.eat(types$1._else) ? this.parseStatement("if") : null;
	return this.finishNode(node, "IfStatement");
};
pp$8.parseReturnStatement = function(node) {
	if (!this.allowReturn) this.raise(this.start, "'return' outside of function");
	this.next();
	if (this.eat(types$1.semi) || this.insertSemicolon()) node.argument = null;
	else {
		node.argument = this.parseExpression();
		this.semicolon();
	}
	return this.finishNode(node, "ReturnStatement");
};
pp$8.parseSwitchStatement = function(node) {
	this.next();
	node.discriminant = this.parseParenExpression();
	node.cases = [];
	this.expect(types$1.braceL);
	this.labels.push(switchLabel);
	this.enterScope(SCOPE_SWITCH);
	var cur;
	for (var sawDefault = false; this.type !== types$1.braceR;) if (this.type === types$1._case || this.type === types$1._default) {
		var isCase = this.type === types$1._case;
		if (cur) this.finishNode(cur, "SwitchCase");
		node.cases.push(cur = this.startNode());
		cur.consequent = [];
		this.next();
		if (isCase) cur.test = this.parseExpression();
		else {
			if (sawDefault) this.raiseRecoverable(this.lastTokStart, "Multiple default clauses");
			sawDefault = true;
			cur.test = null;
		}
		this.expect(types$1.colon);
	} else {
		if (!cur) this.unexpected();
		cur.consequent.push(this.parseStatement(null));
	}
	this.exitScope();
	if (cur) this.finishNode(cur, "SwitchCase");
	this.next();
	this.labels.pop();
	return this.finishNode(node, "SwitchStatement");
};
pp$8.parseThrowStatement = function(node) {
	this.next();
	if (lineBreak.test(this.input.slice(this.lastTokEnd, this.start))) this.raise(this.lastTokEnd, "Illegal newline after throw");
	node.argument = this.parseExpression();
	this.semicolon();
	return this.finishNode(node, "ThrowStatement");
};
var empty$1 = [];
pp$8.parseCatchClauseParam = function() {
	var param = this.parseBindingAtom();
	var simple = param.type === "Identifier";
	this.enterScope(simple ? SCOPE_SIMPLE_CATCH : 0);
	this.checkLValPattern(param, simple ? BIND_SIMPLE_CATCH : BIND_LEXICAL);
	this.expect(types$1.parenR);
	return param;
};
pp$8.parseTryStatement = function(node) {
	this.next();
	node.block = this.parseBlock();
	node.handler = null;
	if (this.type === types$1._catch) {
		var clause = this.startNode();
		this.next();
		if (this.eat(types$1.parenL)) clause.param = this.parseCatchClauseParam();
		else {
			if (this.options.ecmaVersion < 10) this.unexpected();
			clause.param = null;
			this.enterScope(0);
		}
		clause.body = this.parseBlock(false);
		this.exitScope();
		node.handler = this.finishNode(clause, "CatchClause");
	}
	node.finalizer = this.eat(types$1._finally) ? this.parseBlock() : null;
	if (!node.handler && !node.finalizer) this.raise(node.start, "Missing catch or finally clause");
	return this.finishNode(node, "TryStatement");
};
pp$8.parseVarStatement = function(node, kind, allowMissingInitializer) {
	this.next();
	this.parseVar(node, false, kind, allowMissingInitializer);
	this.semicolon();
	return this.finishNode(node, "VariableDeclaration");
};
pp$8.parseWhileStatement = function(node) {
	this.next();
	node.test = this.parseParenExpression();
	this.labels.push(loopLabel);
	node.body = this.parseStatement("while");
	this.labels.pop();
	return this.finishNode(node, "WhileStatement");
};
pp$8.parseWithStatement = function(node) {
	if (this.strict) this.raise(this.start, "'with' in strict mode");
	this.next();
	node.object = this.parseParenExpression();
	node.body = this.parseStatement("with");
	return this.finishNode(node, "WithStatement");
};
pp$8.parseEmptyStatement = function(node) {
	this.next();
	return this.finishNode(node, "EmptyStatement");
};
pp$8.parseLabeledStatement = function(node, maybeName, expr, context) {
	for (var i$1 = 0, list = this.labels; i$1 < list.length; i$1 += 1) if (list[i$1].name === maybeName) this.raise(expr.start, "Label '" + maybeName + "' is already declared");
	var kind = this.type.isLoop ? "loop" : this.type === types$1._switch ? "switch" : null;
	for (var i = this.labels.length - 1; i >= 0; i--) {
		var label$1 = this.labels[i];
		if (label$1.statementStart === node.start) {
			label$1.statementStart = this.start;
			label$1.kind = kind;
		} else break;
	}
	this.labels.push({
		name: maybeName,
		kind,
		statementStart: this.start
	});
	node.body = this.parseStatement(context ? context.indexOf("label") === -1 ? context + "label" : context : "label");
	this.labels.pop();
	node.label = expr;
	return this.finishNode(node, "LabeledStatement");
};
pp$8.parseExpressionStatement = function(node, expr) {
	node.expression = expr;
	this.semicolon();
	return this.finishNode(node, "ExpressionStatement");
};
pp$8.parseBlock = function(createNewLexicalScope, node, exitStrict) {
	if (createNewLexicalScope === void 0) createNewLexicalScope = true;
	if (node === void 0) node = this.startNode();
	node.body = [];
	this.expect(types$1.braceL);
	if (createNewLexicalScope) this.enterScope(0);
	while (this.type !== types$1.braceR) {
		var stmt = this.parseStatement(null);
		node.body.push(stmt);
	}
	if (exitStrict) this.strict = false;
	this.next();
	if (createNewLexicalScope) this.exitScope();
	return this.finishNode(node, "BlockStatement");
};
pp$8.parseFor = function(node, init) {
	node.init = init;
	this.expect(types$1.semi);
	node.test = this.type === types$1.semi ? null : this.parseExpression();
	this.expect(types$1.semi);
	node.update = this.type === types$1.parenR ? null : this.parseExpression();
	this.expect(types$1.parenR);
	node.body = this.parseStatement("for");
	this.exitScope();
	this.labels.pop();
	return this.finishNode(node, "ForStatement");
};
pp$8.parseForIn = function(node, init) {
	var isForIn = this.type === types$1._in;
	this.next();
	if (init.type === "VariableDeclaration" && init.declarations[0].init != null && (!isForIn || this.options.ecmaVersion < 8 || this.strict || init.kind !== "var" || init.declarations[0].id.type !== "Identifier")) this.raise(init.start, (isForIn ? "for-in" : "for-of") + " loop variable declaration may not have an initializer");
	node.left = init;
	node.right = isForIn ? this.parseExpression() : this.parseMaybeAssign();
	this.expect(types$1.parenR);
	node.body = this.parseStatement("for");
	this.exitScope();
	this.labels.pop();
	return this.finishNode(node, isForIn ? "ForInStatement" : "ForOfStatement");
};
pp$8.parseVar = function(node, isFor, kind, allowMissingInitializer) {
	node.declarations = [];
	node.kind = kind;
	for (;;) {
		var decl = this.startNode();
		this.parseVarId(decl, kind);
		if (this.eat(types$1.eq)) decl.init = this.parseMaybeAssign(isFor);
		else if (!allowMissingInitializer && kind === "const" && !(this.type === types$1._in || this.options.ecmaVersion >= 6 && this.isContextual("of"))) this.unexpected();
		else if (!allowMissingInitializer && (kind === "using" || kind === "await using") && this.options.ecmaVersion >= 17 && this.type !== types$1._in && !this.isContextual("of")) this.raise(this.lastTokEnd, "Missing initializer in " + kind + " declaration");
		else if (!allowMissingInitializer && decl.id.type !== "Identifier" && !(isFor && (this.type === types$1._in || this.isContextual("of")))) this.raise(this.lastTokEnd, "Complex binding patterns require an initialization value");
		else decl.init = null;
		node.declarations.push(this.finishNode(decl, "VariableDeclarator"));
		if (!this.eat(types$1.comma)) break;
	}
	return node;
};
pp$8.parseVarId = function(decl, kind) {
	decl.id = kind === "using" || kind === "await using" ? this.parseIdent() : this.parseBindingAtom();
	this.checkLValPattern(decl.id, kind === "var" ? BIND_VAR : BIND_LEXICAL, false);
};
var FUNC_STATEMENT = 1;
var FUNC_HANGING_STATEMENT = 2;
var FUNC_NULLABLE_ID = 4;
pp$8.parseFunction = function(node, statement, allowExpressionBody, isAsync, forInit) {
	this.initFunction(node);
	if (this.options.ecmaVersion >= 9 || this.options.ecmaVersion >= 6 && !isAsync) {
		if (this.type === types$1.star && statement & FUNC_HANGING_STATEMENT) this.unexpected();
		node.generator = this.eat(types$1.star);
	}
	if (this.options.ecmaVersion >= 8) node.async = !!isAsync;
	if (statement & FUNC_STATEMENT) {
		node.id = statement & FUNC_NULLABLE_ID && this.type !== types$1.name ? null : this.parseIdent();
		if (node.id && !(statement & FUNC_HANGING_STATEMENT)) this.checkLValSimple(node.id, this.strict || node.generator || node.async ? this.treatFunctionsAsVar ? BIND_VAR : BIND_LEXICAL : BIND_FUNCTION);
	}
	var oldYieldPos = this.yieldPos, oldAwaitPos = this.awaitPos, oldAwaitIdentPos = this.awaitIdentPos;
	this.yieldPos = 0;
	this.awaitPos = 0;
	this.awaitIdentPos = 0;
	this.enterScope(functionFlags(node.async, node.generator));
	if (!(statement & FUNC_STATEMENT)) node.id = this.type === types$1.name ? this.parseIdent() : null;
	this.parseFunctionParams(node);
	this.parseFunctionBody(node, allowExpressionBody, false, forInit);
	this.yieldPos = oldYieldPos;
	this.awaitPos = oldAwaitPos;
	this.awaitIdentPos = oldAwaitIdentPos;
	return this.finishNode(node, statement & FUNC_STATEMENT ? "FunctionDeclaration" : "FunctionExpression");
};
pp$8.parseFunctionParams = function(node) {
	this.expect(types$1.parenL);
	node.params = this.parseBindingList(types$1.parenR, false, this.options.ecmaVersion >= 8);
	this.checkYieldAwaitInDefaultParams();
};
pp$8.parseClass = function(node, isStatement) {
	this.next();
	var oldStrict = this.strict;
	this.strict = true;
	this.parseClassId(node, isStatement);
	this.parseClassSuper(node);
	var privateNameMap = this.enterClassBody();
	var classBody = this.startNode();
	var hadConstructor = false;
	classBody.body = [];
	this.expect(types$1.braceL);
	while (this.type !== types$1.braceR) {
		var element = this.parseClassElement(node.superClass !== null);
		if (element) {
			classBody.body.push(element);
			if (element.type === "MethodDefinition" && element.kind === "constructor") {
				if (hadConstructor) this.raiseRecoverable(element.start, "Duplicate constructor in the same class");
				hadConstructor = true;
			} else if (element.key && element.key.type === "PrivateIdentifier" && isPrivateNameConflicted(privateNameMap, element)) this.raiseRecoverable(element.key.start, "Identifier '#" + element.key.name + "' has already been declared");
		}
	}
	this.strict = oldStrict;
	this.next();
	node.body = this.finishNode(classBody, "ClassBody");
	this.exitClassBody();
	return this.finishNode(node, isStatement ? "ClassDeclaration" : "ClassExpression");
};
pp$8.parseClassElement = function(constructorAllowsSuper) {
	if (this.eat(types$1.semi)) return null;
	var ecmaVersion = this.options.ecmaVersion;
	var node = this.startNode();
	var keyName = "";
	var isGenerator = false;
	var isAsync = false;
	var kind = "method";
	var isStatic = false;
	if (this.eatContextual("static")) {
		if (ecmaVersion >= 13 && this.eat(types$1.braceL)) {
			this.parseClassStaticBlock(node);
			return node;
		}
		if (this.isClassElementNameStart() || this.type === types$1.star) isStatic = true;
		else keyName = "static";
	}
	node.static = isStatic;
	if (!keyName && ecmaVersion >= 8 && this.eatContextual("async")) {
		if ((this.isClassElementNameStart() || this.type === types$1.star) && !this.canInsertSemicolon()) isAsync = true;
		else keyName = "async";
	}
	if (!keyName && (ecmaVersion >= 9 || !isAsync) && this.eat(types$1.star)) isGenerator = true;
	if (!keyName && !isAsync && !isGenerator) {
		var lastValue = this.value;
		if (this.eatContextual("get") || this.eatContextual("set")) {
			if (this.isClassElementNameStart()) kind = lastValue;
			else keyName = lastValue;
		}
	}
	if (keyName) {
		node.computed = false;
		node.key = this.startNodeAt(this.lastTokStart, this.lastTokStartLoc);
		node.key.name = keyName;
		this.finishNode(node.key, "Identifier");
	} else this.parseClassElementName(node);
	if (ecmaVersion < 13 || this.type === types$1.parenL || kind !== "method" || isGenerator || isAsync) {
		var isConstructor = !node.static && checkKeyName(node, "constructor");
		var allowsDirectSuper = isConstructor && constructorAllowsSuper;
		if (isConstructor && kind !== "method") this.raise(node.key.start, "Constructor can't have get/set modifier");
		node.kind = isConstructor ? "constructor" : kind;
		this.parseClassMethod(node, isGenerator, isAsync, allowsDirectSuper);
	} else this.parseClassField(node);
	return node;
};
pp$8.isClassElementNameStart = function() {
	return this.type === types$1.name || this.type === types$1.privateId || this.type === types$1.num || this.type === types$1.string || this.type === types$1.bracketL || this.type.keyword;
};
pp$8.parseClassElementName = function(element) {
	if (this.type === types$1.privateId) {
		if (this.value === "constructor") this.raise(this.start, "Classes can't have an element named '#constructor'");
		element.computed = false;
		element.key = this.parsePrivateIdent();
	} else this.parsePropertyName(element);
};
pp$8.parseClassMethod = function(method, isGenerator, isAsync, allowsDirectSuper) {
	var key = method.key;
	if (method.kind === "constructor") {
		if (isGenerator) this.raise(key.start, "Constructor can't be a generator");
		if (isAsync) this.raise(key.start, "Constructor can't be an async method");
	} else if (method.static && checkKeyName(method, "prototype")) this.raise(key.start, "Classes may not have a static property named prototype");
	var value = method.value = this.parseMethod(isGenerator, isAsync, allowsDirectSuper);
	if (method.kind === "get" && value.params.length !== 0) this.raiseRecoverable(value.start, "getter should have no params");
	if (method.kind === "set" && value.params.length !== 1) this.raiseRecoverable(value.start, "setter should have exactly one param");
	if (method.kind === "set" && value.params[0].type === "RestElement") this.raiseRecoverable(value.params[0].start, "Setter cannot use rest params");
	return this.finishNode(method, "MethodDefinition");
};
pp$8.parseClassField = function(field) {
	if (checkKeyName(field, "constructor")) this.raise(field.key.start, "Classes can't have a field named 'constructor'");
	else if (field.static && checkKeyName(field, "prototype")) this.raise(field.key.start, "Classes can't have a static field named 'prototype'");
	if (this.eat(types$1.eq)) {
		this.enterScope(SCOPE_CLASS_FIELD_INIT | SCOPE_SUPER);
		field.value = this.parseMaybeAssign();
		this.exitScope();
	} else field.value = null;
	this.semicolon();
	return this.finishNode(field, "PropertyDefinition");
};
pp$8.parseClassStaticBlock = function(node) {
	node.body = [];
	var oldLabels = this.labels;
	this.labels = [];
	this.enterScope(SCOPE_CLASS_STATIC_BLOCK | SCOPE_SUPER);
	while (this.type !== types$1.braceR) {
		var stmt = this.parseStatement(null);
		node.body.push(stmt);
	}
	this.next();
	this.exitScope();
	this.labels = oldLabels;
	return this.finishNode(node, "StaticBlock");
};
pp$8.parseClassId = function(node, isStatement) {
	if (this.type === types$1.name) {
		node.id = this.parseIdent();
		if (isStatement) this.checkLValSimple(node.id, BIND_LEXICAL, false);
	} else {
		if (isStatement === true) this.unexpected();
		node.id = null;
	}
};
pp$8.parseClassSuper = function(node) {
	node.superClass = this.eat(types$1._extends) ? this.parseExprSubscripts(null, false) : null;
};
pp$8.enterClassBody = function() {
	var element = {
		declared: Object.create(null),
		used: []
	};
	this.privateNameStack.push(element);
	return element.declared;
};
pp$8.exitClassBody = function() {
	var ref = this.privateNameStack.pop();
	var declared = ref.declared;
	var used = ref.used;
	if (!this.options.checkPrivateFields) return;
	var len = this.privateNameStack.length;
	var parent = len === 0 ? null : this.privateNameStack[len - 1];
	for (var i = 0; i < used.length; ++i) {
		var id = used[i];
		if (!hasOwn(declared, id.name)) {
			if (parent) parent.used.push(id);
			else this.raiseRecoverable(id.start, "Private field '#" + id.name + "' must be declared in an enclosing class");
		}
	}
};
function isPrivateNameConflicted(privateNameMap, element) {
	var name = element.key.name;
	var curr = privateNameMap[name];
	var next = "true";
	if (element.type === "MethodDefinition" && (element.kind === "get" || element.kind === "set")) next = (element.static ? "s" : "i") + element.kind;
	if (curr === "iget" && next === "iset" || curr === "iset" && next === "iget" || curr === "sget" && next === "sset" || curr === "sset" && next === "sget") {
		privateNameMap[name] = "true";
		return false;
	} else if (!curr) {
		privateNameMap[name] = next;
		return false;
	} else return true;
}
function checkKeyName(node, name) {
	var computed = node.computed;
	var key = node.key;
	return !computed && (key.type === "Identifier" && key.name === name || key.type === "Literal" && key.value === name);
}
pp$8.parseExportAllDeclaration = function(node, exports$1) {
	if (this.options.ecmaVersion >= 11) {
		if (this.eatContextual("as")) {
			node.exported = this.parseModuleExportName();
			this.checkExport(exports$1, node.exported, this.lastTokStart);
		} else node.exported = null;
	}
	this.expectContextual("from");
	if (this.type !== types$1.string) this.unexpected();
	node.source = this.parseExprAtom();
	if (this.options.ecmaVersion >= 16) node.attributes = this.parseWithClause();
	this.semicolon();
	return this.finishNode(node, "ExportAllDeclaration");
};
pp$8.parseExport = function(node, exports$1) {
	this.next();
	if (this.eat(types$1.star)) return this.parseExportAllDeclaration(node, exports$1);
	if (this.eat(types$1._default)) {
		this.checkExport(exports$1, "default", this.lastTokStart);
		node.declaration = this.parseExportDefaultDeclaration();
		return this.finishNode(node, "ExportDefaultDeclaration");
	}
	if (this.shouldParseExportStatement()) {
		node.declaration = this.parseExportDeclaration(node);
		if (node.declaration.type === "VariableDeclaration") this.checkVariableExport(exports$1, node.declaration.declarations);
		else this.checkExport(exports$1, node.declaration.id, node.declaration.id.start);
		node.specifiers = [];
		node.source = null;
		if (this.options.ecmaVersion >= 16) node.attributes = [];
	} else {
		node.declaration = null;
		node.specifiers = this.parseExportSpecifiers(exports$1);
		if (this.eatContextual("from")) {
			if (this.type !== types$1.string) this.unexpected();
			node.source = this.parseExprAtom();
			if (this.options.ecmaVersion >= 16) node.attributes = this.parseWithClause();
		} else {
			for (var i = 0, list = node.specifiers; i < list.length; i += 1) {
				var spec = list[i];
				this.checkUnreserved(spec.local);
				this.checkLocalExport(spec.local);
				if (spec.local.type === "Literal") this.raise(spec.local.start, "A string literal cannot be used as an exported binding without `from`.");
			}
			node.source = null;
			if (this.options.ecmaVersion >= 16) node.attributes = [];
		}
		this.semicolon();
	}
	return this.finishNode(node, "ExportNamedDeclaration");
};
pp$8.parseExportDeclaration = function(node) {
	return this.parseStatement(null);
};
pp$8.parseExportDefaultDeclaration = function() {
	var isAsync;
	if (this.type === types$1._function || (isAsync = this.isAsyncFunction())) {
		var fNode = this.startNode();
		this.next();
		if (isAsync) this.next();
		return this.parseFunction(fNode, FUNC_STATEMENT | FUNC_NULLABLE_ID, false, isAsync);
	} else if (this.type === types$1._class) {
		var cNode = this.startNode();
		return this.parseClass(cNode, "nullableID");
	} else {
		var declaration = this.parseMaybeAssign();
		this.semicolon();
		return declaration;
	}
};
pp$8.checkExport = function(exports$1, name, pos) {
	if (!exports$1) return;
	if (typeof name !== "string") name = name.type === "Identifier" ? name.name : name.value;
	if (hasOwn(exports$1, name)) this.raiseRecoverable(pos, "Duplicate export '" + name + "'");
	exports$1[name] = true;
};
pp$8.checkPatternExport = function(exports$1, pat) {
	var type = pat.type;
	if (type === "Identifier") this.checkExport(exports$1, pat, pat.start);
	else if (type === "ObjectPattern") for (var i = 0, list = pat.properties; i < list.length; i += 1) {
		var prop = list[i];
		this.checkPatternExport(exports$1, prop);
	}
	else if (type === "ArrayPattern") for (var i$1 = 0, list$1 = pat.elements; i$1 < list$1.length; i$1 += 1) {
		var elt = list$1[i$1];
		if (elt) this.checkPatternExport(exports$1, elt);
	}
	else if (type === "Property") this.checkPatternExport(exports$1, pat.value);
	else if (type === "AssignmentPattern") this.checkPatternExport(exports$1, pat.left);
	else if (type === "RestElement") this.checkPatternExport(exports$1, pat.argument);
};
pp$8.checkVariableExport = function(exports$1, decls) {
	if (!exports$1) return;
	for (var i = 0, list = decls; i < list.length; i += 1) {
		var decl = list[i];
		this.checkPatternExport(exports$1, decl.id);
	}
};
pp$8.shouldParseExportStatement = function() {
	return this.type.keyword === "var" || this.type.keyword === "const" || this.type.keyword === "class" || this.type.keyword === "function" || this.isLet() || this.isAsyncFunction();
};
pp$8.parseExportSpecifier = function(exports$1) {
	var node = this.startNode();
	node.local = this.parseModuleExportName();
	node.exported = this.eatContextual("as") ? this.parseModuleExportName() : node.local;
	this.checkExport(exports$1, node.exported, node.exported.start);
	return this.finishNode(node, "ExportSpecifier");
};
pp$8.parseExportSpecifiers = function(exports$1) {
	var nodes = [], first = true;
	this.expect(types$1.braceL);
	while (!this.eat(types$1.braceR)) {
		if (!first) {
			this.expect(types$1.comma);
			if (this.afterTrailingComma(types$1.braceR)) break;
		} else first = false;
		nodes.push(this.parseExportSpecifier(exports$1));
	}
	return nodes;
};
pp$8.parseImport = function(node) {
	this.next();
	if (this.type === types$1.string) {
		node.specifiers = empty$1;
		node.source = this.parseExprAtom();
	} else {
		node.specifiers = this.parseImportSpecifiers();
		this.expectContextual("from");
		node.source = this.type === types$1.string ? this.parseExprAtom() : this.unexpected();
	}
	if (this.options.ecmaVersion >= 16) node.attributes = this.parseWithClause();
	this.semicolon();
	return this.finishNode(node, "ImportDeclaration");
};
pp$8.parseImportSpecifier = function() {
	var node = this.startNode();
	node.imported = this.parseModuleExportName();
	if (this.eatContextual("as")) node.local = this.parseIdent();
	else {
		this.checkUnreserved(node.imported);
		node.local = node.imported;
	}
	this.checkLValSimple(node.local, BIND_LEXICAL);
	return this.finishNode(node, "ImportSpecifier");
};
pp$8.parseImportDefaultSpecifier = function() {
	var node = this.startNode();
	node.local = this.parseIdent();
	this.checkLValSimple(node.local, BIND_LEXICAL);
	return this.finishNode(node, "ImportDefaultSpecifier");
};
pp$8.parseImportNamespaceSpecifier = function() {
	var node = this.startNode();
	this.next();
	this.expectContextual("as");
	node.local = this.parseIdent();
	this.checkLValSimple(node.local, BIND_LEXICAL);
	return this.finishNode(node, "ImportNamespaceSpecifier");
};
pp$8.parseImportSpecifiers = function() {
	var nodes = [], first = true;
	if (this.type === types$1.name) {
		nodes.push(this.parseImportDefaultSpecifier());
		if (!this.eat(types$1.comma)) return nodes;
	}
	if (this.type === types$1.star) {
		nodes.push(this.parseImportNamespaceSpecifier());
		return nodes;
	}
	this.expect(types$1.braceL);
	while (!this.eat(types$1.braceR)) {
		if (!first) {
			this.expect(types$1.comma);
			if (this.afterTrailingComma(types$1.braceR)) break;
		} else first = false;
		nodes.push(this.parseImportSpecifier());
	}
	return nodes;
};
pp$8.parseWithClause = function() {
	var nodes = [];
	if (!this.eat(types$1._with)) return nodes;
	this.expect(types$1.braceL);
	var attributeKeys = {};
	var first = true;
	while (!this.eat(types$1.braceR)) {
		if (!first) {
			this.expect(types$1.comma);
			if (this.afterTrailingComma(types$1.braceR)) break;
		} else first = false;
		var attr = this.parseImportAttribute();
		var keyName = attr.key.type === "Identifier" ? attr.key.name : attr.key.value;
		if (hasOwn(attributeKeys, keyName)) this.raiseRecoverable(attr.key.start, "Duplicate attribute key '" + keyName + "'");
		attributeKeys[keyName] = true;
		nodes.push(attr);
	}
	return nodes;
};
pp$8.parseImportAttribute = function() {
	var node = this.startNode();
	node.key = this.type === types$1.string ? this.parseExprAtom() : this.parseIdent(this.options.allowReserved !== "never");
	this.expect(types$1.colon);
	if (this.type !== types$1.string) this.unexpected();
	node.value = this.parseExprAtom();
	return this.finishNode(node, "ImportAttribute");
};
pp$8.parseModuleExportName = function() {
	if (this.options.ecmaVersion >= 13 && this.type === types$1.string) {
		var stringLiteral = this.parseLiteral(this.value);
		if (loneSurrogate.test(stringLiteral.value)) this.raise(stringLiteral.start, "An export name cannot include a lone surrogate.");
		return stringLiteral;
	}
	return this.parseIdent(true);
};
pp$8.adaptDirectivePrologue = function(statements) {
	for (var i = 0; i < statements.length && this.isDirectiveCandidate(statements[i]); ++i) statements[i].directive = statements[i].expression.raw.slice(1, -1);
};
pp$8.isDirectiveCandidate = function(statement) {
	return this.options.ecmaVersion >= 5 && statement.type === "ExpressionStatement" && statement.expression.type === "Literal" && typeof statement.expression.value === "string" && (this.input[statement.start] === "\"" || this.input[statement.start] === "'");
};
var pp$7 = Parser.prototype;
pp$7.toAssignable = function(node, isBinding, refDestructuringErrors) {
	if (this.options.ecmaVersion >= 6 && node) switch (node.type) {
		case "Identifier":
			if (this.inAsync && node.name === "await") this.raise(node.start, "Cannot use 'await' as identifier inside an async function");
			break;
		case "ObjectPattern":
		case "ArrayPattern":
		case "AssignmentPattern":
		case "RestElement": break;
		case "ObjectExpression":
			node.type = "ObjectPattern";
			if (refDestructuringErrors) this.checkPatternErrors(refDestructuringErrors, true);
			for (var i = 0, list = node.properties; i < list.length; i += 1) {
				var prop = list[i];
				this.toAssignable(prop, isBinding);
				if (prop.type === "RestElement" && (prop.argument.type === "ArrayPattern" || prop.argument.type === "ObjectPattern")) this.raise(prop.argument.start, "Unexpected token");
			}
			break;
		case "Property":
			if (node.kind !== "init") this.raise(node.key.start, "Object pattern can't contain getter or setter");
			this.toAssignable(node.value, isBinding);
			break;
		case "ArrayExpression":
			node.type = "ArrayPattern";
			if (refDestructuringErrors) this.checkPatternErrors(refDestructuringErrors, true);
			this.toAssignableList(node.elements, isBinding);
			break;
		case "SpreadElement":
			node.type = "RestElement";
			this.toAssignable(node.argument, isBinding);
			if (node.argument.type === "AssignmentPattern") this.raise(node.argument.start, "Rest elements cannot have a default value");
			break;
		case "AssignmentExpression":
			if (node.operator !== "=") this.raise(node.left.end, "Only '=' operator can be used for specifying default value.");
			node.type = "AssignmentPattern";
			delete node.operator;
			this.toAssignable(node.left, isBinding);
			break;
		case "ParenthesizedExpression":
			this.toAssignable(node.expression, isBinding, refDestructuringErrors);
			break;
		case "ChainExpression":
			this.raiseRecoverable(node.start, "Optional chaining cannot appear in left-hand side");
			break;
		case "MemberExpression": if (!isBinding) break;
		default: this.raise(node.start, "Assigning to rvalue");
	}
	else if (refDestructuringErrors) this.checkPatternErrors(refDestructuringErrors, true);
	return node;
};
pp$7.toAssignableList = function(exprList, isBinding) {
	var end = exprList.length;
	for (var i = 0; i < end; i++) {
		var elt = exprList[i];
		if (elt) this.toAssignable(elt, isBinding);
	}
	if (end) {
		var last = exprList[end - 1];
		if (this.options.ecmaVersion === 6 && isBinding && last && last.type === "RestElement" && last.argument.type !== "Identifier") this.unexpected(last.argument.start);
	}
	return exprList;
};
pp$7.parseSpread = function(refDestructuringErrors) {
	var node = this.startNode();
	this.next();
	node.argument = this.parseMaybeAssign(false, refDestructuringErrors);
	return this.finishNode(node, "SpreadElement");
};
pp$7.parseRestBinding = function() {
	var node = this.startNode();
	this.next();
	if (this.options.ecmaVersion === 6 && this.type !== types$1.name) this.unexpected();
	node.argument = this.parseBindingAtom();
	return this.finishNode(node, "RestElement");
};
pp$7.parseBindingAtom = function() {
	if (this.options.ecmaVersion >= 6) switch (this.type) {
		case types$1.bracketL:
			var node = this.startNode();
			this.next();
			node.elements = this.parseBindingList(types$1.bracketR, true, true);
			return this.finishNode(node, "ArrayPattern");
		case types$1.braceL: return this.parseObj(true);
	}
	return this.parseIdent();
};
pp$7.parseBindingList = function(close, allowEmpty, allowTrailingComma, allowModifiers) {
	var elts = [], first = true;
	while (!this.eat(close)) {
		if (first) first = false;
		else this.expect(types$1.comma);
		if (allowEmpty && this.type === types$1.comma) elts.push(null);
		else if (allowTrailingComma && this.afterTrailingComma(close)) break;
		else if (this.type === types$1.ellipsis) {
			var rest = this.parseRestBinding();
			this.parseBindingListItem(rest);
			elts.push(rest);
			if (this.type === types$1.comma) this.raiseRecoverable(this.start, "Comma is not permitted after the rest element");
			this.expect(close);
			break;
		} else elts.push(this.parseAssignableListItem(allowModifiers));
	}
	return elts;
};
pp$7.parseAssignableListItem = function(allowModifiers) {
	var elem = this.parseMaybeDefault(this.start, this.startLoc);
	this.parseBindingListItem(elem);
	return elem;
};
pp$7.parseBindingListItem = function(param) {
	return param;
};
pp$7.parseMaybeDefault = function(startPos, startLoc, left) {
	left = left || this.parseBindingAtom();
	if (this.options.ecmaVersion < 6 || !this.eat(types$1.eq)) return left;
	var node = this.startNodeAt(startPos, startLoc);
	node.left = left;
	node.right = this.parseMaybeAssign();
	return this.finishNode(node, "AssignmentPattern");
};
pp$7.checkLValSimple = function(expr, bindingType, checkClashes) {
	if (bindingType === void 0) bindingType = BIND_NONE;
	var isBind = bindingType !== BIND_NONE;
	switch (expr.type) {
		case "Identifier":
			if (this.strict && this.reservedWordsStrictBind.test(expr.name)) this.raiseRecoverable(expr.start, (isBind ? "Binding " : "Assigning to ") + expr.name + " in strict mode");
			if (isBind) {
				if (bindingType === BIND_LEXICAL && expr.name === "let") this.raiseRecoverable(expr.start, "let is disallowed as a lexically bound name");
				if (checkClashes) {
					if (hasOwn(checkClashes, expr.name)) this.raiseRecoverable(expr.start, "Argument name clash");
					checkClashes[expr.name] = true;
				}
				if (bindingType !== BIND_OUTSIDE) this.declareName(expr.name, bindingType, expr.start);
			}
			break;
		case "ChainExpression":
			this.raiseRecoverable(expr.start, "Optional chaining cannot appear in left-hand side");
			break;
		case "MemberExpression":
			if (isBind) this.raiseRecoverable(expr.start, "Binding member expression");
			break;
		case "ParenthesizedExpression":
			if (isBind) this.raiseRecoverable(expr.start, "Binding parenthesized expression");
			return this.checkLValSimple(expr.expression, bindingType, checkClashes);
		default: this.raise(expr.start, (isBind ? "Binding" : "Assigning to") + " rvalue");
	}
};
pp$7.checkLValPattern = function(expr, bindingType, checkClashes) {
	if (bindingType === void 0) bindingType = BIND_NONE;
	switch (expr.type) {
		case "ObjectPattern":
			for (var i = 0, list = expr.properties; i < list.length; i += 1) {
				var prop = list[i];
				this.checkLValInnerPattern(prop, bindingType, checkClashes);
			}
			break;
		case "ArrayPattern":
			for (var i$1 = 0, list$1 = expr.elements; i$1 < list$1.length; i$1 += 1) {
				var elem = list$1[i$1];
				if (elem) this.checkLValInnerPattern(elem, bindingType, checkClashes);
			}
			break;
		default: this.checkLValSimple(expr, bindingType, checkClashes);
	}
};
pp$7.checkLValInnerPattern = function(expr, bindingType, checkClashes) {
	if (bindingType === void 0) bindingType = BIND_NONE;
	switch (expr.type) {
		case "Property":
			this.checkLValInnerPattern(expr.value, bindingType, checkClashes);
			break;
		case "AssignmentPattern":
			this.checkLValPattern(expr.left, bindingType, checkClashes);
			break;
		case "RestElement":
			this.checkLValPattern(expr.argument, bindingType, checkClashes);
			break;
		default: this.checkLValPattern(expr, bindingType, checkClashes);
	}
};
var TokContext = function TokContext(token, isExpr, preserveSpace, override, generator) {
	this.token = token;
	this.isExpr = !!isExpr;
	this.preserveSpace = !!preserveSpace;
	this.override = override;
	this.generator = !!generator;
};
var types = {
	b_stat: new TokContext("{", false),
	b_expr: new TokContext("{", true),
	b_tmpl: new TokContext("${", false),
	p_stat: new TokContext("(", false),
	p_expr: new TokContext("(", true),
	q_tmpl: new TokContext("`", true, true, function(p) {
		return p.tryReadTemplateToken();
	}),
	f_stat: new TokContext("function", false),
	f_expr: new TokContext("function", true),
	f_expr_gen: new TokContext("function", true, false, null, true),
	f_gen: new TokContext("function", false, false, null, true)
};
var pp$6 = Parser.prototype;
pp$6.initialContext = function() {
	return [types.b_stat];
};
pp$6.curContext = function() {
	return this.context[this.context.length - 1];
};
pp$6.braceIsBlock = function(prevType) {
	var parent = this.curContext();
	if (parent === types.f_expr || parent === types.f_stat) return true;
	if (prevType === types$1.colon && (parent === types.b_stat || parent === types.b_expr)) return !parent.isExpr;
	if (prevType === types$1._return || prevType === types$1.name && this.exprAllowed) return lineBreak.test(this.input.slice(this.lastTokEnd, this.start));
	if (prevType === types$1._else || prevType === types$1.semi || prevType === types$1.eof || prevType === types$1.parenR || prevType === types$1.arrow) return true;
	if (prevType === types$1.braceL) return parent === types.b_stat;
	if (prevType === types$1._var || prevType === types$1._const || prevType === types$1.name) return false;
	return !this.exprAllowed;
};
pp$6.inGeneratorContext = function() {
	for (var i = this.context.length - 1; i >= 1; i--) {
		var context = this.context[i];
		if (context.token === "function") return context.generator;
	}
	return false;
};
pp$6.updateContext = function(prevType) {
	var update, type = this.type;
	if (type.keyword && prevType === types$1.dot) this.exprAllowed = false;
	else if (update = type.updateContext) update.call(this, prevType);
	else this.exprAllowed = type.beforeExpr;
};
pp$6.overrideContext = function(tokenCtx) {
	if (this.curContext() !== tokenCtx) this.context[this.context.length - 1] = tokenCtx;
};
types$1.parenR.updateContext = types$1.braceR.updateContext = function() {
	if (this.context.length === 1) {
		this.exprAllowed = true;
		return;
	}
	var out = this.context.pop();
	if (out === types.b_stat && this.curContext().token === "function") out = this.context.pop();
	this.exprAllowed = !out.isExpr;
};
types$1.braceL.updateContext = function(prevType) {
	this.context.push(this.braceIsBlock(prevType) ? types.b_stat : types.b_expr);
	this.exprAllowed = true;
};
types$1.dollarBraceL.updateContext = function() {
	this.context.push(types.b_tmpl);
	this.exprAllowed = true;
};
types$1.parenL.updateContext = function(prevType) {
	var statementParens = prevType === types$1._if || prevType === types$1._for || prevType === types$1._with || prevType === types$1._while;
	this.context.push(statementParens ? types.p_stat : types.p_expr);
	this.exprAllowed = true;
};
types$1.incDec.updateContext = function() {};
types$1._function.updateContext = types$1._class.updateContext = function(prevType) {
	if (prevType.beforeExpr && prevType !== types$1._else && !(prevType === types$1.semi && this.curContext() !== types.p_stat) && !(prevType === types$1._return && lineBreak.test(this.input.slice(this.lastTokEnd, this.start))) && !((prevType === types$1.colon || prevType === types$1.braceL) && this.curContext() === types.b_stat)) this.context.push(types.f_expr);
	else this.context.push(types.f_stat);
	this.exprAllowed = false;
};
types$1.colon.updateContext = function() {
	if (this.curContext().token === "function") this.context.pop();
	this.exprAllowed = true;
};
types$1.backQuote.updateContext = function() {
	if (this.curContext() === types.q_tmpl) this.context.pop();
	else this.context.push(types.q_tmpl);
	this.exprAllowed = false;
};
types$1.star.updateContext = function(prevType) {
	if (prevType === types$1._function) {
		var index = this.context.length - 1;
		if (this.context[index] === types.f_expr) this.context[index] = types.f_expr_gen;
		else this.context[index] = types.f_gen;
	}
	this.exprAllowed = true;
};
types$1.name.updateContext = function(prevType) {
	var allowed = false;
	if (this.options.ecmaVersion >= 6 && prevType !== types$1.dot) {
		if (this.value === "of" && !this.exprAllowed || this.value === "yield" && this.inGeneratorContext()) allowed = true;
	}
	this.exprAllowed = allowed;
};
var pp$5 = Parser.prototype;
pp$5.checkPropClash = function(prop, propHash, refDestructuringErrors) {
	if (this.options.ecmaVersion >= 9 && prop.type === "SpreadElement") return;
	if (this.options.ecmaVersion >= 6 && (prop.computed || prop.method || prop.shorthand)) return;
	var key = prop.key;
	var name;
	switch (key.type) {
		case "Identifier":
			name = key.name;
			break;
		case "Literal":
			name = String(key.value);
			break;
		default: return;
	}
	var kind = prop.kind;
	if (this.options.ecmaVersion >= 6) {
		if (name === "__proto__" && kind === "init") {
			if (propHash.proto) {
				if (refDestructuringErrors) {
					if (refDestructuringErrors.doubleProto < 0) refDestructuringErrors.doubleProto = key.start;
				} else this.raiseRecoverable(key.start, "Redefinition of __proto__ property");
			}
			propHash.proto = true;
		}
		return;
	}
	name = "$" + name;
	var other = propHash[name];
	if (other) {
		var redefinition;
		if (kind === "init") redefinition = this.strict && other.init || other.get || other.set;
		else redefinition = other.init || other[kind];
		if (redefinition) this.raiseRecoverable(key.start, "Redefinition of property");
	} else other = propHash[name] = {
		init: false,
		get: false,
		set: false
	};
	other[kind] = true;
};
pp$5.parseExpression = function(forInit, refDestructuringErrors) {
	var this$1$1 = this;
	return this.catchStackOverflow(function() {
		var startPos = this$1$1.start, startLoc = this$1$1.startLoc;
		var expr = this$1$1.parseMaybeAssign(forInit, refDestructuringErrors);
		if (this$1$1.type === types$1.comma) {
			var node = this$1$1.startNodeAt(startPos, startLoc);
			node.expressions = [expr];
			while (this$1$1.eat(types$1.comma)) node.expressions.push(this$1$1.parseMaybeAssign(forInit, refDestructuringErrors));
			return this$1$1.finishNode(node, "SequenceExpression");
		}
		return expr;
	});
};
pp$5.parseMaybeAssign = function(forInit, refDestructuringErrors, afterLeftParse) {
	if (this.isContextual("yield")) {
		if (this.inGenerator) return this.parseYield(forInit);
		else this.exprAllowed = false;
	}
	var ownDestructuringErrors = false, oldParenAssign = -1, oldTrailingComma = -1, oldDoubleProto = -1;
	if (refDestructuringErrors) {
		oldParenAssign = refDestructuringErrors.parenthesizedAssign;
		oldTrailingComma = refDestructuringErrors.trailingComma;
		oldDoubleProto = refDestructuringErrors.doubleProto;
		refDestructuringErrors.parenthesizedAssign = refDestructuringErrors.trailingComma = -1;
	} else {
		refDestructuringErrors = new DestructuringErrors();
		ownDestructuringErrors = true;
	}
	var startPos = this.start, startLoc = this.startLoc;
	if (this.type === types$1.parenL || this.type === types$1.name) {
		this.potentialArrowAt = this.start;
		this.potentialArrowInForAwait = forInit === "await";
	}
	var left = this.parseMaybeConditional(forInit, refDestructuringErrors);
	if (afterLeftParse) left = afterLeftParse.call(this, left, startPos, startLoc);
	if (this.type.isAssign) {
		var node = this.startNodeAt(startPos, startLoc);
		node.operator = this.value;
		if (this.type === types$1.eq) left = this.toAssignable(left, false, refDestructuringErrors);
		if (!ownDestructuringErrors) refDestructuringErrors.parenthesizedAssign = refDestructuringErrors.trailingComma = refDestructuringErrors.doubleProto = -1;
		if (refDestructuringErrors.shorthandAssign >= left.start) refDestructuringErrors.shorthandAssign = -1;
		if (this.type === types$1.eq) this.checkLValPattern(left);
		else this.checkLValSimple(left);
		node.left = left;
		this.next();
		node.right = this.parseMaybeAssign(forInit);
		if (oldDoubleProto > -1) refDestructuringErrors.doubleProto = oldDoubleProto;
		return this.finishNode(node, "AssignmentExpression");
	} else if (ownDestructuringErrors) this.checkExpressionErrors(refDestructuringErrors, true);
	if (oldParenAssign > -1) refDestructuringErrors.parenthesizedAssign = oldParenAssign;
	if (oldTrailingComma > -1) refDestructuringErrors.trailingComma = oldTrailingComma;
	return left;
};
pp$5.parseMaybeConditional = function(forInit, refDestructuringErrors) {
	var startPos = this.start, startLoc = this.startLoc;
	var expr = this.parseExprOps(forInit, refDestructuringErrors);
	if (this.checkExpressionErrors(refDestructuringErrors)) return expr;
	if (!(expr.type === "ArrowFunctionExpression" && expr.start === startPos) && this.eat(types$1.question)) {
		var node = this.startNodeAt(startPos, startLoc);
		node.test = expr;
		node.consequent = this.parseMaybeAssign();
		this.expect(types$1.colon);
		node.alternate = this.parseMaybeAssign(forInit);
		return this.finishNode(node, "ConditionalExpression");
	}
	return expr;
};
pp$5.parseExprOps = function(forInit, refDestructuringErrors) {
	var startPos = this.start, startLoc = this.startLoc;
	var expr = this.parseMaybeUnary(refDestructuringErrors, false, false, forInit);
	if (this.checkExpressionErrors(refDestructuringErrors)) return expr;
	return expr.start === startPos && expr.type === "ArrowFunctionExpression" ? expr : this.parseExprOp(expr, startPos, startLoc, -1, forInit);
};
pp$5.parseExprOp = function(left, leftStartPos, leftStartLoc, minPrec, forInit) {
	var prec = this.type.binop;
	if (prec != null && (!forInit || this.type !== types$1._in)) {
		if (prec > minPrec) {
			var logical = this.type === types$1.logicalOR || this.type === types$1.logicalAND;
			var coalesce = this.type === types$1.coalesce;
			if (coalesce) prec = types$1.logicalAND.binop;
			var op = this.value;
			this.next();
			var startPos = this.start, startLoc = this.startLoc;
			var right = this.parseExprOp(this.parseMaybeUnary(null, false, false, forInit), startPos, startLoc, prec, forInit);
			var node = this.buildBinary(leftStartPos, leftStartLoc, left, right, op, logical || coalesce);
			if (logical && this.type === types$1.coalesce || coalesce && (this.type === types$1.logicalOR || this.type === types$1.logicalAND)) this.raiseRecoverable(this.start, "Logical expressions and coalesce expressions cannot be mixed. Wrap either by parentheses");
			return this.parseExprOp(node, leftStartPos, leftStartLoc, minPrec, forInit);
		}
	}
	return left;
};
pp$5.buildBinary = function(startPos, startLoc, left, right, op, logical) {
	if (right.type === "PrivateIdentifier") this.raise(right.start, "Private identifier can only be left side of binary expression");
	var node = this.startNodeAt(startPos, startLoc);
	node.left = left;
	node.operator = op;
	node.right = right;
	return this.finishNode(node, logical ? "LogicalExpression" : "BinaryExpression");
};
pp$5.parseMaybeUnary = function(refDestructuringErrors, sawUnary, incDec, forInit) {
	var startPos = this.start, startLoc = this.startLoc, expr;
	if (this.isContextual("await") && this.canAwait) {
		expr = this.parseAwait(forInit);
		sawUnary = true;
	} else if (this.type.prefix) {
		var node = this.startNode(), update = this.type === types$1.incDec;
		node.operator = this.value;
		node.prefix = true;
		this.next();
		node.argument = this.parseMaybeUnary(null, true, update, forInit);
		this.checkExpressionErrors(refDestructuringErrors, true);
		if (update) this.checkLValSimple(node.argument);
		else if (this.strict && node.operator === "delete" && isLocalVariableAccess(node.argument)) this.raiseRecoverable(node.start, "Deleting local variable in strict mode");
		else if (node.operator === "delete" && isPrivateFieldAccess(node.argument)) this.raiseRecoverable(node.start, "Private fields can not be deleted");
		else sawUnary = true;
		expr = this.finishNode(node, update ? "UpdateExpression" : "UnaryExpression");
	} else if (!sawUnary && this.type === types$1.privateId) {
		if ((forInit || this.privateNameStack.length === 0) && this.options.checkPrivateFields) this.unexpected();
		expr = this.parsePrivateIdent();
		if (this.type !== types$1._in) this.unexpected();
	} else {
		expr = this.parseExprSubscripts(refDestructuringErrors, forInit);
		if (this.checkExpressionErrors(refDestructuringErrors)) return expr;
		while (this.type.postfix && !this.canInsertSemicolon()) {
			var node$1 = this.startNodeAt(startPos, startLoc);
			node$1.operator = this.value;
			node$1.prefix = false;
			node$1.argument = expr;
			this.checkLValSimple(expr);
			this.next();
			expr = this.finishNode(node$1, "UpdateExpression");
		}
	}
	if (!incDec && !(expr.type === "ArrowFunctionExpression" && expr.start === startPos) && this.eat(types$1.starstar)) {
		if (sawUnary) this.unexpected(this.lastTokStart);
		else return this.buildBinary(startPos, startLoc, expr, this.parseMaybeUnary(null, false, false, forInit), "**", false);
	} else return expr;
};
function isLocalVariableAccess(node) {
	return node.type === "Identifier" || node.type === "ParenthesizedExpression" && isLocalVariableAccess(node.expression);
}
function isPrivateFieldAccess(node) {
	return node.type === "MemberExpression" && node.property.type === "PrivateIdentifier" || node.type === "ChainExpression" && isPrivateFieldAccess(node.expression) || node.type === "ParenthesizedExpression" && isPrivateFieldAccess(node.expression);
}
pp$5.parseExprSubscripts = function(refDestructuringErrors, forInit) {
	var startPos = this.start, startLoc = this.startLoc;
	var expr = this.parseExprAtom(refDestructuringErrors, forInit);
	if (expr.type === "ArrowFunctionExpression" && this.input.slice(this.lastTokStart, this.lastTokEnd) !== ")") return expr;
	var result = this.parseSubscripts(expr, startPos, startLoc, false, forInit);
	if (refDestructuringErrors && result.type === "MemberExpression") {
		if (refDestructuringErrors.parenthesizedAssign >= result.start) refDestructuringErrors.parenthesizedAssign = -1;
		if (refDestructuringErrors.parenthesizedBind >= result.start) refDestructuringErrors.parenthesizedBind = -1;
		if (refDestructuringErrors.trailingComma >= result.start) refDestructuringErrors.trailingComma = -1;
	}
	return result;
};
pp$5.parseSubscripts = function(base, startPos, startLoc, noCalls, forInit) {
	var maybeAsyncArrow = this.options.ecmaVersion >= 8 && base.type === "Identifier" && base.name === "async" && this.lastTokEnd === base.end && !this.canInsertSemicolon() && base.end - base.start === 5 && this.potentialArrowAt === base.start;
	var optionalChained = false;
	while (true) {
		var element = this.parseSubscript(base, startPos, startLoc, noCalls, maybeAsyncArrow, optionalChained, forInit);
		if (element.optional) optionalChained = true;
		if (element === base || element.type === "ArrowFunctionExpression") {
			if (optionalChained) {
				var chainNode = this.startNodeAt(startPos, startLoc);
				chainNode.expression = element;
				element = this.finishNode(chainNode, "ChainExpression");
			}
			return element;
		}
		base = element;
	}
};
pp$5.shouldParseAsyncArrow = function() {
	return !this.canInsertSemicolon() && this.eat(types$1.arrow);
};
pp$5.parseSubscriptAsyncArrow = function(startPos, startLoc, exprList, forInit) {
	return this.parseArrowExpression(this.startNodeAt(startPos, startLoc), exprList, true, forInit);
};
pp$5.parseSubscript = function(base, startPos, startLoc, noCalls, maybeAsyncArrow, optionalChained, forInit) {
	var optionalSupported = this.options.ecmaVersion >= 11;
	var optional = optionalSupported && this.eat(types$1.questionDot);
	if (noCalls && optional) this.raise(this.lastTokStart, "Optional chaining cannot appear in the callee of new expressions");
	var computed = this.eat(types$1.bracketL);
	if (computed || optional && this.type !== types$1.parenL && this.type !== types$1.backQuote || this.eat(types$1.dot)) {
		var node = this.startNodeAt(startPos, startLoc);
		node.object = base;
		if (computed) {
			node.property = this.parseExpression();
			this.expect(types$1.bracketR);
		} else if (this.type === types$1.privateId && base.type !== "Super") node.property = this.parsePrivateIdent();
		else node.property = this.parseIdent(this.options.allowReserved !== "never");
		node.computed = !!computed;
		if (optionalSupported) node.optional = optional;
		base = this.finishNode(node, "MemberExpression");
	} else if (!noCalls && this.eat(types$1.parenL)) {
		var refDestructuringErrors = new DestructuringErrors(), oldYieldPos = this.yieldPos, oldAwaitPos = this.awaitPos, oldAwaitIdentPos = this.awaitIdentPos;
		this.yieldPos = 0;
		this.awaitPos = 0;
		this.awaitIdentPos = 0;
		var exprList = this.parseExprList(types$1.parenR, this.options.ecmaVersion >= 8, false, refDestructuringErrors);
		if (maybeAsyncArrow && !optional && this.shouldParseAsyncArrow()) {
			this.checkPatternErrors(refDestructuringErrors, false);
			this.checkYieldAwaitInDefaultParams();
			if (this.awaitIdentPos > 0) this.raise(this.awaitIdentPos, "Cannot use 'await' as identifier inside an async function");
			this.yieldPos = oldYieldPos;
			this.awaitPos = oldAwaitPos;
			this.awaitIdentPos = oldAwaitIdentPos;
			return this.parseSubscriptAsyncArrow(startPos, startLoc, exprList, forInit);
		}
		this.checkExpressionErrors(refDestructuringErrors, true);
		this.yieldPos = oldYieldPos || this.yieldPos;
		this.awaitPos = oldAwaitPos || this.awaitPos;
		this.awaitIdentPos = oldAwaitIdentPos || this.awaitIdentPos;
		var node$1 = this.startNodeAt(startPos, startLoc);
		node$1.callee = base;
		node$1.arguments = exprList;
		if (optionalSupported) node$1.optional = optional;
		base = this.finishNode(node$1, "CallExpression");
	} else if (this.type === types$1.backQuote) {
		if (optional || optionalChained) this.raise(this.start, "Optional chaining cannot appear in the tag of tagged template expressions");
		var node$2 = this.startNodeAt(startPos, startLoc);
		node$2.tag = base;
		node$2.quasi = this.parseTemplate({ isTagged: true });
		base = this.finishNode(node$2, "TaggedTemplateExpression");
	}
	return base;
};
pp$5.parseExprAtom = function(refDestructuringErrors, forInit, forNew) {
	if (this.type === types$1.slash) this.readRegexp();
	var node, canBeArrow = this.potentialArrowAt === this.start;
	switch (this.type) {
		case types$1._super:
			if (!this.allowSuper) this.raise(this.start, "'super' keyword outside a method");
			node = this.startNode();
			this.next();
			if (this.type === types$1.parenL && !this.allowDirectSuper) this.raise(node.start, "super() call outside constructor of a subclass");
			if (this.type !== types$1.dot && this.type !== types$1.bracketL && this.type !== types$1.parenL) this.unexpected();
			return this.finishNode(node, "Super");
		case types$1._this:
			node = this.startNode();
			this.next();
			return this.finishNode(node, "ThisExpression");
		case types$1.name:
			var startPos = this.start, startLoc = this.startLoc, containsEsc = this.containsEsc;
			var id = this.parseIdent(false);
			if (this.options.ecmaVersion >= 8 && !containsEsc && id.name === "async" && !this.canInsertSemicolon() && this.eat(types$1._function)) {
				this.overrideContext(types.f_expr);
				return this.parseFunction(this.startNodeAt(startPos, startLoc), 0, false, true, forInit);
			}
			if (canBeArrow && !this.canInsertSemicolon()) {
				if (this.eat(types$1.arrow)) return this.parseArrowExpression(this.startNodeAt(startPos, startLoc), [id], false, forInit);
				if (this.options.ecmaVersion >= 8 && id.name === "async" && this.type === types$1.name && !containsEsc && (!this.potentialArrowInForAwait || this.value !== "of" || this.containsEsc)) {
					id = this.parseIdent(false);
					if (this.canInsertSemicolon() || !this.eat(types$1.arrow)) this.unexpected();
					return this.parseArrowExpression(this.startNodeAt(startPos, startLoc), [id], true, forInit);
				}
			}
			return id;
		case types$1.regexp:
			var value = this.value;
			node = this.parseLiteral(value.value);
			node.regex = {
				pattern: value.pattern,
				flags: value.flags
			};
			return node;
		case types$1.num:
		case types$1.string: return this.parseLiteral(this.value);
		case types$1._null:
		case types$1._true:
		case types$1._false:
			node = this.startNode();
			node.value = this.type === types$1._null ? null : this.type === types$1._true;
			node.raw = this.type.keyword;
			this.next();
			return this.finishNode(node, "Literal");
		case types$1.parenL:
			var start = this.start, expr = this.parseParenAndDistinguishExpression(canBeArrow, forInit);
			if (refDestructuringErrors) {
				if (refDestructuringErrors.parenthesizedAssign < 0 && !this.isSimpleAssignTarget(expr)) refDestructuringErrors.parenthesizedAssign = start;
				if (refDestructuringErrors.parenthesizedBind < 0) refDestructuringErrors.parenthesizedBind = start;
			}
			return expr;
		case types$1.bracketL:
			node = this.startNode();
			this.next();
			node.elements = this.parseExprList(types$1.bracketR, true, true, refDestructuringErrors);
			return this.finishNode(node, "ArrayExpression");
		case types$1.braceL:
			this.overrideContext(types.b_expr);
			return this.parseObj(false, refDestructuringErrors);
		case types$1._function:
			node = this.startNode();
			this.next();
			return this.parseFunction(node, 0);
		case types$1._class: return this.parseClass(this.startNode(), false);
		case types$1._new: return this.parseNew();
		case types$1.backQuote: return this.parseTemplate();
		case types$1._import: if (this.options.ecmaVersion >= 11) return this.parseExprImport(forNew);
		else return this.unexpected();
		default: return this.parseExprAtomDefault();
	}
};
pp$5.parseExprAtomDefault = function() {
	this.unexpected();
};
pp$5.parseExprImport = function(forNew) {
	var node = this.startNode();
	if (this.containsEsc) this.raiseRecoverable(this.start, "Escape sequence in keyword import");
	this.next();
	if (this.type === types$1.parenL && !forNew) return this.parseDynamicImport(node);
	else if (this.type === types$1.dot) {
		var meta = this.startNodeAt(node.start, node.loc && node.loc.start);
		meta.name = "import";
		node.meta = this.finishNode(meta, "Identifier");
		return this.parseImportMeta(node);
	} else this.unexpected();
};
pp$5.parseDynamicImport = function(node) {
	this.next();
	node.source = this.parseMaybeAssign();
	if (this.options.ecmaVersion >= 16) {
		if (!this.eat(types$1.parenR)) {
			this.expect(types$1.comma);
			if (!this.afterTrailingComma(types$1.parenR)) {
				node.options = this.parseMaybeAssign();
				if (!this.eat(types$1.parenR)) {
					this.expect(types$1.comma);
					if (!this.afterTrailingComma(types$1.parenR)) this.unexpected();
				}
			} else node.options = null;
		} else node.options = null;
	} else if (!this.eat(types$1.parenR)) {
		var errorPos = this.start;
		if (this.eat(types$1.comma) && this.eat(types$1.parenR)) this.raiseRecoverable(errorPos, "Trailing comma is not allowed in import()");
		else this.unexpected(errorPos);
	}
	return this.finishNode(node, "ImportExpression");
};
pp$5.parseImportMeta = function(node) {
	this.next();
	var containsEsc = this.containsEsc;
	node.property = this.parseIdent(true);
	if (node.property.name !== "meta") this.raiseRecoverable(node.property.start, "The only valid meta property for import is 'import.meta'");
	if (containsEsc) this.raiseRecoverable(node.start, "'import.meta' must not contain escaped characters");
	if (this.options.sourceType !== "module" && !this.options.allowImportExportEverywhere) this.raiseRecoverable(node.start, "Cannot use 'import.meta' outside a module");
	return this.finishNode(node, "MetaProperty");
};
pp$5.parseLiteral = function(value) {
	var node = this.startNode();
	node.value = value;
	node.raw = this.input.slice(this.start, this.end);
	if (node.raw.charCodeAt(node.raw.length - 1) === 110) node.bigint = node.value != null ? node.value.toString() : node.raw.slice(0, -1).replace(/_/g, "");
	this.next();
	return this.finishNode(node, "Literal");
};
pp$5.parseParenExpression = function() {
	this.expect(types$1.parenL);
	var val = this.parseExpression();
	this.expect(types$1.parenR);
	return val;
};
pp$5.shouldParseArrow = function(exprList) {
	return !this.canInsertSemicolon();
};
pp$5.parseParenAndDistinguishExpression = function(canBeArrow, forInit) {
	var startPos = this.start, startLoc = this.startLoc, val, allowTrailingComma = this.options.ecmaVersion >= 8;
	if (this.options.ecmaVersion >= 6) {
		this.next();
		var innerStartPos = this.start, innerStartLoc = this.startLoc;
		var exprList = [], first = true, lastIsComma = false;
		var refDestructuringErrors = new DestructuringErrors(), oldYieldPos = this.yieldPos, oldAwaitPos = this.awaitPos, spreadStart;
		this.yieldPos = 0;
		this.awaitPos = 0;
		while (this.type !== types$1.parenR) {
			first ? first = false : this.expect(types$1.comma);
			if (allowTrailingComma && this.afterTrailingComma(types$1.parenR, true)) {
				lastIsComma = true;
				break;
			} else if (this.type === types$1.ellipsis) {
				spreadStart = this.start;
				exprList.push(this.parseParenItem(this.parseRestBinding()));
				if (this.type === types$1.comma) this.raiseRecoverable(this.start, "Comma is not permitted after the rest element");
				break;
			} else exprList.push(this.parseMaybeAssign(false, refDestructuringErrors, this.parseParenItem));
		}
		var innerEndPos = this.lastTokEnd, innerEndLoc = this.lastTokEndLoc;
		this.expect(types$1.parenR);
		if (canBeArrow && this.shouldParseArrow(exprList) && this.eat(types$1.arrow)) {
			this.checkPatternErrors(refDestructuringErrors, false);
			this.checkYieldAwaitInDefaultParams();
			this.yieldPos = oldYieldPos;
			this.awaitPos = oldAwaitPos;
			return this.parseParenArrowList(startPos, startLoc, exprList, forInit);
		}
		if (!exprList.length || lastIsComma) this.unexpected(this.lastTokStart);
		if (spreadStart) this.unexpected(spreadStart);
		this.checkExpressionErrors(refDestructuringErrors, true);
		this.yieldPos = oldYieldPos || this.yieldPos;
		this.awaitPos = oldAwaitPos || this.awaitPos;
		if (exprList.length > 1) {
			val = this.startNodeAt(innerStartPos, innerStartLoc);
			val.expressions = exprList;
			this.finishNodeAt(val, "SequenceExpression", innerEndPos, innerEndLoc);
		} else val = exprList[0];
	} else val = this.parseParenExpression();
	if (this.options.preserveParens) {
		var par = this.startNodeAt(startPos, startLoc);
		par.expression = val;
		return this.finishNode(par, "ParenthesizedExpression");
	} else return val;
};
pp$5.parseParenItem = function(item) {
	return item;
};
pp$5.parseParenArrowList = function(startPos, startLoc, exprList, forInit) {
	return this.parseArrowExpression(this.startNodeAt(startPos, startLoc), exprList, false, forInit);
};
var empty = [];
pp$5.parseNew = function() {
	if (this.containsEsc) this.raiseRecoverable(this.start, "Escape sequence in keyword new");
	var node = this.startNode();
	this.next();
	if (this.options.ecmaVersion >= 6 && this.type === types$1.dot) {
		var meta = this.startNodeAt(node.start, node.loc && node.loc.start);
		meta.name = "new";
		node.meta = this.finishNode(meta, "Identifier");
		this.next();
		var containsEsc = this.containsEsc;
		node.property = this.parseIdent(true);
		if (node.property.name !== "target") this.raiseRecoverable(node.property.start, "The only valid meta property for new is 'new.target'");
		if (containsEsc) this.raiseRecoverable(node.start, "'new.target' must not contain escaped characters");
		if (!this.allowNewDotTarget) this.raiseRecoverable(node.start, "'new.target' can only be used in functions and class static block");
		return this.finishNode(node, "MetaProperty");
	}
	var startPos = this.start, startLoc = this.startLoc;
	node.callee = this.parseSubscripts(this.parseExprAtom(null, false, true), startPos, startLoc, true, false);
	if (node.callee.type === "Super") this.raiseRecoverable(startPos, "Invalid use of 'super'");
	if (this.eat(types$1.parenL)) node.arguments = this.parseExprList(types$1.parenR, this.options.ecmaVersion >= 8, false);
	else node.arguments = empty;
	return this.finishNode(node, "NewExpression");
};
pp$5.parseTemplateElement = function(ref) {
	var isTagged = ref.isTagged;
	var elem = this.startNode();
	if (this.type === types$1.invalidTemplate) {
		if (!isTagged) this.raiseRecoverable(this.start, "Bad escape sequence in untagged template literal");
		elem.value = {
			raw: this.value.replace(/\r\n?/g, "\n"),
			cooked: null
		};
	} else elem.value = {
		raw: this.input.slice(this.start, this.end).replace(/\r\n?/g, "\n"),
		cooked: this.value
	};
	this.next();
	elem.tail = this.type === types$1.backQuote;
	return this.finishNode(elem, "TemplateElement");
};
pp$5.parseTemplate = function(ref) {
	if (ref === void 0) ref = {};
	var isTagged = ref.isTagged;
	if (isTagged === void 0) isTagged = false;
	var node = this.startNode();
	this.next();
	node.expressions = [];
	var curElt = this.parseTemplateElement({ isTagged });
	node.quasis = [curElt];
	while (!curElt.tail) {
		if (this.type === types$1.eof) this.raise(this.pos, "Unterminated template literal");
		this.expect(types$1.dollarBraceL);
		node.expressions.push(this.parseExpression());
		this.expect(types$1.braceR);
		node.quasis.push(curElt = this.parseTemplateElement({ isTagged }));
	}
	this.next();
	return this.finishNode(node, "TemplateLiteral");
};
pp$5.isAsyncProp = function(prop) {
	return !prop.computed && prop.key.type === "Identifier" && prop.key.name === "async" && (this.type === types$1.name || this.type === types$1.num || this.type === types$1.string || this.type === types$1.bracketL || this.type.keyword || this.options.ecmaVersion >= 9 && this.type === types$1.star) && !lineBreak.test(this.input.slice(this.lastTokEnd, this.start));
};
pp$5.parseObj = function(isPattern, refDestructuringErrors) {
	var node = this.startNode(), first = true, propHash = {};
	node.properties = [];
	this.next();
	while (!this.eat(types$1.braceR)) {
		if (!first) {
			this.expect(types$1.comma);
			if (this.options.ecmaVersion >= 5 && this.afterTrailingComma(types$1.braceR)) break;
		} else first = false;
		var prop = this.parseProperty(isPattern, refDestructuringErrors);
		if (!isPattern) this.checkPropClash(prop, propHash, refDestructuringErrors);
		node.properties.push(prop);
	}
	return this.finishNode(node, isPattern ? "ObjectPattern" : "ObjectExpression");
};
pp$5.parseProperty = function(isPattern, refDestructuringErrors) {
	var prop = this.startNode(), isGenerator, isAsync, startPos, startLoc;
	if (this.options.ecmaVersion >= 9 && this.eat(types$1.ellipsis)) {
		if (isPattern) {
			prop.argument = this.parseIdent(false);
			if (this.type === types$1.comma) this.raiseRecoverable(this.start, "Comma is not permitted after the rest element");
			return this.finishNode(prop, "RestElement");
		}
		prop.argument = this.parseMaybeAssign(false, refDestructuringErrors);
		if (this.type === types$1.comma && refDestructuringErrors && refDestructuringErrors.trailingComma < 0) refDestructuringErrors.trailingComma = this.start;
		return this.finishNode(prop, "SpreadElement");
	}
	if (this.options.ecmaVersion >= 6) {
		prop.method = false;
		prop.shorthand = false;
		if (isPattern || refDestructuringErrors) {
			startPos = this.start;
			startLoc = this.startLoc;
		}
		if (!isPattern) isGenerator = this.eat(types$1.star);
	}
	var containsEsc = this.containsEsc;
	this.parsePropertyName(prop);
	if (!isPattern && !containsEsc && this.options.ecmaVersion >= 8 && !isGenerator && this.isAsyncProp(prop)) {
		isAsync = true;
		isGenerator = this.options.ecmaVersion >= 9 && this.eat(types$1.star);
		this.parsePropertyName(prop);
	} else isAsync = false;
	this.parsePropertyValue(prop, isPattern, isGenerator, isAsync, startPos, startLoc, refDestructuringErrors, containsEsc);
	return this.finishNode(prop, "Property");
};
pp$5.parseGetterSetter = function(prop) {
	var kind = prop.key.name;
	this.parsePropertyName(prop);
	prop.value = this.parseMethod(false);
	prop.kind = kind;
	var paramCount = prop.kind === "get" ? 0 : 1;
	if (prop.value.params.length !== paramCount) {
		var start = prop.value.start;
		if (prop.kind === "get") this.raiseRecoverable(start, "getter should have no params");
		else this.raiseRecoverable(start, "setter should have exactly one param");
	} else if (prop.kind === "set" && prop.value.params[0].type === "RestElement") this.raiseRecoverable(prop.value.params[0].start, "Setter cannot use rest params");
};
pp$5.parsePropertyValue = function(prop, isPattern, isGenerator, isAsync, startPos, startLoc, refDestructuringErrors, containsEsc) {
	if ((isGenerator || isAsync) && this.type === types$1.colon) this.unexpected();
	if (this.eat(types$1.colon)) {
		prop.value = isPattern ? this.parseMaybeDefault(this.start, this.startLoc) : this.parseMaybeAssign(false, refDestructuringErrors);
		prop.kind = "init";
	} else if (this.options.ecmaVersion >= 6 && this.type === types$1.parenL) {
		if (isPattern) this.unexpected();
		prop.method = true;
		prop.value = this.parseMethod(isGenerator, isAsync);
		prop.kind = "init";
	} else if (!isPattern && !containsEsc && this.options.ecmaVersion >= 5 && !prop.computed && prop.key.type === "Identifier" && (prop.key.name === "get" || prop.key.name === "set") && this.type !== types$1.comma && this.type !== types$1.braceR && this.type !== types$1.eq) {
		if (isGenerator || isAsync) this.unexpected();
		this.parseGetterSetter(prop);
	} else if (this.options.ecmaVersion >= 6 && !prop.computed && prop.key.type === "Identifier") {
		if (isGenerator || isAsync) this.unexpected();
		this.checkUnreserved(prop.key);
		if (prop.key.name === "await" && !this.awaitIdentPos) this.awaitIdentPos = startPos;
		if (isPattern) prop.value = this.parseMaybeDefault(startPos, startLoc, this.copyNode(prop.key));
		else if (this.type === types$1.eq && refDestructuringErrors) {
			if (refDestructuringErrors.shorthandAssign < 0) refDestructuringErrors.shorthandAssign = this.start;
			prop.value = this.parseMaybeDefault(startPos, startLoc, this.copyNode(prop.key));
		} else prop.value = this.copyNode(prop.key);
		prop.kind = "init";
		prop.shorthand = true;
	} else this.unexpected();
};
pp$5.parsePropertyName = function(prop) {
	if (this.options.ecmaVersion >= 6) {
		if (this.eat(types$1.bracketL)) {
			prop.computed = true;
			prop.key = this.parseMaybeAssign();
			this.expect(types$1.bracketR);
			return prop.key;
		} else prop.computed = false;
	}
	return prop.key = this.type === types$1.num || this.type === types$1.string ? this.parseExprAtom() : this.parseIdent(this.options.allowReserved !== "never");
};
pp$5.initFunction = function(node) {
	node.id = null;
	if (this.options.ecmaVersion >= 6) node.generator = node.expression = false;
	if (this.options.ecmaVersion >= 8) node.async = false;
};
pp$5.parseMethod = function(isGenerator, isAsync, allowDirectSuper) {
	var node = this.startNode(), oldYieldPos = this.yieldPos, oldAwaitPos = this.awaitPos, oldAwaitIdentPos = this.awaitIdentPos;
	this.initFunction(node);
	if (this.options.ecmaVersion >= 6) node.generator = isGenerator;
	if (this.options.ecmaVersion >= 8) node.async = !!isAsync;
	this.yieldPos = 0;
	this.awaitPos = 0;
	this.awaitIdentPos = 0;
	this.enterScope(functionFlags(isAsync, node.generator) | SCOPE_SUPER | (allowDirectSuper ? SCOPE_DIRECT_SUPER : 0));
	this.expect(types$1.parenL);
	node.params = this.parseBindingList(types$1.parenR, false, this.options.ecmaVersion >= 8);
	this.checkYieldAwaitInDefaultParams();
	this.parseFunctionBody(node, false, true, false);
	this.yieldPos = oldYieldPos;
	this.awaitPos = oldAwaitPos;
	this.awaitIdentPos = oldAwaitIdentPos;
	return this.finishNode(node, "FunctionExpression");
};
pp$5.parseArrowExpression = function(node, params, isAsync, forInit) {
	var oldYieldPos = this.yieldPos, oldAwaitPos = this.awaitPos, oldAwaitIdentPos = this.awaitIdentPos;
	this.enterScope(functionFlags(isAsync, false) | SCOPE_ARROW);
	this.initFunction(node);
	if (this.options.ecmaVersion >= 8) node.async = !!isAsync;
	this.yieldPos = 0;
	this.awaitPos = 0;
	this.awaitIdentPos = 0;
	node.params = this.toAssignableList(params, true);
	this.parseFunctionBody(node, true, false, forInit);
	this.yieldPos = oldYieldPos;
	this.awaitPos = oldAwaitPos;
	this.awaitIdentPos = oldAwaitIdentPos;
	return this.finishNode(node, "ArrowFunctionExpression");
};
pp$5.parseFunctionBody = function(node, isArrowFunction, isMethod, forInit) {
	var isExpression = isArrowFunction && this.type !== types$1.braceL;
	var oldStrict = this.strict, useStrict = false;
	if (isExpression) {
		node.body = this.parseMaybeAssign(forInit);
		node.expression = true;
		this.checkParams(node, false);
	} else {
		var nonSimple = this.options.ecmaVersion >= 7 && !this.isSimpleParamList(node.params);
		if (!oldStrict || nonSimple) {
			useStrict = this.strictDirective(this.end);
			if (useStrict && nonSimple) this.raiseRecoverable(node.start, "Illegal 'use strict' directive in function with non-simple parameter list");
		}
		var oldLabels = this.labels;
		this.labels = [];
		if (useStrict) this.strict = true;
		this.checkParams(node, !oldStrict && !useStrict && !isArrowFunction && !isMethod && this.isSimpleParamList(node.params));
		if (this.strict && node.id) this.checkLValSimple(node.id, BIND_OUTSIDE);
		node.body = this.parseBlock(false, void 0, useStrict && !oldStrict);
		node.expression = false;
		this.adaptDirectivePrologue(node.body.body);
		this.labels = oldLabels;
	}
	this.exitScope();
};
pp$5.isSimpleParamList = function(params) {
	for (var i = 0, list = params; i < list.length; i += 1) if (list[i].type !== "Identifier") return false;
	return true;
};
pp$5.checkParams = function(node, allowDuplicates) {
	var nameHash = Object.create(null);
	for (var i = 0, list = node.params; i < list.length; i += 1) {
		var param = list[i];
		this.checkLValInnerPattern(param, BIND_VAR, allowDuplicates ? null : nameHash);
	}
};
pp$5.parseExprList = function(close, allowTrailingComma, allowEmpty, refDestructuringErrors) {
	var elts = [], first = true;
	while (!this.eat(close)) {
		if (!first) {
			this.expect(types$1.comma);
			if (allowTrailingComma && this.afterTrailingComma(close)) break;
		} else first = false;
		var elt = void 0;
		if (allowEmpty && this.type === types$1.comma) elt = null;
		else if (this.type === types$1.ellipsis) {
			elt = this.parseSpread(refDestructuringErrors);
			if (refDestructuringErrors && this.type === types$1.comma && refDestructuringErrors.trailingComma < 0) refDestructuringErrors.trailingComma = this.start;
		} else elt = this.parseMaybeAssign(false, refDestructuringErrors);
		elts.push(elt);
	}
	return elts;
};
pp$5.checkUnreserved = function(ref) {
	var start = ref.start;
	var end = ref.end;
	var name = ref.name;
	if (this.inGenerator && name === "yield") this.raiseRecoverable(start, "Cannot use 'yield' as identifier inside a generator");
	if (this.inAsync && name === "await") this.raiseRecoverable(start, "Cannot use 'await' as identifier inside an async function");
	if (!(this.currentThisScope().flags & SCOPE_VAR) && name === "arguments") this.raiseRecoverable(start, "Cannot use 'arguments' in class field initializer");
	if (this.inClassStaticBlock && (name === "arguments" || name === "await")) this.raise(start, "Cannot use " + name + " in class static initialization block");
	if (this.keywords.test(name)) this.raise(start, "Unexpected keyword '" + name + "'");
	if (this.options.ecmaVersion < 6 && this.input.slice(start, end).indexOf("\\") !== -1) return;
	if ((this.strict ? this.reservedWordsStrict : this.reservedWords).test(name)) {
		if (!this.inAsync && name === "await") this.raiseRecoverable(start, "Cannot use keyword 'await' outside an async function");
		this.raiseRecoverable(start, "The keyword '" + name + "' is reserved");
	}
};
pp$5.parseIdent = function(liberal) {
	var node = this.parseIdentNode();
	this.next(!!liberal);
	this.finishNode(node, "Identifier");
	if (!liberal) {
		this.checkUnreserved(node);
		if (node.name === "await" && !this.awaitIdentPos) this.awaitIdentPos = node.start;
	}
	return node;
};
pp$5.parseIdentNode = function() {
	var node = this.startNode();
	if (this.type === types$1.name) node.name = this.value;
	else if (this.type.keyword) {
		node.name = this.type.keyword;
		if ((node.name === "class" || node.name === "function") && (this.lastTokEnd !== this.lastTokStart + 1 || this.input.charCodeAt(this.lastTokStart) !== 46)) this.context.pop();
		this.type = types$1.name;
	} else this.unexpected();
	return node;
};
pp$5.parsePrivateIdent = function() {
	var node = this.startNode();
	if (this.type === types$1.privateId) node.name = this.value;
	else this.unexpected();
	this.next();
	this.finishNode(node, "PrivateIdentifier");
	if (this.options.checkPrivateFields) {
		if (this.privateNameStack.length === 0) this.raise(node.start, "Private field '#" + node.name + "' must be declared in an enclosing class");
		else this.privateNameStack[this.privateNameStack.length - 1].used.push(node);
	}
	return node;
};
pp$5.parseYield = function(forInit) {
	if (!this.yieldPos) this.yieldPos = this.start;
	var node = this.startNode();
	this.next();
	if (this.type === types$1.semi || this.canInsertSemicolon() || this.type !== types$1.star && !this.type.startsExpr) {
		node.delegate = false;
		node.argument = null;
	} else {
		node.delegate = this.eat(types$1.star);
		node.argument = this.parseMaybeAssign(forInit);
	}
	return this.finishNode(node, "YieldExpression");
};
pp$5.parseAwait = function(forInit) {
	if (!this.awaitPos) this.awaitPos = this.start;
	var node = this.startNode();
	this.next();
	node.argument = this.parseMaybeUnary(null, true, false, forInit);
	return this.finishNode(node, "AwaitExpression");
};
var pp$4 = Parser.prototype;
pp$4.raise = function(pos, message) {
	var loc = getLineInfo(this.input, pos);
	message += " (" + loc.line + ":" + loc.column + ")";
	if (this.sourceFile) message += " in " + this.sourceFile;
	var err = new SyntaxError(message);
	err.pos = pos;
	err.loc = loc;
	err.raisedAt = this.pos;
	throw err;
};
pp$4.raiseRecoverable = pp$4.raise;
pp$4.curPosition = function() {
	if (this.options.locations) return new Position(this.curLine, this.pos - this.lineStart);
};
var pp$3 = Parser.prototype;
var Scope = function Scope(flags) {
	this.flags = flags;
	this.var = [];
	this.lexical = [];
	this.functions = [];
};
pp$3.enterScope = function(flags) {
	this.scopeStack.push(new Scope(flags));
};
pp$3.exitScope = function() {
	this.scopeStack.pop();
};
pp$3.treatFunctionsAsVarInScope = function(scope) {
	return scope.flags & SCOPE_FUNCTION || !this.inModule && scope.flags & SCOPE_TOP;
};
pp$3.declareName = function(name, bindingType, pos) {
	var redeclared = false;
	if (bindingType === BIND_LEXICAL) {
		var scope = this.currentScope();
		redeclared = scope.lexical.indexOf(name) > -1 || scope.functions.indexOf(name) > -1 || scope.var.indexOf(name) > -1;
		scope.lexical.push(name);
		if (this.inModule && scope.flags & SCOPE_TOP) delete this.undefinedExports[name];
	} else if (bindingType === BIND_SIMPLE_CATCH) this.currentScope().lexical.push(name);
	else if (bindingType === BIND_FUNCTION) {
		var scope$2 = this.currentScope();
		if (this.treatFunctionsAsVar) redeclared = scope$2.lexical.indexOf(name) > -1;
		else redeclared = scope$2.lexical.indexOf(name) > -1 || scope$2.var.indexOf(name) > -1;
		scope$2.functions.push(name);
	} else for (var i = this.scopeStack.length - 1; i >= 0; --i) {
		var scope$3 = this.scopeStack[i];
		if (scope$3.lexical.indexOf(name) > -1 && !(scope$3.flags & SCOPE_SIMPLE_CATCH && scope$3.lexical[0] === name) || !this.treatFunctionsAsVarInScope(scope$3) && scope$3.functions.indexOf(name) > -1) {
			redeclared = true;
			break;
		}
		scope$3.var.push(name);
		if (this.inModule && scope$3.flags & SCOPE_TOP) delete this.undefinedExports[name];
		if (scope$3.flags & SCOPE_VAR) break;
	}
	if (redeclared) this.raiseRecoverable(pos, "Identifier '" + name + "' has already been declared");
};
pp$3.checkLocalExport = function(id) {
	if (this.scopeStack[0].lexical.indexOf(id.name) === -1 && this.scopeStack[0].var.indexOf(id.name) === -1) this.undefinedExports[id.name] = id;
};
pp$3.currentScope = function() {
	return this.scopeStack[this.scopeStack.length - 1];
};
pp$3.currentVarScope = function() {
	for (var i = this.scopeStack.length - 1;; i--) {
		var scope = this.scopeStack[i];
		if (scope.flags & (SCOPE_VAR | SCOPE_CLASS_FIELD_INIT | SCOPE_CLASS_STATIC_BLOCK)) return scope;
	}
};
pp$3.currentThisScope = function() {
	for (var i = this.scopeStack.length - 1;; i--) {
		var scope = this.scopeStack[i];
		if (scope.flags & (SCOPE_VAR | SCOPE_CLASS_FIELD_INIT | SCOPE_CLASS_STATIC_BLOCK) && !(scope.flags & SCOPE_ARROW)) return scope;
	}
};
var Node = function Node(parser, pos, loc) {
	this.type = "";
	this.start = pos;
	this.end = 0;
	if (parser.options.locations) this.loc = new SourceLocation(parser, loc);
	if (parser.options.directSourceFile) this.sourceFile = parser.options.directSourceFile;
	if (parser.options.ranges) this.range = [pos, 0];
};
var pp$2 = Parser.prototype;
pp$2.startNode = function() {
	return new Node(this, this.start, this.startLoc);
};
pp$2.startNodeAt = function(pos, loc) {
	return new Node(this, pos, loc);
};
function finishNodeAt(node, type, pos, loc) {
	node.type = type;
	node.end = pos;
	if (this.options.locations) node.loc.end = loc;
	if (this.options.ranges) node.range[1] = pos;
	return node;
}
pp$2.finishNode = function(node, type) {
	return finishNodeAt.call(this, node, type, this.lastTokEnd, this.lastTokEndLoc);
};
pp$2.finishNodeAt = function(node, type, pos, loc) {
	return finishNodeAt.call(this, node, type, pos, loc);
};
pp$2.copyNode = function(node) {
	var newNode = new Node(this, node.start, this.startLoc);
	for (var prop in node) newNode[prop] = node[prop];
	return newNode;
};
var scriptValuesAddedInUnicode = "Berf Beria_Erfe Gara Garay Gukh Gurung_Khema Hrkt Katakana_Or_Hiragana Kawi Kirat_Rai Krai Nag_Mundari Nagm Ol_Onal Onao Sidetic Sidt Sunu Sunuwar Tai_Yo Tayo Todhri Todr Tolong_Siki Tols Tulu_Tigalari Tutg Unknown Zzzz";
var ecma9BinaryProperties = "ASCII ASCII_Hex_Digit AHex Alphabetic Alpha Any Assigned Bidi_Control Bidi_C Bidi_Mirrored Bidi_M Case_Ignorable CI Cased Changes_When_Casefolded CWCF Changes_When_Casemapped CWCM Changes_When_Lowercased CWL Changes_When_NFKC_Casefolded CWKCF Changes_When_Titlecased CWT Changes_When_Uppercased CWU Dash Default_Ignorable_Code_Point DI Deprecated Dep Diacritic Dia Emoji Emoji_Component Emoji_Modifier Emoji_Modifier_Base Emoji_Presentation Extender Ext Grapheme_Base Gr_Base Grapheme_Extend Gr_Ext Hex_Digit Hex IDS_Binary_Operator IDSB IDS_Trinary_Operator IDST ID_Continue IDC ID_Start IDS Ideographic Ideo Join_Control Join_C Logical_Order_Exception LOE Lowercase Lower Math Noncharacter_Code_Point NChar Pattern_Syntax Pat_Syn Pattern_White_Space Pat_WS Quotation_Mark QMark Radical Regional_Indicator RI Sentence_Terminal STerm Soft_Dotted SD Terminal_Punctuation Term Unified_Ideograph UIdeo Uppercase Upper Variation_Selector VS White_Space space XID_Continue XIDC XID_Start XIDS";
var ecma10BinaryProperties = ecma9BinaryProperties + " Extended_Pictographic";
var ecma11BinaryProperties = ecma10BinaryProperties;
var ecma12BinaryProperties = ecma11BinaryProperties + " EBase EComp EMod EPres ExtPict";
var ecma13BinaryProperties = ecma12BinaryProperties;
var unicodeBinaryProperties = {
	9: ecma9BinaryProperties,
	10: ecma10BinaryProperties,
	11: ecma11BinaryProperties,
	12: ecma12BinaryProperties,
	13: ecma13BinaryProperties,
	14: ecma13BinaryProperties
};
var unicodeBinaryPropertiesOfStrings = {
	9: "",
	10: "",
	11: "",
	12: "",
	13: "",
	14: "Basic_Emoji Emoji_Keycap_Sequence RGI_Emoji_Modifier_Sequence RGI_Emoji_Flag_Sequence RGI_Emoji_Tag_Sequence RGI_Emoji_ZWJ_Sequence RGI_Emoji"
};
var unicodeGeneralCategoryValues = "Cased_Letter LC Close_Punctuation Pe Connector_Punctuation Pc Control Cc cntrl Currency_Symbol Sc Dash_Punctuation Pd Decimal_Number Nd digit Enclosing_Mark Me Final_Punctuation Pf Format Cf Initial_Punctuation Pi Letter L Letter_Number Nl Line_Separator Zl Lowercase_Letter Ll Mark M Combining_Mark Math_Symbol Sm Modifier_Letter Lm Modifier_Symbol Sk Nonspacing_Mark Mn Number N Open_Punctuation Ps Other C Other_Letter Lo Other_Number No Other_Punctuation Po Other_Symbol So Paragraph_Separator Zp Private_Use Co Punctuation P punct Separator Z Space_Separator Zs Spacing_Mark Mc Surrogate Cs Symbol S Titlecase_Letter Lt Unassigned Cn Uppercase_Letter Lu";
var ecma9ScriptValues = "Adlam Adlm Ahom Anatolian_Hieroglyphs Hluw Arabic Arab Armenian Armn Avestan Avst Balinese Bali Bamum Bamu Bassa_Vah Bass Batak Batk Bengali Beng Bhaiksuki Bhks Bopomofo Bopo Brahmi Brah Braille Brai Buginese Bugi Buhid Buhd Canadian_Aboriginal Cans Carian Cari Caucasian_Albanian Aghb Chakma Cakm Cham Cham Cherokee Cher Common Zyyy Coptic Copt Qaac Cuneiform Xsux Cypriot Cprt Cyrillic Cyrl Deseret Dsrt Devanagari Deva Duployan Dupl Egyptian_Hieroglyphs Egyp Elbasan Elba Ethiopic Ethi Georgian Geor Glagolitic Glag Gothic Goth Grantha Gran Greek Grek Gujarati Gujr Gurmukhi Guru Han Hani Hangul Hang Hanunoo Hano Hatran Hatr Hebrew Hebr Hiragana Hira Imperial_Aramaic Armi Inherited Zinh Qaai Inscriptional_Pahlavi Phli Inscriptional_Parthian Prti Javanese Java Kaithi Kthi Kannada Knda Katakana Kana Kayah_Li Kali Kharoshthi Khar Khmer Khmr Khojki Khoj Khudawadi Sind Lao Laoo Latin Latn Lepcha Lepc Limbu Limb Linear_A Lina Linear_B Linb Lisu Lisu Lycian Lyci Lydian Lydi Mahajani Mahj Malayalam Mlym Mandaic Mand Manichaean Mani Marchen Marc Masaram_Gondi Gonm Meetei_Mayek Mtei Mende_Kikakui Mend Meroitic_Cursive Merc Meroitic_Hieroglyphs Mero Miao Plrd Modi Mongolian Mong Mro Mroo Multani Mult Myanmar Mymr Nabataean Nbat New_Tai_Lue Talu Newa Newa Nko Nkoo Nushu Nshu Ogham Ogam Ol_Chiki Olck Old_Hungarian Hung Old_Italic Ital Old_North_Arabian Narb Old_Permic Perm Old_Persian Xpeo Old_South_Arabian Sarb Old_Turkic Orkh Oriya Orya Osage Osge Osmanya Osma Pahawh_Hmong Hmng Palmyrene Palm Pau_Cin_Hau Pauc Phags_Pa Phag Phoenician Phnx Psalter_Pahlavi Phlp Rejang Rjng Runic Runr Samaritan Samr Saurashtra Saur Sharada Shrd Shavian Shaw Siddham Sidd SignWriting Sgnw Sinhala Sinh Sora_Sompeng Sora Soyombo Soyo Sundanese Sund Syloti_Nagri Sylo Syriac Syrc Tagalog Tglg Tagbanwa Tagb Tai_Le Tale Tai_Tham Lana Tai_Viet Tavt Takri Takr Tamil Taml Tangut Tang Telugu Telu Thaana Thaa Thai Thai Tibetan Tibt Tifinagh Tfng Tirhuta Tirh Ugaritic Ugar Vai Vaii Warang_Citi Wara Yi Yiii Zanabazar_Square Zanb";
var ecma10ScriptValues = ecma9ScriptValues + " Dogra Dogr Gunjala_Gondi Gong Hanifi_Rohingya Rohg Makasar Maka Medefaidrin Medf Old_Sogdian Sogo Sogdian Sogd";
var ecma11ScriptValues = ecma10ScriptValues + " Elymaic Elym Nandinagari Nand Nyiakeng_Puachue_Hmong Hmnp Wancho Wcho";
var ecma12ScriptValues = ecma11ScriptValues + " Chorasmian Chrs Diak Dives_Akuru Khitan_Small_Script Kits Yezi Yezidi";
var ecma13ScriptValues = ecma12ScriptValues + " Cypro_Minoan Cpmn Old_Uyghur Ougr Tangsa Tnsa Toto Vithkuqi Vith";
var unicodeScriptValues = {
	9: ecma9ScriptValues,
	10: ecma10ScriptValues,
	11: ecma11ScriptValues,
	12: ecma12ScriptValues,
	13: ecma13ScriptValues,
	14: ecma13ScriptValues + " " + scriptValuesAddedInUnicode
};
var data$1 = {};
function buildUnicodeData(ecmaVersion) {
	var d = data$1[ecmaVersion] = {
		binary: wordsRegexp(unicodeBinaryProperties[ecmaVersion] + " " + unicodeGeneralCategoryValues),
		binaryOfStrings: wordsRegexp(unicodeBinaryPropertiesOfStrings[ecmaVersion]),
		nonBinary: {
			General_Category: wordsRegexp(unicodeGeneralCategoryValues),
			Script: wordsRegexp(unicodeScriptValues[ecmaVersion])
		}
	};
	d.nonBinary.Script_Extensions = d.nonBinary.Script;
	d.nonBinary.gc = d.nonBinary.General_Category;
	d.nonBinary.sc = d.nonBinary.Script;
	d.nonBinary.scx = d.nonBinary.Script_Extensions;
}
for (var i = 0, list = [
	9,
	10,
	11,
	12,
	13,
	14
]; i < list.length; i += 1) {
	var ecmaVersion = list[i];
	buildUnicodeData(ecmaVersion);
}
var pp$1 = Parser.prototype;
var BranchID = function BranchID(parent, base) {
	this.parent = parent;
	this.base = base || this;
};
BranchID.prototype.separatedFrom = function separatedFrom(alt) {
	for (var self = this; self; self = self.parent) for (var other = alt; other; other = other.parent) if (self.base === other.base && self !== other) return true;
	return false;
};
BranchID.prototype.sibling = function sibling() {
	return new BranchID(this.parent, this.base);
};
var RegExpValidationState = function RegExpValidationState(parser) {
	this.parser = parser;
	this.validFlags = "gim" + (parser.options.ecmaVersion >= 6 ? "uy" : "") + (parser.options.ecmaVersion >= 9 ? "s" : "") + (parser.options.ecmaVersion >= 13 ? "d" : "") + (parser.options.ecmaVersion >= 15 ? "v" : "");
	this.unicodeProperties = data$1[parser.options.ecmaVersion >= 14 ? 14 : parser.options.ecmaVersion];
	this.source = "";
	this.flags = "";
	this.start = 0;
	this.switchU = false;
	this.switchV = false;
	this.switchN = false;
	this.pos = 0;
	this.lastIntValue = 0;
	this.lastStringValue = "";
	this.lastAssertionIsQuantifiable = false;
	this.numCapturingParens = 0;
	this.maxBackReference = 0;
	this.groupNames = Object.create(null);
	this.backReferenceNames = [];
	this.branchID = null;
};
RegExpValidationState.prototype.reset = function reset(start, pattern, flags) {
	var unicodeSets = flags.indexOf("v") !== -1;
	var unicode = flags.indexOf("u") !== -1;
	this.start = start | 0;
	this.source = pattern + "";
	this.flags = flags;
	if (unicodeSets && this.parser.options.ecmaVersion >= 15) {
		this.switchU = true;
		this.switchV = true;
		this.switchN = true;
	} else {
		this.switchU = unicode && this.parser.options.ecmaVersion >= 6;
		this.switchV = false;
		this.switchN = unicode && this.parser.options.ecmaVersion >= 9;
	}
};
RegExpValidationState.prototype.raise = function raise(message) {
	this.parser.raiseRecoverable(this.start, "Invalid regular expression: /" + this.source + "/: " + message);
};
RegExpValidationState.prototype.at = function at(i, forceU) {
	if (forceU === void 0) forceU = false;
	var s = this.source;
	var l = s.length;
	if (i >= l) return -1;
	var c = s.charCodeAt(i);
	if (!(forceU || this.switchU) || c <= 55295 || c >= 57344 || i + 1 >= l) return c;
	var next = s.charCodeAt(i + 1);
	return next >= 56320 && next <= 57343 ? (c << 10) + next - 56613888 : c;
};
RegExpValidationState.prototype.nextIndex = function nextIndex(i, forceU) {
	if (forceU === void 0) forceU = false;
	var s = this.source;
	var l = s.length;
	if (i >= l) return l;
	var c = s.charCodeAt(i), next;
	if (!(forceU || this.switchU) || c <= 55295 || c >= 57344 || i + 1 >= l || (next = s.charCodeAt(i + 1)) < 56320 || next > 57343) return i + 1;
	return i + 2;
};
RegExpValidationState.prototype.current = function current(forceU) {
	if (forceU === void 0) forceU = false;
	return this.at(this.pos, forceU);
};
RegExpValidationState.prototype.lookahead = function lookahead(forceU) {
	if (forceU === void 0) forceU = false;
	return this.at(this.nextIndex(this.pos, forceU), forceU);
};
RegExpValidationState.prototype.advance = function advance(forceU) {
	if (forceU === void 0) forceU = false;
	this.pos = this.nextIndex(this.pos, forceU);
};
RegExpValidationState.prototype.eat = function eat(ch, forceU) {
	if (forceU === void 0) forceU = false;
	if (this.current(forceU) === ch) {
		this.advance(forceU);
		return true;
	}
	return false;
};
RegExpValidationState.prototype.eatChars = function eatChars(chs, forceU) {
	if (forceU === void 0) forceU = false;
	var pos = this.pos;
	for (var i = 0, list = chs; i < list.length; i += 1) {
		var ch = list[i];
		var current = this.at(pos, forceU);
		if (current === -1 || current !== ch) return false;
		pos = this.nextIndex(pos, forceU);
	}
	this.pos = pos;
	return true;
};
/**
* Validate the flags part of a given RegExpLiteral.
*
* @param {RegExpValidationState} state The state to validate RegExp.
* @returns {void}
*/
pp$1.validateRegExpFlags = function(state) {
	var validFlags = state.validFlags;
	var flags = state.flags;
	var u = false;
	var v = false;
	for (var i = 0; i < flags.length; i++) {
		var flag = flags.charAt(i);
		if (validFlags.indexOf(flag) === -1) this.raise(state.start, "Invalid regular expression flag");
		if (flags.indexOf(flag, i + 1) > -1) this.raise(state.start, "Duplicate regular expression flag");
		if (flag === "u") u = true;
		if (flag === "v") v = true;
	}
	if (this.options.ecmaVersion >= 15 && u && v) this.raise(state.start, "Invalid regular expression flag");
};
function hasProp(obj) {
	for (var _ in obj) return true;
	return false;
}
/**
* Validate the pattern part of a given RegExpLiteral.
*
* @param {RegExpValidationState} state The state to validate RegExp.
* @returns {void}
*/
pp$1.validateRegExpPattern = function(state) {
	this.regexp_pattern(state);
	if (!state.switchN && this.options.ecmaVersion >= 9 && hasProp(state.groupNames)) {
		state.switchN = true;
		this.regexp_pattern(state);
	}
};
pp$1.regexp_pattern = function(state) {
	state.pos = 0;
	state.lastIntValue = 0;
	state.lastStringValue = "";
	state.lastAssertionIsQuantifiable = false;
	state.numCapturingParens = 0;
	state.maxBackReference = 0;
	state.groupNames = Object.create(null);
	state.backReferenceNames.length = 0;
	state.branchID = null;
	this.regexp_disjunction(state);
	if (state.pos !== state.source.length) {
		if (state.eat(41)) state.raise("Unmatched ')'");
		if (state.eat(93) || state.eat(125)) state.raise("Lone quantifier brackets");
	}
	if (state.maxBackReference > state.numCapturingParens) state.raise("Invalid escape");
	for (var i = 0, list = state.backReferenceNames; i < list.length; i += 1) {
		var name = list[i];
		if (!state.groupNames[name]) state.raise("Invalid named capture referenced");
	}
};
pp$1.regexp_disjunction = function(state) {
	var trackDisjunction = this.options.ecmaVersion >= 16;
	if (trackDisjunction) state.branchID = new BranchID(state.branchID, null);
	this.regexp_alternative(state);
	while (state.eat(124)) {
		if (trackDisjunction) state.branchID = state.branchID.sibling();
		this.regexp_alternative(state);
	}
	if (trackDisjunction) state.branchID = state.branchID.parent;
	if (this.regexp_eatQuantifier(state, true)) state.raise("Nothing to repeat");
	if (state.eat(123)) state.raise("Lone quantifier brackets");
};
pp$1.regexp_alternative = function(state) {
	while (state.pos < state.source.length && this.regexp_eatTerm(state));
};
pp$1.regexp_eatTerm = function(state) {
	if (this.regexp_eatAssertion(state)) {
		if (state.lastAssertionIsQuantifiable && this.regexp_eatQuantifier(state)) {
			if (state.switchU) state.raise("Invalid quantifier");
		}
		return true;
	}
	if (state.switchU ? this.regexp_eatAtom(state) : this.regexp_eatExtendedAtom(state)) {
		this.regexp_eatQuantifier(state);
		return true;
	}
	return false;
};
pp$1.regexp_eatAssertion = function(state) {
	var start = state.pos;
	state.lastAssertionIsQuantifiable = false;
	if (state.eat(94) || state.eat(36)) return true;
	if (state.eat(92)) {
		if (state.eat(66) || state.eat(98)) return true;
		state.pos = start;
	}
	if (state.eat(40) && state.eat(63)) {
		var lookbehind = false;
		if (this.options.ecmaVersion >= 9) lookbehind = state.eat(60);
		if (state.eat(61) || state.eat(33)) {
			this.regexp_disjunction(state);
			if (!state.eat(41)) state.raise("Unterminated group");
			state.lastAssertionIsQuantifiable = !lookbehind;
			return true;
		}
	}
	state.pos = start;
	return false;
};
pp$1.regexp_eatQuantifier = function(state, noError) {
	if (noError === void 0) noError = false;
	if (this.regexp_eatQuantifierPrefix(state, noError)) {
		state.eat(63);
		return true;
	}
	return false;
};
pp$1.regexp_eatQuantifierPrefix = function(state, noError) {
	return state.eat(42) || state.eat(43) || state.eat(63) || this.regexp_eatBracedQuantifier(state, noError);
};
pp$1.regexp_eatBracedQuantifier = function(state, noError) {
	var start = state.pos;
	if (state.eat(123)) {
		var min = 0, max = -1;
		if (this.regexp_eatDecimalDigits(state)) {
			min = state.lastIntValue;
			if (state.eat(44) && this.regexp_eatDecimalDigits(state)) max = state.lastIntValue;
			if (state.eat(125)) {
				if (max !== -1 && max < min && !noError) state.raise("numbers out of order in {} quantifier");
				return true;
			}
		}
		if (state.switchU && !noError) state.raise("Incomplete quantifier");
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatAtom = function(state) {
	return this.regexp_eatPatternCharacters(state) || state.eat(46) || this.regexp_eatReverseSolidusAtomEscape(state) || this.regexp_eatCharacterClass(state) || this.regexp_eatUncapturingGroup(state) || this.regexp_eatCapturingGroup(state);
};
pp$1.regexp_eatReverseSolidusAtomEscape = function(state) {
	var start = state.pos;
	if (state.eat(92)) {
		if (this.regexp_eatAtomEscape(state)) return true;
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatUncapturingGroup = function(state) {
	var start = state.pos;
	if (state.eat(40)) {
		if (state.eat(63)) {
			if (this.options.ecmaVersion >= 16) {
				var addModifiers = this.regexp_eatModifiers(state);
				var hasHyphen = state.eat(45);
				if (addModifiers || hasHyphen) {
					for (var i = 0; i < addModifiers.length; i++) {
						var modifier = addModifiers.charAt(i);
						if (addModifiers.indexOf(modifier, i + 1) > -1) state.raise("Duplicate regular expression modifiers");
					}
					if (hasHyphen) {
						var removeModifiers = this.regexp_eatModifiers(state);
						if (!addModifiers && !removeModifiers && state.current() === 58) state.raise("Invalid regular expression modifiers");
						for (var i$1 = 0; i$1 < removeModifiers.length; i$1++) {
							var modifier$1 = removeModifiers.charAt(i$1);
							if (removeModifiers.indexOf(modifier$1, i$1 + 1) > -1 || addModifiers.indexOf(modifier$1) > -1) state.raise("Duplicate regular expression modifiers");
						}
					}
				}
			}
			if (state.eat(58)) {
				this.regexp_disjunction(state);
				if (state.eat(41)) return true;
				state.raise("Unterminated group");
			}
		}
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatCapturingGroup = function(state) {
	if (state.eat(40)) {
		if (this.options.ecmaVersion >= 9) this.regexp_groupSpecifier(state);
		else if (state.current() === 63) state.raise("Invalid group");
		this.regexp_disjunction(state);
		if (state.eat(41)) {
			state.numCapturingParens += 1;
			return true;
		}
		state.raise("Unterminated group");
	}
	return false;
};
pp$1.regexp_eatModifiers = function(state) {
	var modifiers = "";
	var ch = 0;
	while ((ch = state.current()) !== -1 && isRegularExpressionModifier(ch)) {
		modifiers += codePointToString(ch);
		state.advance();
	}
	return modifiers;
};
function isRegularExpressionModifier(ch) {
	return ch === 105 || ch === 109 || ch === 115;
}
pp$1.regexp_eatExtendedAtom = function(state) {
	return state.eat(46) || this.regexp_eatReverseSolidusAtomEscape(state) || this.regexp_eatCharacterClass(state) || this.regexp_eatUncapturingGroup(state) || this.regexp_eatCapturingGroup(state) || this.regexp_eatInvalidBracedQuantifier(state) || this.regexp_eatExtendedPatternCharacter(state);
};
pp$1.regexp_eatInvalidBracedQuantifier = function(state) {
	if (this.regexp_eatBracedQuantifier(state, true)) state.raise("Nothing to repeat");
	return false;
};
pp$1.regexp_eatSyntaxCharacter = function(state) {
	var ch = state.current();
	if (isSyntaxCharacter(ch)) {
		state.lastIntValue = ch;
		state.advance();
		return true;
	}
	return false;
};
function isSyntaxCharacter(ch) {
	return ch === 36 || ch >= 40 && ch <= 43 || ch === 46 || ch === 63 || ch >= 91 && ch <= 94 || ch >= 123 && ch <= 125;
}
pp$1.regexp_eatPatternCharacters = function(state) {
	var start = state.pos;
	var ch = 0;
	while ((ch = state.current()) !== -1 && !isSyntaxCharacter(ch)) state.advance();
	return state.pos !== start;
};
pp$1.regexp_eatExtendedPatternCharacter = function(state) {
	var ch = state.current();
	if (ch !== -1 && ch !== 36 && !(ch >= 40 && ch <= 43) && ch !== 46 && ch !== 63 && ch !== 91 && ch !== 94 && ch !== 124) {
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_groupSpecifier = function(state) {
	if (state.eat(63)) {
		if (!this.regexp_eatGroupName(state)) state.raise("Invalid group");
		var trackDisjunction = this.options.ecmaVersion >= 16;
		var known = state.groupNames[state.lastStringValue];
		if (known) {
			if (trackDisjunction) {
				for (var i = 0, list = known; i < list.length; i += 1) if (!list[i].separatedFrom(state.branchID)) state.raise("Duplicate capture group name");
			} else state.raise("Duplicate capture group name");
		}
		if (trackDisjunction) (known || (state.groupNames[state.lastStringValue] = [])).push(state.branchID);
		else state.groupNames[state.lastStringValue] = true;
	}
};
pp$1.regexp_eatGroupName = function(state) {
	state.lastStringValue = "";
	if (state.eat(60)) {
		if (this.regexp_eatRegExpIdentifierName(state) && state.eat(62)) return true;
		state.raise("Invalid capture group name");
	}
	return false;
};
pp$1.regexp_eatRegExpIdentifierName = function(state) {
	state.lastStringValue = "";
	if (this.regexp_eatRegExpIdentifierStart(state)) {
		state.lastStringValue += codePointToString(state.lastIntValue);
		while (this.regexp_eatRegExpIdentifierPart(state)) state.lastStringValue += codePointToString(state.lastIntValue);
		return true;
	}
	return false;
};
pp$1.regexp_eatRegExpIdentifierStart = function(state) {
	var start = state.pos;
	var forceU = this.options.ecmaVersion >= 11;
	var ch = state.current(forceU);
	state.advance(forceU);
	if (ch === 92 && this.regexp_eatRegExpUnicodeEscapeSequence(state, forceU)) ch = state.lastIntValue;
	if (isRegExpIdentifierStart(ch)) {
		state.lastIntValue = ch;
		return true;
	}
	state.pos = start;
	return false;
};
function isRegExpIdentifierStart(ch) {
	return isIdentifierStart(ch, true) || ch === 36 || ch === 95;
}
pp$1.regexp_eatRegExpIdentifierPart = function(state) {
	var start = state.pos;
	var forceU = this.options.ecmaVersion >= 11;
	var ch = state.current(forceU);
	state.advance(forceU);
	if (ch === 92 && this.regexp_eatRegExpUnicodeEscapeSequence(state, forceU)) ch = state.lastIntValue;
	if (isRegExpIdentifierPart(ch)) {
		state.lastIntValue = ch;
		return true;
	}
	state.pos = start;
	return false;
};
function isRegExpIdentifierPart(ch) {
	return isIdentifierChar(ch, true) || ch === 36 || ch === 95 || ch === 8204 || ch === 8205;
}
pp$1.regexp_eatAtomEscape = function(state) {
	if (this.regexp_eatBackReference(state) || this.regexp_eatCharacterClassEscape(state) || this.regexp_eatCharacterEscape(state) || state.switchN && this.regexp_eatKGroupName(state)) return true;
	if (state.switchU) {
		if (state.current() === 99) state.raise("Invalid unicode escape");
		state.raise("Invalid escape");
	}
	return false;
};
pp$1.regexp_eatBackReference = function(state) {
	var start = state.pos;
	if (this.regexp_eatDecimalEscape(state)) {
		var n = state.lastIntValue;
		if (state.switchU) {
			if (n > state.maxBackReference) state.maxBackReference = n;
			return true;
		}
		if (n <= state.numCapturingParens) return true;
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatKGroupName = function(state) {
	if (state.eat(107)) {
		if (this.regexp_eatGroupName(state)) {
			state.backReferenceNames.push(state.lastStringValue);
			return true;
		}
		state.raise("Invalid named reference");
	}
	return false;
};
pp$1.regexp_eatCharacterEscape = function(state) {
	return this.regexp_eatControlEscape(state) || this.regexp_eatCControlLetter(state) || this.regexp_eatZero(state) || this.regexp_eatHexEscapeSequence(state) || this.regexp_eatRegExpUnicodeEscapeSequence(state, false) || !state.switchU && this.regexp_eatLegacyOctalEscapeSequence(state) || this.regexp_eatIdentityEscape(state);
};
pp$1.regexp_eatCControlLetter = function(state) {
	var start = state.pos;
	if (state.eat(99)) {
		if (this.regexp_eatControlLetter(state)) return true;
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatZero = function(state) {
	if (state.current() === 48 && !isDecimalDigit(state.lookahead())) {
		state.lastIntValue = 0;
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_eatControlEscape = function(state) {
	var ch = state.current();
	if (ch === 116) {
		state.lastIntValue = 9;
		state.advance();
		return true;
	}
	if (ch === 110) {
		state.lastIntValue = 10;
		state.advance();
		return true;
	}
	if (ch === 118) {
		state.lastIntValue = 11;
		state.advance();
		return true;
	}
	if (ch === 102) {
		state.lastIntValue = 12;
		state.advance();
		return true;
	}
	if (ch === 114) {
		state.lastIntValue = 13;
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_eatControlLetter = function(state) {
	var ch = state.current();
	if (isControlLetter(ch)) {
		state.lastIntValue = ch % 32;
		state.advance();
		return true;
	}
	return false;
};
function isControlLetter(ch) {
	return ch >= 65 && ch <= 90 || ch >= 97 && ch <= 122;
}
pp$1.regexp_eatRegExpUnicodeEscapeSequence = function(state, forceU) {
	if (forceU === void 0) forceU = false;
	var start = state.pos;
	var switchU = forceU || state.switchU;
	if (state.eat(117)) {
		if (this.regexp_eatFixedHexDigits(state, 4)) {
			var lead = state.lastIntValue;
			if (switchU && lead >= 55296 && lead <= 56319) {
				var leadSurrogateEnd = state.pos;
				if (state.eat(92) && state.eat(117) && this.regexp_eatFixedHexDigits(state, 4)) {
					var trail = state.lastIntValue;
					if (trail >= 56320 && trail <= 57343) {
						state.lastIntValue = (lead - 55296) * 1024 + (trail - 56320) + 65536;
						return true;
					}
				}
				state.pos = leadSurrogateEnd;
				state.lastIntValue = lead;
			}
			return true;
		}
		if (switchU && state.eat(123) && this.regexp_eatHexDigits(state) && state.eat(125) && isValidUnicode(state.lastIntValue)) return true;
		if (switchU) state.raise("Invalid unicode escape");
		state.pos = start;
	}
	return false;
};
function isValidUnicode(ch) {
	return ch >= 0 && ch <= 1114111;
}
pp$1.regexp_eatIdentityEscape = function(state) {
	if (state.switchU) {
		if (this.regexp_eatSyntaxCharacter(state)) return true;
		if (state.eat(47)) {
			state.lastIntValue = 47;
			return true;
		}
		return false;
	}
	var ch = state.current();
	if (ch !== 99 && (!state.switchN || ch !== 107)) {
		state.lastIntValue = ch;
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_eatDecimalEscape = function(state) {
	state.lastIntValue = 0;
	var ch = state.current();
	if (ch >= 49 && ch <= 57) {
		do {
			state.lastIntValue = 10 * state.lastIntValue + (ch - 48);
			state.advance();
		} while ((ch = state.current()) >= 48 && ch <= 57);
		return true;
	}
	return false;
};
var CharSetNone = 0;
var CharSetOk = 1;
var CharSetString = 2;
pp$1.regexp_eatCharacterClassEscape = function(state) {
	var ch = state.current();
	if (isCharacterClassEscape(ch)) {
		state.lastIntValue = -1;
		state.advance();
		return CharSetOk;
	}
	var negate = false;
	if (state.switchU && this.options.ecmaVersion >= 9 && ((negate = ch === 80) || ch === 112)) {
		state.lastIntValue = -1;
		state.advance();
		var result;
		if (state.eat(123) && (result = this.regexp_eatUnicodePropertyValueExpression(state)) && state.eat(125)) {
			if (negate && result === CharSetString) state.raise("Invalid property name");
			return result;
		}
		state.raise("Invalid property name");
	}
	return CharSetNone;
};
function isCharacterClassEscape(ch) {
	return ch === 100 || ch === 68 || ch === 115 || ch === 83 || ch === 119 || ch === 87;
}
pp$1.regexp_eatUnicodePropertyValueExpression = function(state) {
	var start = state.pos;
	if (this.regexp_eatUnicodePropertyName(state) && state.eat(61)) {
		var name = state.lastStringValue;
		if (this.regexp_eatUnicodePropertyValue(state)) {
			var value = state.lastStringValue;
			this.regexp_validateUnicodePropertyNameAndValue(state, name, value);
			return CharSetOk;
		}
	}
	state.pos = start;
	if (this.regexp_eatLoneUnicodePropertyNameOrValue(state)) {
		var nameOrValue = state.lastStringValue;
		return this.regexp_validateUnicodePropertyNameOrValue(state, nameOrValue);
	}
	return CharSetNone;
};
pp$1.regexp_validateUnicodePropertyNameAndValue = function(state, name, value) {
	if (!hasOwn(state.unicodeProperties.nonBinary, name)) state.raise("Invalid property name");
	if (!state.unicodeProperties.nonBinary[name].test(value)) state.raise("Invalid property value");
};
pp$1.regexp_validateUnicodePropertyNameOrValue = function(state, nameOrValue) {
	if (state.unicodeProperties.binary.test(nameOrValue)) return CharSetOk;
	if (state.switchV && state.unicodeProperties.binaryOfStrings.test(nameOrValue)) return CharSetString;
	state.raise("Invalid property name");
};
pp$1.regexp_eatUnicodePropertyName = function(state) {
	var ch = 0;
	state.lastStringValue = "";
	while (isUnicodePropertyNameCharacter(ch = state.current())) {
		state.lastStringValue += codePointToString(ch);
		state.advance();
	}
	return state.lastStringValue !== "";
};
function isUnicodePropertyNameCharacter(ch) {
	return isControlLetter(ch) || ch === 95;
}
pp$1.regexp_eatUnicodePropertyValue = function(state) {
	var ch = 0;
	state.lastStringValue = "";
	while (isUnicodePropertyValueCharacter(ch = state.current())) {
		state.lastStringValue += codePointToString(ch);
		state.advance();
	}
	return state.lastStringValue !== "";
};
function isUnicodePropertyValueCharacter(ch) {
	return isUnicodePropertyNameCharacter(ch) || isDecimalDigit(ch);
}
pp$1.regexp_eatLoneUnicodePropertyNameOrValue = function(state) {
	return this.regexp_eatUnicodePropertyValue(state);
};
pp$1.regexp_eatCharacterClass = function(state) {
	if (state.eat(91)) {
		var negate = state.eat(94);
		var result = this.regexp_classContents(state);
		if (!state.eat(93)) state.raise("Unterminated character class");
		if (negate && result === CharSetString) state.raise("Negated character class may contain strings");
		return true;
	}
	return false;
};
pp$1.regexp_classContents = function(state) {
	if (state.current() === 93) return CharSetOk;
	if (state.switchV) return this.regexp_classSetExpression(state);
	this.regexp_nonEmptyClassRanges(state);
	return CharSetOk;
};
pp$1.regexp_nonEmptyClassRanges = function(state) {
	while (this.regexp_eatClassAtom(state)) {
		var left = state.lastIntValue;
		if (state.eat(45) && this.regexp_eatClassAtom(state)) {
			var right = state.lastIntValue;
			if (state.switchU && (left === -1 || right === -1)) state.raise("Invalid character class");
			if (left !== -1 && right !== -1 && left > right) state.raise("Range out of order in character class");
		}
	}
};
pp$1.regexp_eatClassAtom = function(state) {
	var start = state.pos;
	if (state.eat(92)) {
		if (this.regexp_eatClassEscape(state)) return true;
		if (state.switchU) {
			var ch$1 = state.current();
			if (ch$1 === 99 || isOctalDigit(ch$1)) state.raise("Invalid class escape");
			state.raise("Invalid escape");
		}
		state.pos = start;
	}
	var ch = state.current();
	if (ch !== 93) {
		state.lastIntValue = ch;
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_eatClassEscape = function(state) {
	var start = state.pos;
	if (state.eat(98)) {
		state.lastIntValue = 8;
		return true;
	}
	if (state.switchU && state.eat(45)) {
		state.lastIntValue = 45;
		return true;
	}
	if (!state.switchU && state.eat(99)) {
		if (this.regexp_eatClassControlLetter(state)) return true;
		state.pos = start;
	}
	return this.regexp_eatCharacterClassEscape(state) || this.regexp_eatCharacterEscape(state);
};
pp$1.regexp_classSetExpression = function(state) {
	var result = CharSetOk, subResult;
	if (this.regexp_eatClassSetRange(state));
	else if (subResult = this.regexp_eatClassSetOperand(state)) {
		if (subResult === CharSetString) result = CharSetString;
		var start = state.pos;
		while (state.eatChars([38, 38])) {
			if (state.current() !== 38 && (subResult = this.regexp_eatClassSetOperand(state))) {
				if (subResult !== CharSetString) result = CharSetOk;
				continue;
			}
			state.raise("Invalid character in character class");
		}
		if (start !== state.pos) return result;
		while (state.eatChars([45, 45])) {
			if (this.regexp_eatClassSetOperand(state)) continue;
			state.raise("Invalid character in character class");
		}
		if (start !== state.pos) return result;
	} else state.raise("Invalid character in character class");
	for (;;) {
		if (this.regexp_eatClassSetRange(state)) continue;
		subResult = this.regexp_eatClassSetOperand(state);
		if (!subResult) return result;
		if (subResult === CharSetString) result = CharSetString;
	}
};
pp$1.regexp_eatClassSetRange = function(state) {
	var start = state.pos;
	if (this.regexp_eatClassSetCharacter(state)) {
		var left = state.lastIntValue;
		if (state.eat(45) && this.regexp_eatClassSetCharacter(state)) {
			var right = state.lastIntValue;
			if (left !== -1 && right !== -1 && left > right) state.raise("Range out of order in character class");
			return true;
		}
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatClassSetOperand = function(state) {
	if (this.regexp_eatClassSetCharacter(state)) return CharSetOk;
	return this.regexp_eatClassStringDisjunction(state) || this.regexp_eatNestedClass(state);
};
pp$1.regexp_eatNestedClass = function(state) {
	var start = state.pos;
	if (state.eat(91)) {
		var negate = state.eat(94);
		var result = this.regexp_classContents(state);
		if (state.eat(93)) {
			if (negate && result === CharSetString) state.raise("Negated character class may contain strings");
			return result;
		}
		state.pos = start;
	}
	if (state.eat(92)) {
		var result$1 = this.regexp_eatCharacterClassEscape(state);
		if (result$1) return result$1;
		state.pos = start;
	}
	return null;
};
pp$1.regexp_eatClassStringDisjunction = function(state) {
	var start = state.pos;
	if (state.eatChars([92, 113])) {
		if (state.eat(123)) {
			var result = this.regexp_classStringDisjunctionContents(state);
			if (state.eat(125)) return result;
		} else state.raise("Invalid escape");
		state.pos = start;
	}
	return null;
};
pp$1.regexp_classStringDisjunctionContents = function(state) {
	var result = this.regexp_classString(state);
	while (state.eat(124)) if (this.regexp_classString(state) === CharSetString) result = CharSetString;
	return result;
};
pp$1.regexp_classString = function(state) {
	var count = 0;
	while (this.regexp_eatClassSetCharacter(state)) count++;
	return count === 1 ? CharSetOk : CharSetString;
};
pp$1.regexp_eatClassSetCharacter = function(state) {
	var start = state.pos;
	if (state.eat(92)) {
		if (this.regexp_eatCharacterEscape(state) || this.regexp_eatClassSetReservedPunctuator(state)) return true;
		if (state.eat(98)) {
			state.lastIntValue = 8;
			return true;
		}
		state.pos = start;
		return false;
	}
	var ch = state.current();
	if (ch < 0 || ch === state.lookahead() && isClassSetReservedDoublePunctuatorCharacter(ch)) return false;
	if (isClassSetSyntaxCharacter(ch)) return false;
	state.advance();
	state.lastIntValue = ch;
	return true;
};
function isClassSetReservedDoublePunctuatorCharacter(ch) {
	return ch === 33 || ch >= 35 && ch <= 38 || ch >= 42 && ch <= 44 || ch === 46 || ch >= 58 && ch <= 64 || ch === 94 || ch === 96 || ch === 126;
}
function isClassSetSyntaxCharacter(ch) {
	return ch === 40 || ch === 41 || ch === 45 || ch === 47 || ch >= 91 && ch <= 93 || ch >= 123 && ch <= 125;
}
pp$1.regexp_eatClassSetReservedPunctuator = function(state) {
	var ch = state.current();
	if (isClassSetReservedPunctuator(ch)) {
		state.lastIntValue = ch;
		state.advance();
		return true;
	}
	return false;
};
function isClassSetReservedPunctuator(ch) {
	return ch === 33 || ch === 35 || ch === 37 || ch === 38 || ch === 44 || ch === 45 || ch >= 58 && ch <= 62 || ch === 64 || ch === 96 || ch === 126;
}
pp$1.regexp_eatClassControlLetter = function(state) {
	var ch = state.current();
	if (isDecimalDigit(ch) || ch === 95) {
		state.lastIntValue = ch % 32;
		state.advance();
		return true;
	}
	return false;
};
pp$1.regexp_eatHexEscapeSequence = function(state) {
	var start = state.pos;
	if (state.eat(120)) {
		if (this.regexp_eatFixedHexDigits(state, 2)) return true;
		if (state.switchU) state.raise("Invalid escape");
		state.pos = start;
	}
	return false;
};
pp$1.regexp_eatDecimalDigits = function(state) {
	var start = state.pos;
	var ch = 0;
	state.lastIntValue = 0;
	while (isDecimalDigit(ch = state.current())) {
		state.lastIntValue = 10 * state.lastIntValue + (ch - 48);
		state.advance();
	}
	return state.pos !== start;
};
function isDecimalDigit(ch) {
	return ch >= 48 && ch <= 57;
}
pp$1.regexp_eatHexDigits = function(state) {
	var start = state.pos;
	var ch = 0;
	state.lastIntValue = 0;
	while (isHexDigit(ch = state.current())) {
		state.lastIntValue = 16 * state.lastIntValue + hexToInt(ch);
		state.advance();
	}
	return state.pos !== start;
};
function isHexDigit(ch) {
	return ch >= 48 && ch <= 57 || ch >= 65 && ch <= 70 || ch >= 97 && ch <= 102;
}
function hexToInt(ch) {
	if (ch >= 65 && ch <= 70) return 10 + (ch - 65);
	if (ch >= 97 && ch <= 102) return 10 + (ch - 97);
	return ch - 48;
}
pp$1.regexp_eatLegacyOctalEscapeSequence = function(state) {
	if (this.regexp_eatOctalDigit(state)) {
		var n1 = state.lastIntValue;
		if (this.regexp_eatOctalDigit(state)) {
			var n2 = state.lastIntValue;
			if (n1 <= 3 && this.regexp_eatOctalDigit(state)) state.lastIntValue = n1 * 64 + n2 * 8 + state.lastIntValue;
			else state.lastIntValue = n1 * 8 + n2;
		} else state.lastIntValue = n1;
		return true;
	}
	return false;
};
pp$1.regexp_eatOctalDigit = function(state) {
	var ch = state.current();
	if (isOctalDigit(ch)) {
		state.lastIntValue = ch - 48;
		state.advance();
		return true;
	}
	state.lastIntValue = 0;
	return false;
};
function isOctalDigit(ch) {
	return ch >= 48 && ch <= 55;
}
pp$1.regexp_eatFixedHexDigits = function(state, length) {
	var start = state.pos;
	state.lastIntValue = 0;
	for (var i = 0; i < length; ++i) {
		var ch = state.current();
		if (!isHexDigit(ch)) {
			state.pos = start;
			return false;
		}
		state.lastIntValue = 16 * state.lastIntValue + hexToInt(ch);
		state.advance();
	}
	return true;
};
var Token = function Token(p) {
	this.type = p.type;
	this.value = p.value;
	this.start = p.start;
	this.end = p.end;
	if (p.options.locations) this.loc = new SourceLocation(p, p.startLoc, p.endLoc);
	if (p.options.ranges) this.range = [p.start, p.end];
};
var pp = Parser.prototype;
pp.next = function(ignoreEscapeSequenceInKeyword) {
	if (!ignoreEscapeSequenceInKeyword && this.type.keyword && this.containsEsc) this.raiseRecoverable(this.start, "Escape sequence in keyword " + this.type.keyword);
	if (this.options.onToken) this.options.onToken(new Token(this));
	this.lastTokEnd = this.end;
	this.lastTokStart = this.start;
	this.lastTokEndLoc = this.endLoc;
	this.lastTokStartLoc = this.startLoc;
	this.nextToken();
};
pp.getToken = function() {
	this.next();
	return new Token(this);
};
if (typeof Symbol !== "undefined") pp[Symbol.iterator] = function() {
	var this$1$1 = this;
	return { next: function() {
		var token = this$1$1.getToken();
		return {
			done: token.type === types$1.eof,
			value: token
		};
	} };
};
pp.nextToken = function() {
	var curContext = this.curContext();
	if (!curContext || !curContext.preserveSpace) this.skipSpace();
	this.start = this.pos;
	if (this.options.locations) this.startLoc = this.curPosition();
	if (this.pos >= this.input.length) return this.finishToken(types$1.eof);
	if (curContext.override) return curContext.override(this);
	else this.readToken(this.fullCharCodeAtPos());
};
pp.readToken = function(code) {
	if (isIdentifierStart(code, this.options.ecmaVersion >= 6) || code === 92) return this.readWord();
	return this.getTokenFromCode(code);
};
pp.fullCharCodeAt = function(pos) {
	var code = this.input.charCodeAt(pos);
	if (code <= 55295 || code >= 56320) return code;
	var next = this.input.charCodeAt(pos + 1);
	return next <= 56319 || next >= 57344 ? code : (code << 10) + next - 56613888;
};
pp.fullCharCodeAtPos = function() {
	return this.fullCharCodeAt(this.pos);
};
pp.skipBlockComment = function() {
	var startLoc = this.options.onComment && this.curPosition();
	var start = this.pos, end = this.input.indexOf("*/", this.pos += 2);
	if (end === -1) this.raise(this.pos - 2, "Unterminated comment");
	this.pos = end + 2;
	if (this.options.locations) for (var nextBreak = void 0, pos = start; (nextBreak = nextLineBreak(this.input, pos, this.pos)) > -1;) {
		++this.curLine;
		pos = this.lineStart = nextBreak;
	}
	if (this.options.onComment) this.options.onComment(true, this.input.slice(start + 2, end), start, this.pos, startLoc, this.curPosition());
};
pp.skipLineComment = function(startSkip) {
	var start = this.pos;
	var startLoc = this.options.onComment && this.curPosition();
	var ch = this.input.charCodeAt(this.pos += startSkip);
	while (this.pos < this.input.length && !isNewLine(ch)) ch = this.input.charCodeAt(++this.pos);
	if (this.options.onComment) this.options.onComment(false, this.input.slice(start + startSkip, this.pos), start, this.pos, startLoc, this.curPosition());
};
pp.skipSpace = function() {
	loop: while (this.pos < this.input.length) {
		var ch = this.input.charCodeAt(this.pos);
		switch (ch) {
			case 32:
			case 160:
				++this.pos;
				break;
			case 13: if (this.input.charCodeAt(this.pos + 1) === 10) ++this.pos;
			case 10:
			case 8232:
			case 8233:
				++this.pos;
				if (this.options.locations) {
					++this.curLine;
					this.lineStart = this.pos;
				}
				break;
			case 47:
				switch (this.input.charCodeAt(this.pos + 1)) {
					case 42:
						this.skipBlockComment();
						break;
					case 47:
						this.skipLineComment(2);
						break;
					default: break loop;
				}
				break;
			default: if (ch > 8 && ch < 14 || ch >= 5760 && nonASCIIwhitespace.test(String.fromCharCode(ch))) ++this.pos;
			else break loop;
		}
	}
};
pp.finishToken = function(type, val) {
	this.end = this.pos;
	if (this.options.locations) this.endLoc = this.curPosition();
	var prevType = this.type;
	this.type = type;
	this.value = val;
	this.updateContext(prevType);
};
pp.readToken_dot = function() {
	var next = this.input.charCodeAt(this.pos + 1);
	if (next >= 48 && next <= 57) return this.readNumber(true);
	var next2 = this.input.charCodeAt(this.pos + 2);
	if (this.options.ecmaVersion >= 6 && next === 46 && next2 === 46) {
		this.pos += 3;
		return this.finishToken(types$1.ellipsis);
	} else {
		++this.pos;
		return this.finishToken(types$1.dot);
	}
};
pp.readToken_slash = function() {
	var next = this.input.charCodeAt(this.pos + 1);
	if (this.exprAllowed) {
		++this.pos;
		return this.readRegexp();
	}
	if (next === 61) return this.finishOp(types$1.assign, 2);
	return this.finishOp(types$1.slash, 1);
};
pp.readToken_mult_modulo_exp = function(code) {
	var next = this.input.charCodeAt(this.pos + 1);
	var size = 1;
	var tokentype = code === 42 ? types$1.star : types$1.modulo;
	if (this.options.ecmaVersion >= 7 && code === 42 && next === 42) {
		++size;
		tokentype = types$1.starstar;
		next = this.input.charCodeAt(this.pos + 2);
	}
	if (next === 61) return this.finishOp(types$1.assign, size + 1);
	return this.finishOp(tokentype, size);
};
pp.readToken_pipe_amp = function(code) {
	var next = this.input.charCodeAt(this.pos + 1);
	if (next === code) {
		if (this.options.ecmaVersion >= 12) {
			if (this.input.charCodeAt(this.pos + 2) === 61) return this.finishOp(types$1.assign, 3);
		}
		return this.finishOp(code === 124 ? types$1.logicalOR : types$1.logicalAND, 2);
	}
	if (next === 61) return this.finishOp(types$1.assign, 2);
	return this.finishOp(code === 124 ? types$1.bitwiseOR : types$1.bitwiseAND, 1);
};
pp.readToken_caret = function() {
	if (this.input.charCodeAt(this.pos + 1) === 61) return this.finishOp(types$1.assign, 2);
	return this.finishOp(types$1.bitwiseXOR, 1);
};
pp.readToken_plus_min = function(code) {
	var next = this.input.charCodeAt(this.pos + 1);
	if (next === code) {
		if (next === 45 && !this.inModule && this.input.charCodeAt(this.pos + 2) === 62 && (this.lastTokEnd === 0 || lineBreak.test(this.input.slice(this.lastTokEnd, this.pos)))) {
			this.skipLineComment(3);
			this.skipSpace();
			return this.nextToken();
		}
		return this.finishOp(types$1.incDec, 2);
	}
	if (next === 61) return this.finishOp(types$1.assign, 2);
	return this.finishOp(types$1.plusMin, 1);
};
pp.readToken_lt_gt = function(code) {
	var next = this.input.charCodeAt(this.pos + 1);
	var size = 1;
	if (next === code) {
		size = code === 62 && this.input.charCodeAt(this.pos + 2) === 62 ? 3 : 2;
		if (this.input.charCodeAt(this.pos + size) === 61) return this.finishOp(types$1.assign, size + 1);
		return this.finishOp(types$1.bitShift, size);
	}
	if (next === 33 && code === 60 && !this.inModule && this.input.charCodeAt(this.pos + 2) === 45 && this.input.charCodeAt(this.pos + 3) === 45) {
		this.skipLineComment(4);
		this.skipSpace();
		return this.nextToken();
	}
	if (next === 61) size = 2;
	return this.finishOp(types$1.relational, size);
};
pp.readToken_eq_excl = function(code) {
	var next = this.input.charCodeAt(this.pos + 1);
	if (next === 61) return this.finishOp(types$1.equality, this.input.charCodeAt(this.pos + 2) === 61 ? 3 : 2);
	if (code === 61 && next === 62 && this.options.ecmaVersion >= 6) {
		this.pos += 2;
		return this.finishToken(types$1.arrow);
	}
	return this.finishOp(code === 61 ? types$1.eq : types$1.prefix, 1);
};
pp.readToken_question = function() {
	var ecmaVersion = this.options.ecmaVersion;
	if (ecmaVersion >= 11) {
		var next = this.input.charCodeAt(this.pos + 1);
		if (next === 46) {
			var next2 = this.input.charCodeAt(this.pos + 2);
			if (next2 < 48 || next2 > 57) return this.finishOp(types$1.questionDot, 2);
		}
		if (next === 63) {
			if (ecmaVersion >= 12) {
				if (this.input.charCodeAt(this.pos + 2) === 61) return this.finishOp(types$1.assign, 3);
			}
			return this.finishOp(types$1.coalesce, 2);
		}
	}
	return this.finishOp(types$1.question, 1);
};
pp.readToken_numberSign = function() {
	var ecmaVersion = this.options.ecmaVersion;
	var code = 35;
	if (ecmaVersion >= 13) {
		++this.pos;
		code = this.fullCharCodeAtPos();
		if (isIdentifierStart(code, true) || code === 92) return this.finishToken(types$1.privateId, this.readWord1());
	}
	this.raise(this.pos, "Unexpected character '" + codePointToString(code) + "'");
};
pp.getTokenFromCode = function(code) {
	switch (code) {
		case 46: return this.readToken_dot();
		case 40:
			++this.pos;
			return this.finishToken(types$1.parenL);
		case 41:
			++this.pos;
			return this.finishToken(types$1.parenR);
		case 59:
			++this.pos;
			return this.finishToken(types$1.semi);
		case 44:
			++this.pos;
			return this.finishToken(types$1.comma);
		case 91:
			++this.pos;
			return this.finishToken(types$1.bracketL);
		case 93:
			++this.pos;
			return this.finishToken(types$1.bracketR);
		case 123:
			++this.pos;
			return this.finishToken(types$1.braceL);
		case 125:
			++this.pos;
			return this.finishToken(types$1.braceR);
		case 58:
			++this.pos;
			return this.finishToken(types$1.colon);
		case 96:
			if (this.options.ecmaVersion < 6) break;
			++this.pos;
			return this.finishToken(types$1.backQuote);
		case 48:
			var next = this.input.charCodeAt(this.pos + 1);
			if (next === 120 || next === 88) return this.readRadixNumber(16);
			if (this.options.ecmaVersion >= 6) {
				if (next === 111 || next === 79) return this.readRadixNumber(8);
				if (next === 98 || next === 66) return this.readRadixNumber(2);
			}
		case 49:
		case 50:
		case 51:
		case 52:
		case 53:
		case 54:
		case 55:
		case 56:
		case 57: return this.readNumber(false);
		case 34:
		case 39: return this.readString(code);
		case 47: return this.readToken_slash();
		case 37:
		case 42: return this.readToken_mult_modulo_exp(code);
		case 124:
		case 38: return this.readToken_pipe_amp(code);
		case 94: return this.readToken_caret();
		case 43:
		case 45: return this.readToken_plus_min(code);
		case 60:
		case 62: return this.readToken_lt_gt(code);
		case 61:
		case 33: return this.readToken_eq_excl(code);
		case 63: return this.readToken_question();
		case 126: return this.finishOp(types$1.prefix, 1);
		case 35: return this.readToken_numberSign();
	}
	this.raise(this.pos, "Unexpected character '" + codePointToString(code) + "'");
};
pp.finishOp = function(type, size) {
	var str = this.input.slice(this.pos, this.pos + size);
	this.pos += size;
	return this.finishToken(type, str);
};
pp.readRegexp = function() {
	var escaped, inClass, start = this.pos;
	for (;;) {
		if (this.pos >= this.input.length) this.raise(start, "Unterminated regular expression");
		var ch = this.input.charAt(this.pos);
		if (lineBreak.test(ch)) this.raise(start, "Unterminated regular expression");
		if (!escaped) {
			if (ch === "[") inClass = true;
			else if (ch === "]" && inClass) inClass = false;
			else if (ch === "/" && !inClass) break;
			escaped = ch === "\\";
		} else escaped = false;
		++this.pos;
	}
	var pattern = this.input.slice(start, this.pos);
	++this.pos;
	var flagsStart = this.pos;
	var flags = this.readWord1();
	if (this.containsEsc) this.unexpected(flagsStart);
	var state = this.regexpState || (this.regexpState = new RegExpValidationState(this));
	state.reset(start, pattern, flags);
	this.validateRegExpFlags(state);
	this.validateRegExpPattern(state);
	var value = null;
	try {
		value = new RegExp(pattern, flags);
	} catch (e) {}
	return this.finishToken(types$1.regexp, {
		pattern,
		flags,
		value
	});
};
pp.readInt = function(radix, len, maybeLegacyOctalNumericLiteral) {
	var allowSeparators = this.options.ecmaVersion >= 12 && len === void 0;
	var isLegacyOctalNumericLiteral = maybeLegacyOctalNumericLiteral && this.input.charCodeAt(this.pos) === 48;
	var start = this.pos, total = 0, lastCode = 0;
	for (var i = 0, e = len == null ? Infinity : len; i < e; ++i, ++this.pos) {
		var code = this.input.charCodeAt(this.pos), val = void 0;
		if (allowSeparators && code === 95) {
			if (isLegacyOctalNumericLiteral) this.raiseRecoverable(this.pos, "Numeric separator is not allowed in legacy octal numeric literals");
			if (lastCode === 95) this.raiseRecoverable(this.pos, "Numeric separator must be exactly one underscore");
			if (i === 0) this.raiseRecoverable(this.pos, "Numeric separator is not allowed at the first of digits");
			lastCode = code;
			continue;
		}
		if (code >= 97) val = code - 97 + 10;
		else if (code >= 65) val = code - 65 + 10;
		else if (code >= 48 && code <= 57) val = code - 48;
		else val = Infinity;
		if (val >= radix) break;
		lastCode = code;
		total = total * radix + val;
	}
	if (allowSeparators && lastCode === 95) this.raiseRecoverable(this.pos - 1, "Numeric separator is not allowed at the last of digits");
	if (this.pos === start || len != null && this.pos - start !== len) return null;
	return total;
};
function stringToNumber(str, isLegacyOctalNumericLiteral) {
	if (isLegacyOctalNumericLiteral) return parseInt(str, 8);
	return parseFloat(str.replace(/_/g, ""));
}
function stringToBigInt(str) {
	if (typeof BigInt !== "function") return null;
	return BigInt(str.replace(/_/g, ""));
}
pp.readRadixNumber = function(radix) {
	var start = this.pos;
	this.pos += 2;
	var val = this.readInt(radix);
	if (val == null) this.raise(this.start + 2, "Expected number in radix " + radix);
	if (this.options.ecmaVersion >= 11 && this.input.charCodeAt(this.pos) === 110) {
		val = stringToBigInt(this.input.slice(start, this.pos));
		++this.pos;
	} else if (isIdentifierStart(this.fullCharCodeAtPos())) this.raise(this.pos, "Identifier directly after number");
	return this.finishToken(types$1.num, val);
};
pp.readNumber = function(startsWithDot) {
	var start = this.pos;
	if (!startsWithDot && this.readInt(10, void 0, true) === null) this.raise(start, "Invalid number");
	var octal = this.pos - start >= 2 && this.input.charCodeAt(start) === 48;
	if (octal && this.strict) this.raise(start, "Invalid number");
	var next = this.input.charCodeAt(this.pos);
	if (!octal && !startsWithDot && this.options.ecmaVersion >= 11 && next === 110) {
		var val$1 = stringToBigInt(this.input.slice(start, this.pos));
		++this.pos;
		if (isIdentifierStart(this.fullCharCodeAtPos())) this.raise(this.pos, "Identifier directly after number");
		return this.finishToken(types$1.num, val$1);
	}
	if (octal && /[89]/.test(this.input.slice(start, this.pos))) octal = false;
	if (next === 46 && !octal) {
		++this.pos;
		this.readInt(10);
		next = this.input.charCodeAt(this.pos);
	}
	if ((next === 69 || next === 101) && !octal) {
		next = this.input.charCodeAt(++this.pos);
		if (next === 43 || next === 45) ++this.pos;
		if (this.readInt(10) === null) this.raise(start, "Invalid number");
	}
	if (isIdentifierStart(this.fullCharCodeAtPos())) this.raise(this.pos, "Identifier directly after number");
	var val = stringToNumber(this.input.slice(start, this.pos), octal);
	return this.finishToken(types$1.num, val);
};
pp.readCodePoint = function() {
	var ch = this.input.charCodeAt(this.pos), code;
	if (ch === 123) {
		if (this.options.ecmaVersion < 6) this.unexpected();
		var codePos = ++this.pos;
		code = this.readHexChar(this.input.indexOf("}", this.pos) - this.pos);
		++this.pos;
		if (code > 1114111) this.invalidStringToken(codePos, "Code point out of bounds");
	} else code = this.readHexChar(4);
	return code;
};
pp.readString = function(quote) {
	var out = "", chunkStart = ++this.pos;
	for (;;) {
		if (this.pos >= this.input.length) this.raise(this.start, "Unterminated string constant");
		var ch = this.input.charCodeAt(this.pos);
		if (ch === quote) break;
		if (ch === 92) {
			out += this.input.slice(chunkStart, this.pos);
			out += this.readEscapedChar(false);
			chunkStart = this.pos;
		} else if (ch === 8232 || ch === 8233) {
			if (this.options.ecmaVersion < 10) this.raise(this.start, "Unterminated string constant");
			++this.pos;
			if (this.options.locations) {
				this.curLine++;
				this.lineStart = this.pos;
			}
		} else {
			if (isNewLine(ch)) this.raise(this.start, "Unterminated string constant");
			++this.pos;
		}
	}
	out += this.input.slice(chunkStart, this.pos++);
	return this.finishToken(types$1.string, out);
};
var INVALID_TEMPLATE_ESCAPE_ERROR = {};
pp.tryReadTemplateToken = function() {
	this.inTemplateElement = true;
	try {
		this.readTmplToken();
	} catch (err) {
		if (err === INVALID_TEMPLATE_ESCAPE_ERROR) this.readInvalidTemplateToken();
		else throw err;
	}
	this.inTemplateElement = false;
};
pp.invalidStringToken = function(position, message) {
	if (this.inTemplateElement && this.options.ecmaVersion >= 9) throw INVALID_TEMPLATE_ESCAPE_ERROR;
	else this.raise(position, message);
};
pp.readTmplToken = function() {
	var out = "", chunkStart = this.pos;
	for (;;) {
		if (this.pos >= this.input.length) this.raise(this.start, "Unterminated template");
		var ch = this.input.charCodeAt(this.pos);
		if (ch === 96 || ch === 36 && this.input.charCodeAt(this.pos + 1) === 123) {
			if (this.pos === this.start && (this.type === types$1.template || this.type === types$1.invalidTemplate)) {
				if (ch === 36) {
					this.pos += 2;
					return this.finishToken(types$1.dollarBraceL);
				} else {
					++this.pos;
					return this.finishToken(types$1.backQuote);
				}
			}
			out += this.input.slice(chunkStart, this.pos);
			return this.finishToken(types$1.template, out);
		}
		if (ch === 92) {
			out += this.input.slice(chunkStart, this.pos);
			out += this.readEscapedChar(true);
			chunkStart = this.pos;
		} else if (isNewLine(ch)) {
			out += this.input.slice(chunkStart, this.pos);
			++this.pos;
			switch (ch) {
				case 13: if (this.input.charCodeAt(this.pos) === 10) ++this.pos;
				case 10:
					out += "\n";
					break;
				default: out += String.fromCharCode(ch);
			}
			if (this.options.locations) {
				++this.curLine;
				this.lineStart = this.pos;
			}
			chunkStart = this.pos;
		} else ++this.pos;
	}
};
pp.readInvalidTemplateToken = function() {
	for (; this.pos < this.input.length; this.pos++) switch (this.input[this.pos]) {
		case "\\":
			++this.pos;
			break;
		case "$": if (this.input[this.pos + 1] !== "{") break;
		case "`": return this.finishToken(types$1.invalidTemplate, this.input.slice(this.start, this.pos));
		case "\r": if (this.input[this.pos + 1] === "\n") ++this.pos;
		case "\n":
		case "\u2028":
		case "\u2029":
			++this.curLine;
			this.lineStart = this.pos + 1;
	}
	this.raise(this.start, "Unterminated template");
};
pp.readEscapedChar = function(inTemplate) {
	var ch = this.input.charCodeAt(++this.pos);
	++this.pos;
	switch (ch) {
		case 110: return "\n";
		case 114: return "\r";
		case 120: return String.fromCharCode(this.readHexChar(2));
		case 117: return codePointToString(this.readCodePoint());
		case 116: return "	";
		case 98: return "\b";
		case 118: return "\v";
		case 102: return "\f";
		case 13: if (this.input.charCodeAt(this.pos) === 10) ++this.pos;
		case 10:
			if (this.options.locations) {
				this.lineStart = this.pos;
				++this.curLine;
			}
			return "";
		case 56:
		case 57:
			if (this.strict) this.invalidStringToken(this.pos - 1, "Invalid escape sequence");
			if (inTemplate) {
				var codePos = this.pos - 1;
				this.invalidStringToken(codePos, "Invalid escape sequence in template string");
			}
		default:
			if (ch >= 48 && ch <= 55) {
				var octalStr = this.input.substr(this.pos - 1, 3).match(/^[0-7]+/)[0];
				var octal = parseInt(octalStr, 8);
				if (octal > 255) {
					octalStr = octalStr.slice(0, -1);
					octal = parseInt(octalStr, 8);
				}
				this.pos += octalStr.length - 1;
				ch = this.input.charCodeAt(this.pos);
				if ((octalStr !== "0" || ch === 56 || ch === 57) && (this.strict || inTemplate)) this.invalidStringToken(this.pos - 1 - octalStr.length, inTemplate ? "Octal literal in template string" : "Octal literal in strict mode");
				return String.fromCharCode(octal);
			}
			if (isNewLine(ch)) {
				if (this.options.locations) {
					this.lineStart = this.pos;
					++this.curLine;
				}
				return "";
			}
			return String.fromCharCode(ch);
	}
};
pp.readHexChar = function(len) {
	var codePos = this.pos;
	var n = this.readInt(16, len);
	if (n === null) this.invalidStringToken(codePos, "Bad character escape sequence");
	return n;
};
pp.readWord1 = function() {
	this.containsEsc = false;
	var word = "", first = true, chunkStart = this.pos;
	var astral = this.options.ecmaVersion >= 6;
	while (this.pos < this.input.length) {
		var ch = this.fullCharCodeAtPos();
		if (isIdentifierChar(ch, astral)) this.pos += ch <= 65535 ? 1 : 2;
		else if (ch === 92) {
			this.containsEsc = true;
			word += this.input.slice(chunkStart, this.pos);
			var escStart = this.pos;
			if (this.input.charCodeAt(++this.pos) !== 117) this.invalidStringToken(this.pos, "Expecting Unicode escape sequence \\uXXXX");
			++this.pos;
			var esc = this.readCodePoint();
			if (!(first ? isIdentifierStart : isIdentifierChar)(esc, astral)) this.invalidStringToken(escStart, "Invalid Unicode escape");
			word += codePointToString(esc);
			chunkStart = this.pos;
		} else break;
		first = false;
	}
	return word + this.input.slice(chunkStart, this.pos);
};
pp.readWord = function() {
	var word = this.readWord1();
	var type = types$1.name;
	if (this.keywords.test(word)) type = keywords[word];
	return this.finishToken(type, word);
};
Parser.acorn = {
	Parser,
	version: "8.18.0",
	defaultOptions,
	Position,
	SourceLocation,
	getLineInfo,
	Node,
	TokenType,
	tokTypes: types$1,
	keywordTypes: keywords,
	TokContext,
	tokContexts: types,
	isIdentifierChar,
	isIdentifierStart,
	Token,
	isNewLine,
	lineBreak,
	lineBreakG,
	nonASCIIwhitespace
};
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/constants.js
var constants = {
	undefined: "void(0)",
	Infinity: "Number.POSITIVE_INFINITY",
	NaN: "Number.NaN",
	E: "Math.E",
	LN2: "Math.LN2",
	LN10: "Math.LN10",
	LOG2E: "Math.LOG2E",
	LOG10E: "Math.LOG10E",
	PI: "Math.PI",
	SQRT1_2: "Math.SQRT1_2",
	SQRT2: "Math.SQRT2"
};
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/util/is-number.js
/**
* @param {*} value
* @returns {value is number}
*/
function isNumber(value) {
	return typeof value === "number";
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/expression/parse-expression.js
var NO = (msg) => (node, ctx) => ctx.error(node, msg + " not allowed");
var ERROR_AGGREGATE = NO("Aggregate function");
var ERROR_WINDOW = NO("Window function");
var ERROR_COLUMN = "Invalid column reference";
var ERROR_AGGRONLY = ERROR_COLUMN + " (must be input to an aggregate function)";
var ERROR_FUNCTION = "Invalid function call";
var ERROR_MEMBER = "Invalid member expression";
var ERROR_OP_PARAMETER = "Invalid operator parameter";
var ERROR_PARAM = "Invalid param reference";
var ERROR_VARIABLE = "Invalid variable reference";
var ERROR_VARIABLE_OP = "Variable not accessible in operator call";
var ERROR_DECLARATION = "Unsupported variable declaration";
var ERROR_CLOSURE = "Table expressions do not support closures";
var ERROR_ESCAPE = "Use aq.escape(fn) to use a function as-is (including closures)";
var ERROR_USE_PARAMS = "use table.params({ name: value }) to define dynamic parameters";
var ERROR_ADD_FUNCTION = "use aq.addFunction(name, fn) to add new op functions";
var ERROR_VARIABLE_NOTE = `\nNote: ${ERROR_CLOSURE}. ${ERROR_ESCAPE}, or ${ERROR_USE_PARAMS}.`;
var ERROR_FUNCTION_NOTE = `\nNote: ${ERROR_CLOSURE}. ${ERROR_ESCAPE}, or ${ERROR_ADD_FUNCTION}.`;
var ERROR_ROW_OBJECT = `The ${ROW_OBJECT} method is not valid in multi-table expressions.`;
var visitors = {
	FunctionDeclaration: NO("Function definitions"),
	ForStatement: NO("For loops"),
	ForOfStatement: NO("For-of loops"),
	ForInStatement: NO("For-in loops"),
	WhileStatement: NO("While loops"),
	DoWhileStatement: NO("Do-while loops"),
	AwaitExpression: NO("Await expressions"),
	ArrowFunctionExpression: NO("Function definitions"),
	AssignmentExpression: NO("Assignments"),
	FunctionExpression: NO("Function definitions"),
	NewExpression: NO("Use of \"new\""),
	UpdateExpression: NO("Update expressions"),
	VariableDeclarator(node, ctx) {
		handleDeclaration(node.id, ctx);
	},
	Identifier(node, ctx, parent) {
		if (handleIdentifier(node, ctx, parent) && !ctx.scope.has(node.name)) ctx.error(node, ERROR_VARIABLE, ERROR_VARIABLE_NOTE);
	},
	CallExpression(node, ctx) {
		const name = functionName(node.callee);
		const def = getAggregate(name) || getWindow(name);
		if (def) {
			if ((ctx.join || ctx.aggregate === false) && hasAggregate(name)) ERROR_AGGREGATE(node, ctx);
			if ((ctx.join || ctx.window === false) && hasWindow(name)) ERROR_WINDOW(node, ctx);
			ctx.$op = 1;
			if (ctx.ast) {
				updateFunctionNode(node, name, ctx);
				node.arguments.forEach((arg) => walk(arg, ctx, opVisitors));
			} else {
				const op = ctx.op(parseOperator(ctx, def, name, node.arguments));
				Object.assign(node, {
					type: "Op",
					name: op.id
				});
			}
			ctx.$op = 0;
			return false;
		} else if (hasFunction(name)) updateFunctionNode(node, name, ctx);
		else ctx.error(node, ERROR_FUNCTION, ERROR_FUNCTION_NOTE);
	},
	MemberExpression(node, ctx, parent) {
		const { object, property } = node;
		if (!is("Identifier", object)) return;
		const { name } = object;
		if (isMath(node) && is("Identifier", property) && Object.hasOwn(constants, property.name)) {
			updateConstantNode(node, property.name);
			return;
		}
		const index = name === ctx.tuple ? 0 : name === ctx.tuple1 ? 1 : name === ctx.tuple2 ? 2 : -1;
		if (index >= 0) return spliceMember(node, index, ctx, checkColumn, parent);
		else if (name === ctx.$param) return spliceMember(node, index, ctx, checkParam);
		else if (ctx.paramsRef.has(name)) updateParameterNode(node, ctx.paramsRef.get(name));
		else if (ctx.columnRef.has(name)) updateColumnNode(object, name, ctx, node);
		else if (Object.hasOwn(ctx.params, name)) updateParameterNode(object, name);
	}
};
function spliceMember(node, index, ctx, check, parent) {
	const { property, computed } = node;
	let name;
	if (!computed) name = property.name;
	else if (is("Literal", property)) name = property.value;
	else try {
		walk(property, ctx, visitors, node);
		name = ctx.param(property);
	} catch (e) {
		ctx.error(node, ERROR_MEMBER);
	}
	check(node, name, index, ctx, parent);
	return false;
}
var opVisitors = {
	...visitors,
	VariableDeclarator: NO("Variable declaration in operator call"),
	Identifier(node, ctx, parent) {
		if (handleIdentifier(node, ctx, parent)) ctx.error(node, ERROR_VARIABLE_OP);
	},
	CallExpression(node, ctx) {
		const name = functionName(node.callee);
		if (hasFunction(name)) updateFunctionNode(node, name, ctx);
		else ctx.error(node, ERROR_FUNCTION, ERROR_FUNCTION_NOTE);
	}
};
function parseOperator(ctx, def, name, args) {
	const fields = [];
	const params = [];
	const idxFields = def.param[0] || 0;
	const idxParams = idxFields + (def.param[1] || 0);
	args.forEach((arg, index) => {
		if (index < idxFields) {
			walk(arg, ctx, opVisitors);
			fields.push(ctx.field(arg));
		} else if (index < idxParams) {
			walk(arg, ctx, opVisitors);
			params.push(ctx.param(arg));
		} else ctx.error(arg, ERROR_OP_PARAMETER);
	});
	return {
		name,
		fields,
		params,
		...ctx.spec.window || {}
	};
}
function functionName(node) {
	return is("Identifier", node) ? node.name : !is("MemberExpression", node) ? null : isMath(node) ? rewriteMath(node.property.name) : node.property.name;
}
function isMath(node) {
	return is("Identifier", node.object) && node.object.name === "Math";
}
function rewriteMath(name) {
	return name === "max" ? "greatest" : name === "min" ? "least" : name;
}
function handleIdentifier(node, ctx, parent) {
	const { name } = node;
	if (is("MemberExpression", parent) && parent.property === node) {} else if (is("Property", parent) && parent.key === node) {} else if (ctx.paramsRef.has(name)) updateParameterNode(node, ctx.paramsRef.get(name));
	else if (ctx.columnRef.has(name)) updateColumnNode(node, name, ctx, parent);
	else if (Object.hasOwn(ctx.params, name)) updateParameterNode(node, name);
	else if (Object.hasOwn(constants, name)) updateConstantNode(node, name);
	else return true;
}
function checkColumn(node, name, index, ctx, parent) {
	const table = index === 0 ? ctx.table : index > 0 ? ctx.join[index - 1] : null;
	const col = table && table.column(name);
	if (table && !col) ctx.error(node, ERROR_COLUMN);
	if (ctx.aggronly && !ctx.$op) ctx.error(node, ERROR_AGGRONLY);
	rewrite(node, name, index, col, parent);
}
function updateColumnNode(node, key, ctx, parent) {
	const [name, index] = ctx.columnRef.get(key);
	checkColumn(node, name, index, ctx, parent);
}
function checkParam(node, name, index, ctx) {
	if (ctx.params && !Object.hasOwn(ctx.params, name)) ctx.error(node, ERROR_PARAM);
	updateParameterNode(node, name);
}
function updateParameterNode(node, name) {
	node.type = Parameter;
	node.name = name;
}
function updateConstantNode(node, name) {
	node.type = Constant;
	node.name = name;
	node.raw = constants[name];
}
function updateFunctionNode(node, name, ctx) {
	if (name === "row_object") {
		const t = ctx.table;
		if (!t) ctx.error(node, ERROR_ROW_OBJECT);
		rowObjectExpression(node, t, node.arguments.length ? node.arguments.map((node) => {
			const col = ctx.param(node);
			const name = isNumber(col) ? t.columnName(col) : col;
			if (!t.column(name)) ctx.error(node, ERROR_COLUMN);
			return name;
		}) : t.columnNames());
	} else node.callee = {
		type: Function$1,
		name
	};
}
function handleDeclaration(node, ctx) {
	if (is("Identifier", node)) ctx.scope.add(node.name);
	else if (is("ArrayPattern", node)) node.elements.forEach((elm) => handleDeclaration(elm, ctx));
	else if (is("ObjectPattern", node)) node.properties.forEach((prop) => handleDeclaration(prop.value, ctx));
	else ctx.error(node.id, ERROR_DECLARATION);
}
//#endregion
//#region ../../node_modules/.pnpm/arquero@8.0.3/node_modules/arquero/src/op/register.js
/**
* Aggregate function definition.
* @typedef {import('./aggregate-functions.js').AggregateDef} AggregateDef
*/
/**
* Window function definition.
* @typedef {import('./window-functions.js').WindowDef} WindowDef
*/
/**
* Options for registering new functions.
* @typedef {object} RegisterOptions
* @property {boolean} [override=false] Flag indicating if the added
*  function can override an existing function with the same name.
*/
//#endregion
//#region ../../node_modules/.pnpm/lz4js@0.2.0/node_modules/lz4js/util.js
var require_util = /* @__PURE__ */ __commonJSMin(((exports) => {
	exports.hashU32 = function hashU32(a) {
		a = a | 0;
		a = a + 2127912214 + (a << 12) | 0;
		a = a ^ -949894596 ^ a >>> 19;
		a = a + 374761393 + (a << 5) | 0;
		a = a + -744332180 ^ a << 9;
		a = a + -42973499 + (a << 3) | 0;
		return a ^ -1252372727 ^ a >>> 16 | 0;
	};
	exports.readU64 = function readU64(b, n) {
		var x = 0;
		x |= b[n++] << 0;
		x |= b[n++] << 8;
		x |= b[n++] << 16;
		x |= b[n++] << 24;
		x |= b[n++] << 32;
		x |= b[n++] << 40;
		x |= b[n++] << 48;
		x |= b[n++] << 56;
		return x;
	};
	exports.readU32 = function readU32(b, n) {
		var x = 0;
		x |= b[n++] << 0;
		x |= b[n++] << 8;
		x |= b[n++] << 16;
		x |= b[n++] << 24;
		return x;
	};
	exports.writeU32 = function writeU32(b, n, x) {
		b[n++] = x >> 0 & 255;
		b[n++] = x >> 8 & 255;
		b[n++] = x >> 16 & 255;
		b[n++] = x >> 24 & 255;
	};
	exports.imul = function imul(a, b) {
		var ah = a >>> 16;
		var al = a & 65535;
		var bh = b >>> 16;
		var bl = b & 65535;
		return al * bl + (ah * bl + al * bh << 16) | 0;
	};
}));
//#endregion
//#region ../../node_modules/.pnpm/lz4js@0.2.0/node_modules/lz4js/xxh32.js
var require_xxh32 = /* @__PURE__ */ __commonJSMin(((exports) => {
	var util = require_util();
	var prime1 = 2654435761;
	var prime2 = 2246822519;
	var prime3 = 3266489917;
	var prime4 = 668265263;
	var prime5 = 374761393;
	function rotl32(x, r) {
		x = x | 0;
		r = r | 0;
		return x >>> (32 - r | 0) | x << r | 0;
	}
	function rotmul32(h, r, m) {
		h = h | 0;
		r = r | 0;
		m = m | 0;
		return util.imul(h >>> (32 - r | 0) | h << r, m) | 0;
	}
	function shiftxor32(h, s) {
		h = h | 0;
		s = s | 0;
		return h >>> s ^ h | 0;
	}
	function xxhapply(h, src, m0, s, m1) {
		return rotmul32(util.imul(src, m0) + h, s, m1);
	}
	function xxh1(h, src, index) {
		return rotmul32(h + util.imul(src[index], prime5), 11, prime1);
	}
	function xxh4(h, src, index) {
		return xxhapply(h, util.readU32(src, index), prime3, 17, prime4);
	}
	function xxh16(h, src, index) {
		return [
			xxhapply(h[0], util.readU32(src, index + 0), prime2, 13, prime1),
			xxhapply(h[1], util.readU32(src, index + 4), prime2, 13, prime1),
			xxhapply(h[2], util.readU32(src, index + 8), prime2, 13, prime1),
			xxhapply(h[3], util.readU32(src, index + 12), prime2, 13, prime1)
		];
	}
	function xxh32(seed, src, index, len) {
		var h, l = len;
		if (len >= 16) {
			h = [
				seed + prime1 + prime2,
				seed + prime2,
				seed,
				seed - prime1
			];
			while (len >= 16) {
				h = xxh16(h, src, index);
				index += 16;
				len -= 16;
			}
			h = rotl32(h[0], 1) + rotl32(h[1], 7) + rotl32(h[2], 12) + rotl32(h[3], 18) + l;
		} else h = seed + prime5 + len >>> 0;
		while (len >= 4) {
			h = xxh4(h, src, index);
			index += 4;
			len -= 4;
		}
		while (len > 0) {
			h = xxh1(h, src, index);
			index++;
			len--;
		}
		h = shiftxor32(util.imul(shiftxor32(util.imul(shiftxor32(h, 15), prime2), 13), prime3), 16);
		return h >>> 0;
	}
	exports.hash = xxh32;
}));
(/* @__PURE__ */ __commonJSMin(((exports) => {
	var xxhash = require_xxh32();
	var util = require_util();
	var minMatch = 4;
	var minLength = 13;
	var searchLimit = 5;
	var skipTrigger = 6;
	var hashSize = 65536;
	var mlBits = 4;
	var mlMask = (1 << mlBits) - 1;
	var runMask = 15;
	var blockBuf = makeBuffer(5 << 20);
	var hashTable = makeHashTable();
	var magicNum = 407708164;
	var fdContentChksum = 4;
	var fdContentSize = 8;
	var fdBlockChksum = 16;
	var fdVersion = 64;
	var fdVersionMask = 192;
	var bsUncompressed = 2147483648;
	var bsDefault = 7;
	var bsShift = 4;
	var bsMask = 7;
	var bsMap = {
		4: 65536,
		5: 262144,
		6: 1048576,
		7: 4194304
	};
	function makeHashTable() {
		try {
			return new Uint32Array(hashSize);
		} catch (error) {
			var hashTable = new Array(hashSize);
			for (var i = 0; i < hashSize; i++) hashTable[i] = 0;
			return hashTable;
		}
	}
	function clearHashTable(table) {
		for (var i = 0; i < hashSize; i++) hashTable[i] = 0;
	}
	function makeBuffer(size) {
		try {
			return new Uint8Array(size);
		} catch (error) {
			var buf = new Array(size);
			for (var i = 0; i < size; i++) buf[i] = 0;
			return buf;
		}
	}
	function sliceArray(array, start, end) {
		if (typeof array.buffer !== void 0) {
			if (Uint8Array.prototype.slice) return array.slice(start, end);
			else {
				var len = array.length;
				start = start | 0;
				start = start < 0 ? Math.max(len + start, 0) : Math.min(start, len);
				end = end === void 0 ? len : end | 0;
				end = end < 0 ? Math.max(len + end, 0) : Math.min(end, len);
				var arraySlice = new Uint8Array(end - start);
				for (var i = start, n = 0; i < end;) arraySlice[n++] = array[i++];
				return arraySlice;
			}
		} else return array.slice(start, end);
	}
	exports.compressBound = function compressBound(n) {
		return n + n / 255 + 16 | 0;
	};
	exports.decompressBound = function decompressBound(src) {
		var sIndex = 0;
		if (util.readU32(src, sIndex) !== magicNum) throw new Error("invalid magic number");
		sIndex += 4;
		var descriptor = src[sIndex++];
		if ((descriptor & fdVersionMask) !== fdVersion) throw new Error("incompatible descriptor version " + (descriptor & fdVersionMask));
		var useBlockSum = (descriptor & fdBlockChksum) !== 0;
		var useContentSize = (descriptor & fdContentSize) !== 0;
		var bsIdx = src[sIndex++] >> bsShift & bsMask;
		if (bsMap[bsIdx] === void 0) throw new Error("invalid block size " + bsIdx);
		var maxBlockSize = bsMap[bsIdx];
		if (useContentSize) return util.readU64(src, sIndex);
		sIndex++;
		var maxSize = 0;
		while (true) {
			var blockSize = util.readU32(src, sIndex);
			sIndex += 4;
			if (blockSize & bsUncompressed) {
				blockSize &= ~bsUncompressed;
				maxSize += blockSize;
			} else maxSize += maxBlockSize;
			if (blockSize === 0) return maxSize;
			if (useBlockSum) sIndex += 4;
			sIndex += blockSize;
		}
	};
	exports.makeBuffer = makeBuffer;
	exports.decompressBlock = function decompressBlock(src, dst, sIndex, sLength, dIndex) {
		var mLength, mOffset, sEnd = sIndex + sLength, n, i;
		while (sIndex < sEnd) {
			var token = src[sIndex++];
			var literalCount = token >> 4;
			if (literalCount > 0) {
				if (literalCount === 15) while (true) {
					literalCount += src[sIndex];
					if (src[sIndex++] !== 255) break;
				}
				for (n = sIndex + literalCount; sIndex < n;) dst[dIndex++] = src[sIndex++];
			}
			if (sIndex >= sEnd) break;
			mLength = token & 15;
			mOffset = src[sIndex++] | src[sIndex++] << 8;
			if (mLength === 15) while (true) {
				mLength += src[sIndex];
				if (src[sIndex++] !== 255) break;
			}
			mLength += minMatch;
			for (i = dIndex - mOffset, n = i + mLength; i < n;) dst[dIndex++] = dst[i++] | 0;
		}
		return dIndex;
	};
	exports.compressBlock = function compressBlock(src, dst, sIndex, sLength, hashTable) {
		var mIndex, mAnchor, mLength, mOffset, mStep;
		var literalCount, dIndex = 0, sEnd = sLength + sIndex, n;
		mAnchor = sIndex;
		if (sLength >= minLength) {
			var searchMatchCount = (1 << skipTrigger) + 3;
			while (sIndex + minMatch < sEnd - searchLimit) {
				var seq = util.readU32(src, sIndex);
				var hash = util.hashU32(seq) >>> 0;
				hash = (hash >> 16 ^ hash) >>> 0 & 65535;
				mIndex = hashTable[hash] - 1;
				hashTable[hash] = sIndex + 1;
				if (mIndex < 0 || sIndex - mIndex >>> 16 > 0 || util.readU32(src, mIndex) !== seq) {
					mStep = searchMatchCount++ >> skipTrigger;
					sIndex += mStep;
					continue;
				}
				searchMatchCount = (1 << skipTrigger) + 3;
				literalCount = sIndex - mAnchor;
				mOffset = sIndex - mIndex;
				sIndex += minMatch;
				mIndex += minMatch;
				mLength = sIndex;
				while (sIndex < sEnd - searchLimit && src[sIndex] === src[mIndex]) {
					sIndex++;
					mIndex++;
				}
				mLength = sIndex - mLength;
				var token = mLength < mlMask ? mLength : mlMask;
				if (literalCount >= runMask) {
					dst[dIndex++] = (runMask << mlBits) + token;
					for (n = literalCount - runMask; n >= 255; n -= 255) dst[dIndex++] = 255;
					dst[dIndex++] = n;
				} else dst[dIndex++] = (literalCount << mlBits) + token;
				for (var i = 0; i < literalCount; i++) dst[dIndex++] = src[mAnchor + i];
				dst[dIndex++] = mOffset;
				dst[dIndex++] = mOffset >> 8;
				if (mLength >= mlMask) {
					for (n = mLength - mlMask; n >= 255; n -= 255) dst[dIndex++] = 255;
					dst[dIndex++] = n;
				}
				mAnchor = sIndex;
			}
		}
		if (mAnchor === 0) return 0;
		literalCount = sEnd - mAnchor;
		if (literalCount >= runMask) {
			dst[dIndex++] = runMask << mlBits;
			for (n = literalCount - runMask; n >= 255; n -= 255) dst[dIndex++] = 255;
			dst[dIndex++] = n;
		} else dst[dIndex++] = literalCount << mlBits;
		sIndex = mAnchor;
		while (sIndex < sEnd) dst[dIndex++] = src[sIndex++];
		return dIndex;
	};
	exports.decompressFrame = function decompressFrame(src, dst) {
		var useBlockSum, useContentSum, useContentSize, descriptor;
		var sIndex = 0;
		var dIndex = 0;
		if (util.readU32(src, sIndex) !== magicNum) throw new Error("invalid magic number");
		sIndex += 4;
		descriptor = src[sIndex++];
		if ((descriptor & fdVersionMask) !== fdVersion) throw new Error("incompatible descriptor version");
		useBlockSum = (descriptor & fdBlockChksum) !== 0;
		useContentSum = (descriptor & fdContentChksum) !== 0;
		useContentSize = (descriptor & fdContentSize) !== 0;
		if (bsMap[src[sIndex++] >> bsShift & bsMask] === void 0) throw new Error("invalid block size");
		if (useContentSize) sIndex += 8;
		sIndex++;
		while (true) {
			var compSize = util.readU32(src, sIndex);
			sIndex += 4;
			if (compSize === 0) break;
			if (useBlockSum) sIndex += 4;
			if ((compSize & bsUncompressed) !== 0) {
				compSize &= ~bsUncompressed;
				for (var j = 0; j < compSize; j++) dst[dIndex++] = src[sIndex++];
			} else {
				dIndex = exports.decompressBlock(src, dst, sIndex, compSize, dIndex);
				sIndex += compSize;
			}
		}
		if (useContentSum) sIndex += 4;
		return dIndex;
	};
	exports.compressFrame = function compressFrame(src, dst) {
		var dIndex = 0;
		util.writeU32(dst, dIndex, magicNum);
		dIndex += 4;
		dst[dIndex++] = fdVersion;
		dst[dIndex++] = bsDefault << bsShift;
		dst[dIndex] = xxhash.hash(0, dst, 4, dIndex - 4) >> 8;
		dIndex++;
		var maxBlockSize = bsMap[bsDefault];
		var remaining = src.length;
		var sIndex = 0;
		clearHashTable(hashTable);
		while (remaining > 0) {
			var compSize = 0;
			var blockSize = remaining > maxBlockSize ? maxBlockSize : remaining;
			compSize = exports.compressBlock(src, blockBuf, sIndex, blockSize, hashTable);
			if (compSize > blockSize || compSize === 0) {
				util.writeU32(dst, dIndex, 2147483648 | blockSize);
				dIndex += 4;
				for (var z = sIndex + blockSize; sIndex < z;) dst[dIndex++] = src[sIndex++];
				remaining -= blockSize;
			} else {
				util.writeU32(dst, dIndex, compSize);
				dIndex += 4;
				for (var j = 0; j < compSize;) dst[dIndex++] = blockBuf[j++];
				sIndex += blockSize;
				remaining -= blockSize;
			}
		}
		util.writeU32(dst, dIndex, 0);
		dIndex += 4;
		return dIndex;
	};
	exports.decompress = function decompress(src, maxSize) {
		var dst, size;
		if (maxSize === void 0) maxSize = exports.decompressBound(src);
		dst = exports.makeBuffer(maxSize);
		size = exports.decompressFrame(src, dst);
		if (size !== maxSize) dst = sliceArray(dst, 0, size);
		return dst;
	};
	exports.compress = function compress(src, maxSize) {
		var dst, size;
		if (maxSize === void 0) maxSize = exports.compressBound(src.length);
		dst = exports.makeBuffer(maxSize);
		size = exports.compressFrame(src, dst);
		if (size !== maxSize) dst = sliceArray(dst, 0, size);
		return dst;
	};
})))();
//#endregion
//#region ../../packages/util/src/brand.ts
/**
* Branded types for nominal typing in TypeScript.
*
* Branded types create distinct types from the same base type,
* preventing accidental misuse at compile time with zero runtime overhead.
*
* @example
* ```ts
* type UserId = Brand<number, "UserId">;
* type PostId = Brand<number, "PostId">;
*
* const makeUserId = make<UserId>();
* const makePostId = make<PostId>();
*
* const userId = makeUserId(42);
* const postId = makePostId(42);
* getUser(postId);  // ✗ compile error - PostId !== UserId
* ```
*
* @module
*/ /**
* Creates a brander function for a given branded type.
*
* @typeParam B - The branded type to produce
* @returns A function that casts base values to the branded type
*
* @example
* ```ts
* type UserId = Brand<number, "UserId">;
* const makeUserId = make<UserId>();
* const id = makeUserId(42);
* ```
*/ function make() {
	return (value) => value;
}
//#endregion
//#region ../../packages/util/src/asyncData.ts
/**
* The `compose` function allows a set of `AsyncData` values to be combined into
* a single `AsyncData`. The complex type of the function represents a transformation
* from an argument like this...
*
* ```typescript
*   { a: AsyncData<A>, b: AsyncData<B>, c: AsyncData<C> }
*```
* ...to a return value like this...
*```
*   AsyncData<{ a: A, b: B, c: C }>
*```
*
* In practice, this can be used to create hooks that depend on multiple API
* calls.
*
*/ function compose(hooks) {
	const result = {};
	const errors = [];
	let loadingResult = false;
	for (const key in hooks) {
		const { loading, error, data } = hooks[key];
		if (error) errors.push(error);
		else if (loading) loadingResult = true;
		else result[key] = data;
	}
	if (errors[0]) return {
		loading: false,
		error: errors[0]
	};
	if (loadingResult) return loading;
	return {
		loading: false,
		data: result
	};
}
function map(asyncData, fn) {
	if (asyncData.loading || asyncData.error) return asyncData;
	else return data(fn(asyncData.data));
}
/**
* The `data` function wraps the provided data in an `AsyncData` object, indicating
* that the data is not loading and there is no error.
*
* @template T - The type of the data
* @param {T} data - The data to wrap
* @returns {AsyncData<T>} - An `AsyncData` object with `loading` set to `false`
* and `data` set to the provided data
*/ function data(data) {
	return {
		loading: false,
		data
	};
}
/**
* The `loading` constant is an instance of `AsyncDataLoading` that can be shared
* to provide identity stability. It represents the state when the data is loading.
*/ var loading = make()({ loading: true });
//#endregion
//#region ../../packages/util/src/http.ts
/**
* Request options for every fetch the browser issues directly to a log
* location. That location is data (a link param, a listing entry, a
* server-supplied direct URL), not the page's own origin: it gets no
* referrer, no cross-origin credentials, and no redirect to a destination
* other than the one that was named.
*/ var logFetchInit = Object.freeze({
	credentials: "same-origin",
	referrerPolicy: "no-referrer",
	redirect: "error"
});
/**
* Fetches a range of bytes from a remote resource and returns it as a `Uint8Array`.
*/ var fetchRange = async (url, start, end) => {
	const arrayBuffer = await (await fetch(url, {
		...logFetchInit,
		headers: { Range: `bytes=${start}-${end}` }
	})).arrayBuffer();
	return new Uint8Array(arrayBuffer);
};
//#endregion
//#region ../../packages/util/src/hiddenCharacters.ts
var HIDDEN_RANGES = [
	[0, 31],
	[127, 159],
	[173, 173],
	[847, 847],
	[1564, 1564],
	[4447, 4448],
	[6068, 6069],
	[6155, 6159],
	[8203, 8207],
	[8232, 8238],
	[8288, 8303],
	[12644, 12644],
	[65279, 65279],
	[65440, 65440],
	[65529, 65531],
	[119155, 119162],
	[917504, 917631],
	[917760, 917999]
];
var ZWNJ = 8204;
var ZWJ = 8205;
var VARIATION_SELECTOR_16 = 65039;
var kEmoji = /^[\p{Extended_Pictographic}\p{Emoji_Modifier}]$/u;
var kJoiningScript = /^[\p{Script=Arabic}\p{Script=Syriac}\p{Script=Nko}\p{Script=Mongolian}\p{Script=Devanagari}\p{Script=Bengali}\p{Script=Gurmukhi}\p{Script=Gujarati}\p{Script=Oriya}\p{Script=Tamil}\p{Script=Telugu}\p{Script=Kannada}\p{Script=Malayalam}\p{Script=Sinhala}\p{Script=Myanmar}\p{Script=Khmer}]$/u;
var isEmoji = (codePoint) => kEmoji.test(String.fromCodePoint(codePoint));
var isJoiningScript = (codePoint) => kJoiningScript.test(String.fromCodePoint(codePoint));
/** A joiner inside an emoji ZWJ sequence or between letters of a joining
*  script renders (it shapes what's around it), so it hides nothing. */ var isPurposefulJoiner = (codePoint, prev, next) => {
	if (prev === void 0 || next === void 0) return false;
	if (codePoint === ZWJ && (isEmoji(prev) || prev === VARIATION_SELECTOR_16) && isEmoji(next)) return true;
	return isJoiningScript(prev) && isJoiningScript(next);
};
var LINE_FEED = 10;
var CARRIAGE_RETURN = 13;
var hex = (codePoint) => codePoint.toString(16);
var kCandidates = new RegExp(`[${HIDDEN_RANGES.flatMap(([lo, hi]) => lo <= LINE_FEED && hi >= LINE_FEED ? [[lo, 8], [11, hi]] : [[lo, hi]]).map(([lo, hi]) => `\\u{${hex(lo)}}-\\u{${hex(hi)}}`).join("")}]`, "gu");
var codePointBefore = (text, index) => {
	if (index === 0) return void 0;
	const low = text.charCodeAt(index - 1);
	if (index >= 2 && low >= 56320 && low <= 57343) {
		const high = text.charCodeAt(index - 2);
		if (high >= 55296 && high <= 56319) return text.codePointAt(index - 2);
	}
	return low;
};
var isHidden = (codePoint, prev, next) => {
	if (codePoint === ZWNJ || codePoint === ZWJ) return !isPurposefulJoiner(codePoint, prev, next);
	if (codePoint === CARRIAGE_RETURN) return next !== LINE_FEED;
	return true;
};
/**
* Replaces each hidden character with a visible `⟨U+XXXX⟩` marker, so text
* shown for inspection can't hide content or disguise itself (e.g. a bidi
* override making `gnp.exe` display as `exe.png`).
*/ var revealHiddenCharacters = (text) => text.replace(kCandidates, (match, offset) => {
	const codePoint = match.codePointAt(0) ?? 0;
	return isHidden(codePoint, codePointBefore(text, offset), text.codePointAt(offset + match.length)) ? `⟨U+${hex(codePoint).toUpperCase().padStart(4, "0")}⟩` : match;
});
//#endregion
//#region ../../node_modules/.pnpm/json5@2.2.3/node_modules/json5/dist/index.js
var require_dist = /* @__PURE__ */ __commonJSMin(((exports, module) => {
	(function(global, factory) {
		typeof exports === "object" && typeof module !== "undefined" ? module.exports = factory() : typeof define === "function" && define.amd ? define(factory) : global.JSON5 = factory();
	})(exports, (function() {
		"use strict";
		function createCommonjsModule(fn, module$1) {
			return module$1 = { exports: {} }, fn(module$1, module$1.exports), module$1.exports;
		}
		var _global = createCommonjsModule(function(module$2) {
			var global = module$2.exports = typeof window != "undefined" && window.Math == Math ? window : typeof self != "undefined" && self.Math == Math ? self : Function("return this")();
			if (typeof __g == "number") __g = global;
		});
		var _core = createCommonjsModule(function(module$3) {
			var core = module$3.exports = { version: "2.6.5" };
			if (typeof __e == "number") __e = core;
		});
		_core.version;
		var _isObject = function(it) {
			return typeof it === "object" ? it !== null : typeof it === "function";
		};
		var _anObject = function(it) {
			if (!_isObject(it)) throw TypeError(it + " is not an object!");
			return it;
		};
		var _fails = function(exec) {
			try {
				return !!exec();
			} catch (e) {
				return true;
			}
		};
		var _descriptors = !_fails(function() {
			return Object.defineProperty({}, "a", { get: function() {
				return 7;
			} }).a != 7;
		});
		var document = _global.document;
		var is = _isObject(document) && _isObject(document.createElement);
		var _domCreate = function(it) {
			return is ? document.createElement(it) : {};
		};
		var _ie8DomDefine = !_descriptors && !_fails(function() {
			return Object.defineProperty(_domCreate("div"), "a", { get: function() {
				return 7;
			} }).a != 7;
		});
		var _toPrimitive = function(it, S) {
			if (!_isObject(it)) return it;
			var fn, val;
			if (S && typeof (fn = it.toString) == "function" && !_isObject(val = fn.call(it))) return val;
			if (typeof (fn = it.valueOf) == "function" && !_isObject(val = fn.call(it))) return val;
			if (!S && typeof (fn = it.toString) == "function" && !_isObject(val = fn.call(it))) return val;
			throw TypeError("Can't convert object to primitive value");
		};
		var dP = Object.defineProperty;
		var _objectDp = { f: _descriptors ? Object.defineProperty : function defineProperty(O, P, Attributes) {
			_anObject(O);
			P = _toPrimitive(P, true);
			_anObject(Attributes);
			if (_ie8DomDefine) try {
				return dP(O, P, Attributes);
			} catch (e) {}
			if ("get" in Attributes || "set" in Attributes) throw TypeError("Accessors not supported!");
			if ("value" in Attributes) O[P] = Attributes.value;
			return O;
		} };
		var _propertyDesc = function(bitmap, value) {
			return {
				enumerable: !(bitmap & 1),
				configurable: !(bitmap & 2),
				writable: !(bitmap & 4),
				value
			};
		};
		var _hide = _descriptors ? function(object, key, value) {
			return _objectDp.f(object, key, _propertyDesc(1, value));
		} : function(object, key, value) {
			object[key] = value;
			return object;
		};
		var hasOwnProperty = {}.hasOwnProperty;
		var _has = function(it, key) {
			return hasOwnProperty.call(it, key);
		};
		var id = 0;
		var px = Math.random();
		var _uid = function(key) {
			return "Symbol(".concat(key === void 0 ? "" : key, ")_", (++id + px).toString(36));
		};
		var _library = false;
		var _functionToString = createCommonjsModule(function(module$4) {
			var SHARED = "__core-js_shared__";
			var store = _global[SHARED] || (_global[SHARED] = {});
			(module$4.exports = function(key, value) {
				return store[key] || (store[key] = value !== void 0 ? value : {});
			})("versions", []).push({
				version: _core.version,
				mode: _library ? "pure" : "global",
				copyright: "© 2019 Denis Pushkarev (zloirock.ru)"
			});
		})("native-function-to-string", Function.toString);
		var _redefine = createCommonjsModule(function(module$5) {
			var SRC = _uid("src");
			var TO_STRING = "toString";
			var TPL = ("" + _functionToString).split(TO_STRING);
			_core.inspectSource = function(it) {
				return _functionToString.call(it);
			};
			(module$5.exports = function(O, key, val, safe) {
				var isFunction = typeof val == "function";
				if (isFunction) _has(val, "name") || _hide(val, "name", key);
				if (O[key] === val) return;
				if (isFunction) _has(val, SRC) || _hide(val, SRC, O[key] ? "" + O[key] : TPL.join(String(key)));
				if (O === _global) O[key] = val;
				else if (!safe) {
					delete O[key];
					_hide(O, key, val);
				} else if (O[key]) O[key] = val;
				else _hide(O, key, val);
			})(Function.prototype, TO_STRING, function toString() {
				return typeof this == "function" && this[SRC] || _functionToString.call(this);
			});
		});
		var _aFunction = function(it) {
			if (typeof it != "function") throw TypeError(it + " is not a function!");
			return it;
		};
		var _ctx = function(fn, that, length) {
			_aFunction(fn);
			if (that === void 0) return fn;
			switch (length) {
				case 1: return function(a) {
					return fn.call(that, a);
				};
				case 2: return function(a, b) {
					return fn.call(that, a, b);
				};
				case 3: return function(a, b, c) {
					return fn.call(that, a, b, c);
				};
			}
			return function() {
				return fn.apply(that, arguments);
			};
		};
		var PROTOTYPE = "prototype";
		var $export = function(type, name, source) {
			var IS_FORCED = type & $export.F;
			var IS_GLOBAL = type & $export.G;
			var IS_STATIC = type & $export.S;
			var IS_PROTO = type & $export.P;
			var IS_BIND = type & $export.B;
			var target = IS_GLOBAL ? _global : IS_STATIC ? _global[name] || (_global[name] = {}) : (_global[name] || {})[PROTOTYPE];
			var exports$1 = IS_GLOBAL ? _core : _core[name] || (_core[name] = {});
			var expProto = exports$1[PROTOTYPE] || (exports$1[PROTOTYPE] = {});
			var key, own, out, exp;
			if (IS_GLOBAL) source = name;
			for (key in source) {
				own = !IS_FORCED && target && target[key] !== void 0;
				out = (own ? target : source)[key];
				exp = IS_BIND && own ? _ctx(out, _global) : IS_PROTO && typeof out == "function" ? _ctx(Function.call, out) : out;
				if (target) _redefine(target, key, out, type & $export.U);
				if (exports$1[key] != out) _hide(exports$1, key, exp);
				if (IS_PROTO && expProto[key] != out) expProto[key] = out;
			}
		};
		_global.core = _core;
		$export.F = 1;
		$export.G = 2;
		$export.S = 4;
		$export.P = 8;
		$export.B = 16;
		$export.W = 32;
		$export.U = 64;
		$export.R = 128;
		var _export = $export;
		var ceil = Math.ceil;
		var floor = Math.floor;
		var _toInteger = function(it) {
			return isNaN(it = +it) ? 0 : (it > 0 ? floor : ceil)(it);
		};
		var _defined = function(it) {
			if (it == void 0) throw TypeError("Can't call method on  " + it);
			return it;
		};
		var _stringAt = function(TO_STRING) {
			return function(that, pos) {
				var s = String(_defined(that));
				var i = _toInteger(pos);
				var l = s.length;
				var a, b;
				if (i < 0 || i >= l) return TO_STRING ? "" : void 0;
				a = s.charCodeAt(i);
				return a < 55296 || a > 56319 || i + 1 === l || (b = s.charCodeAt(i + 1)) < 56320 || b > 57343 ? TO_STRING ? s.charAt(i) : a : TO_STRING ? s.slice(i, i + 2) : (a - 55296 << 10) + (b - 56320) + 65536;
			};
		};
		var $at = _stringAt(false);
		_export(_export.P, "String", { codePointAt: function codePointAt(pos) {
			return $at(this, pos);
		} });
		_core.String.codePointAt;
		var max = Math.max;
		var min = Math.min;
		var _toAbsoluteIndex = function(index, length) {
			index = _toInteger(index);
			return index < 0 ? max(index + length, 0) : min(index, length);
		};
		var fromCharCode = String.fromCharCode;
		var $fromCodePoint = String.fromCodePoint;
		_export(_export.S + _export.F * (!!$fromCodePoint && $fromCodePoint.length != 1), "String", { fromCodePoint: function fromCodePoint(x) {
			var arguments$1 = arguments;
			var res = [];
			var aLen = arguments.length;
			var i = 0;
			var code;
			while (aLen > i) {
				code = +arguments$1[i++];
				if (_toAbsoluteIndex(code, 1114111) !== code) throw RangeError(code + " is not a valid code point");
				res.push(code < 65536 ? fromCharCode(code) : fromCharCode(((code -= 65536) >> 10) + 55296, code % 1024 + 56320));
			}
			return res.join("");
		} });
		_core.String.fromCodePoint;
		var unicode = {
			Space_Separator: /[\u1680\u2000-\u200A\u202F\u205F\u3000]/,
			ID_Start: /[\xAA\xB5\xBA\xC0-\xD6\xD8-\xF6\xF8-\u02C1\u02C6-\u02D1\u02E0-\u02E4\u02EC\u02EE\u0370-\u0374\u0376\u0377\u037A-\u037D\u037F\u0386\u0388-\u038A\u038C\u038E-\u03A1\u03A3-\u03F5\u03F7-\u0481\u048A-\u052F\u0531-\u0556\u0559\u0561-\u0587\u05D0-\u05EA\u05F0-\u05F2\u0620-\u064A\u066E\u066F\u0671-\u06D3\u06D5\u06E5\u06E6\u06EE\u06EF\u06FA-\u06FC\u06FF\u0710\u0712-\u072F\u074D-\u07A5\u07B1\u07CA-\u07EA\u07F4\u07F5\u07FA\u0800-\u0815\u081A\u0824\u0828\u0840-\u0858\u0860-\u086A\u08A0-\u08B4\u08B6-\u08BD\u0904-\u0939\u093D\u0950\u0958-\u0961\u0971-\u0980\u0985-\u098C\u098F\u0990\u0993-\u09A8\u09AA-\u09B0\u09B2\u09B6-\u09B9\u09BD\u09CE\u09DC\u09DD\u09DF-\u09E1\u09F0\u09F1\u09FC\u0A05-\u0A0A\u0A0F\u0A10\u0A13-\u0A28\u0A2A-\u0A30\u0A32\u0A33\u0A35\u0A36\u0A38\u0A39\u0A59-\u0A5C\u0A5E\u0A72-\u0A74\u0A85-\u0A8D\u0A8F-\u0A91\u0A93-\u0AA8\u0AAA-\u0AB0\u0AB2\u0AB3\u0AB5-\u0AB9\u0ABD\u0AD0\u0AE0\u0AE1\u0AF9\u0B05-\u0B0C\u0B0F\u0B10\u0B13-\u0B28\u0B2A-\u0B30\u0B32\u0B33\u0B35-\u0B39\u0B3D\u0B5C\u0B5D\u0B5F-\u0B61\u0B71\u0B83\u0B85-\u0B8A\u0B8E-\u0B90\u0B92-\u0B95\u0B99\u0B9A\u0B9C\u0B9E\u0B9F\u0BA3\u0BA4\u0BA8-\u0BAA\u0BAE-\u0BB9\u0BD0\u0C05-\u0C0C\u0C0E-\u0C10\u0C12-\u0C28\u0C2A-\u0C39\u0C3D\u0C58-\u0C5A\u0C60\u0C61\u0C80\u0C85-\u0C8C\u0C8E-\u0C90\u0C92-\u0CA8\u0CAA-\u0CB3\u0CB5-\u0CB9\u0CBD\u0CDE\u0CE0\u0CE1\u0CF1\u0CF2\u0D05-\u0D0C\u0D0E-\u0D10\u0D12-\u0D3A\u0D3D\u0D4E\u0D54-\u0D56\u0D5F-\u0D61\u0D7A-\u0D7F\u0D85-\u0D96\u0D9A-\u0DB1\u0DB3-\u0DBB\u0DBD\u0DC0-\u0DC6\u0E01-\u0E30\u0E32\u0E33\u0E40-\u0E46\u0E81\u0E82\u0E84\u0E87\u0E88\u0E8A\u0E8D\u0E94-\u0E97\u0E99-\u0E9F\u0EA1-\u0EA3\u0EA5\u0EA7\u0EAA\u0EAB\u0EAD-\u0EB0\u0EB2\u0EB3\u0EBD\u0EC0-\u0EC4\u0EC6\u0EDC-\u0EDF\u0F00\u0F40-\u0F47\u0F49-\u0F6C\u0F88-\u0F8C\u1000-\u102A\u103F\u1050-\u1055\u105A-\u105D\u1061\u1065\u1066\u106E-\u1070\u1075-\u1081\u108E\u10A0-\u10C5\u10C7\u10CD\u10D0-\u10FA\u10FC-\u1248\u124A-\u124D\u1250-\u1256\u1258\u125A-\u125D\u1260-\u1288\u128A-\u128D\u1290-\u12B0\u12B2-\u12B5\u12B8-\u12BE\u12C0\u12C2-\u12C5\u12C8-\u12D6\u12D8-\u1310\u1312-\u1315\u1318-\u135A\u1380-\u138F\u13A0-\u13F5\u13F8-\u13FD\u1401-\u166C\u166F-\u167F\u1681-\u169A\u16A0-\u16EA\u16EE-\u16F8\u1700-\u170C\u170E-\u1711\u1720-\u1731\u1740-\u1751\u1760-\u176C\u176E-\u1770\u1780-\u17B3\u17D7\u17DC\u1820-\u1877\u1880-\u1884\u1887-\u18A8\u18AA\u18B0-\u18F5\u1900-\u191E\u1950-\u196D\u1970-\u1974\u1980-\u19AB\u19B0-\u19C9\u1A00-\u1A16\u1A20-\u1A54\u1AA7\u1B05-\u1B33\u1B45-\u1B4B\u1B83-\u1BA0\u1BAE\u1BAF\u1BBA-\u1BE5\u1C00-\u1C23\u1C4D-\u1C4F\u1C5A-\u1C7D\u1C80-\u1C88\u1CE9-\u1CEC\u1CEE-\u1CF1\u1CF5\u1CF6\u1D00-\u1DBF\u1E00-\u1F15\u1F18-\u1F1D\u1F20-\u1F45\u1F48-\u1F4D\u1F50-\u1F57\u1F59\u1F5B\u1F5D\u1F5F-\u1F7D\u1F80-\u1FB4\u1FB6-\u1FBC\u1FBE\u1FC2-\u1FC4\u1FC6-\u1FCC\u1FD0-\u1FD3\u1FD6-\u1FDB\u1FE0-\u1FEC\u1FF2-\u1FF4\u1FF6-\u1FFC\u2071\u207F\u2090-\u209C\u2102\u2107\u210A-\u2113\u2115\u2119-\u211D\u2124\u2126\u2128\u212A-\u212D\u212F-\u2139\u213C-\u213F\u2145-\u2149\u214E\u2160-\u2188\u2C00-\u2C2E\u2C30-\u2C5E\u2C60-\u2CE4\u2CEB-\u2CEE\u2CF2\u2CF3\u2D00-\u2D25\u2D27\u2D2D\u2D30-\u2D67\u2D6F\u2D80-\u2D96\u2DA0-\u2DA6\u2DA8-\u2DAE\u2DB0-\u2DB6\u2DB8-\u2DBE\u2DC0-\u2DC6\u2DC8-\u2DCE\u2DD0-\u2DD6\u2DD8-\u2DDE\u2E2F\u3005-\u3007\u3021-\u3029\u3031-\u3035\u3038-\u303C\u3041-\u3096\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FF\u3105-\u312E\u3131-\u318E\u31A0-\u31BA\u31F0-\u31FF\u3400-\u4DB5\u4E00-\u9FEA\uA000-\uA48C\uA4D0-\uA4FD\uA500-\uA60C\uA610-\uA61F\uA62A\uA62B\uA640-\uA66E\uA67F-\uA69D\uA6A0-\uA6EF\uA717-\uA71F\uA722-\uA788\uA78B-\uA7AE\uA7B0-\uA7B7\uA7F7-\uA801\uA803-\uA805\uA807-\uA80A\uA80C-\uA822\uA840-\uA873\uA882-\uA8B3\uA8F2-\uA8F7\uA8FB\uA8FD\uA90A-\uA925\uA930-\uA946\uA960-\uA97C\uA984-\uA9B2\uA9CF\uA9E0-\uA9E4\uA9E6-\uA9EF\uA9FA-\uA9FE\uAA00-\uAA28\uAA40-\uAA42\uAA44-\uAA4B\uAA60-\uAA76\uAA7A\uAA7E-\uAAAF\uAAB1\uAAB5\uAAB6\uAAB9-\uAABD\uAAC0\uAAC2\uAADB-\uAADD\uAAE0-\uAAEA\uAAF2-\uAAF4\uAB01-\uAB06\uAB09-\uAB0E\uAB11-\uAB16\uAB20-\uAB26\uAB28-\uAB2E\uAB30-\uAB5A\uAB5C-\uAB65\uAB70-\uABE2\uAC00-\uD7A3\uD7B0-\uD7C6\uD7CB-\uD7FB\uF900-\uFA6D\uFA70-\uFAD9\uFB00-\uFB06\uFB13-\uFB17\uFB1D\uFB1F-\uFB28\uFB2A-\uFB36\uFB38-\uFB3C\uFB3E\uFB40\uFB41\uFB43\uFB44\uFB46-\uFBB1\uFBD3-\uFD3D\uFD50-\uFD8F\uFD92-\uFDC7\uFDF0-\uFDFB\uFE70-\uFE74\uFE76-\uFEFC\uFF21-\uFF3A\uFF41-\uFF5A\uFF66-\uFFBE\uFFC2-\uFFC7\uFFCA-\uFFCF\uFFD2-\uFFD7\uFFDA-\uFFDC]|\uD800[\uDC00-\uDC0B\uDC0D-\uDC26\uDC28-\uDC3A\uDC3C\uDC3D\uDC3F-\uDC4D\uDC50-\uDC5D\uDC80-\uDCFA\uDD40-\uDD74\uDE80-\uDE9C\uDEA0-\uDED0\uDF00-\uDF1F\uDF2D-\uDF4A\uDF50-\uDF75\uDF80-\uDF9D\uDFA0-\uDFC3\uDFC8-\uDFCF\uDFD1-\uDFD5]|\uD801[\uDC00-\uDC9D\uDCB0-\uDCD3\uDCD8-\uDCFB\uDD00-\uDD27\uDD30-\uDD63\uDE00-\uDF36\uDF40-\uDF55\uDF60-\uDF67]|\uD802[\uDC00-\uDC05\uDC08\uDC0A-\uDC35\uDC37\uDC38\uDC3C\uDC3F-\uDC55\uDC60-\uDC76\uDC80-\uDC9E\uDCE0-\uDCF2\uDCF4\uDCF5\uDD00-\uDD15\uDD20-\uDD39\uDD80-\uDDB7\uDDBE\uDDBF\uDE00\uDE10-\uDE13\uDE15-\uDE17\uDE19-\uDE33\uDE60-\uDE7C\uDE80-\uDE9C\uDEC0-\uDEC7\uDEC9-\uDEE4\uDF00-\uDF35\uDF40-\uDF55\uDF60-\uDF72\uDF80-\uDF91]|\uD803[\uDC00-\uDC48\uDC80-\uDCB2\uDCC0-\uDCF2]|\uD804[\uDC03-\uDC37\uDC83-\uDCAF\uDCD0-\uDCE8\uDD03-\uDD26\uDD50-\uDD72\uDD76\uDD83-\uDDB2\uDDC1-\uDDC4\uDDDA\uDDDC\uDE00-\uDE11\uDE13-\uDE2B\uDE80-\uDE86\uDE88\uDE8A-\uDE8D\uDE8F-\uDE9D\uDE9F-\uDEA8\uDEB0-\uDEDE\uDF05-\uDF0C\uDF0F\uDF10\uDF13-\uDF28\uDF2A-\uDF30\uDF32\uDF33\uDF35-\uDF39\uDF3D\uDF50\uDF5D-\uDF61]|\uD805[\uDC00-\uDC34\uDC47-\uDC4A\uDC80-\uDCAF\uDCC4\uDCC5\uDCC7\uDD80-\uDDAE\uDDD8-\uDDDB\uDE00-\uDE2F\uDE44\uDE80-\uDEAA\uDF00-\uDF19]|\uD806[\uDCA0-\uDCDF\uDCFF\uDE00\uDE0B-\uDE32\uDE3A\uDE50\uDE5C-\uDE83\uDE86-\uDE89\uDEC0-\uDEF8]|\uD807[\uDC00-\uDC08\uDC0A-\uDC2E\uDC40\uDC72-\uDC8F\uDD00-\uDD06\uDD08\uDD09\uDD0B-\uDD30\uDD46]|\uD808[\uDC00-\uDF99]|\uD809[\uDC00-\uDC6E\uDC80-\uDD43]|[\uD80C\uD81C-\uD820\uD840-\uD868\uD86A-\uD86C\uD86F-\uD872\uD874-\uD879][\uDC00-\uDFFF]|\uD80D[\uDC00-\uDC2E]|\uD811[\uDC00-\uDE46]|\uD81A[\uDC00-\uDE38\uDE40-\uDE5E\uDED0-\uDEED\uDF00-\uDF2F\uDF40-\uDF43\uDF63-\uDF77\uDF7D-\uDF8F]|\uD81B[\uDF00-\uDF44\uDF50\uDF93-\uDF9F\uDFE0\uDFE1]|\uD821[\uDC00-\uDFEC]|\uD822[\uDC00-\uDEF2]|\uD82C[\uDC00-\uDD1E\uDD70-\uDEFB]|\uD82F[\uDC00-\uDC6A\uDC70-\uDC7C\uDC80-\uDC88\uDC90-\uDC99]|\uD835[\uDC00-\uDC54\uDC56-\uDC9C\uDC9E\uDC9F\uDCA2\uDCA5\uDCA6\uDCA9-\uDCAC\uDCAE-\uDCB9\uDCBB\uDCBD-\uDCC3\uDCC5-\uDD05\uDD07-\uDD0A\uDD0D-\uDD14\uDD16-\uDD1C\uDD1E-\uDD39\uDD3B-\uDD3E\uDD40-\uDD44\uDD46\uDD4A-\uDD50\uDD52-\uDEA5\uDEA8-\uDEC0\uDEC2-\uDEDA\uDEDC-\uDEFA\uDEFC-\uDF14\uDF16-\uDF34\uDF36-\uDF4E\uDF50-\uDF6E\uDF70-\uDF88\uDF8A-\uDFA8\uDFAA-\uDFC2\uDFC4-\uDFCB]|\uD83A[\uDC00-\uDCC4\uDD00-\uDD43]|\uD83B[\uDE00-\uDE03\uDE05-\uDE1F\uDE21\uDE22\uDE24\uDE27\uDE29-\uDE32\uDE34-\uDE37\uDE39\uDE3B\uDE42\uDE47\uDE49\uDE4B\uDE4D-\uDE4F\uDE51\uDE52\uDE54\uDE57\uDE59\uDE5B\uDE5D\uDE5F\uDE61\uDE62\uDE64\uDE67-\uDE6A\uDE6C-\uDE72\uDE74-\uDE77\uDE79-\uDE7C\uDE7E\uDE80-\uDE89\uDE8B-\uDE9B\uDEA1-\uDEA3\uDEA5-\uDEA9\uDEAB-\uDEBB]|\uD869[\uDC00-\uDED6\uDF00-\uDFFF]|\uD86D[\uDC00-\uDF34\uDF40-\uDFFF]|\uD86E[\uDC00-\uDC1D\uDC20-\uDFFF]|\uD873[\uDC00-\uDEA1\uDEB0-\uDFFF]|\uD87A[\uDC00-\uDFE0]|\uD87E[\uDC00-\uDE1D]/,
			ID_Continue: /[\xAA\xB5\xBA\xC0-\xD6\xD8-\xF6\xF8-\u02C1\u02C6-\u02D1\u02E0-\u02E4\u02EC\u02EE\u0300-\u0374\u0376\u0377\u037A-\u037D\u037F\u0386\u0388-\u038A\u038C\u038E-\u03A1\u03A3-\u03F5\u03F7-\u0481\u0483-\u0487\u048A-\u052F\u0531-\u0556\u0559\u0561-\u0587\u0591-\u05BD\u05BF\u05C1\u05C2\u05C4\u05C5\u05C7\u05D0-\u05EA\u05F0-\u05F2\u0610-\u061A\u0620-\u0669\u066E-\u06D3\u06D5-\u06DC\u06DF-\u06E8\u06EA-\u06FC\u06FF\u0710-\u074A\u074D-\u07B1\u07C0-\u07F5\u07FA\u0800-\u082D\u0840-\u085B\u0860-\u086A\u08A0-\u08B4\u08B6-\u08BD\u08D4-\u08E1\u08E3-\u0963\u0966-\u096F\u0971-\u0983\u0985-\u098C\u098F\u0990\u0993-\u09A8\u09AA-\u09B0\u09B2\u09B6-\u09B9\u09BC-\u09C4\u09C7\u09C8\u09CB-\u09CE\u09D7\u09DC\u09DD\u09DF-\u09E3\u09E6-\u09F1\u09FC\u0A01-\u0A03\u0A05-\u0A0A\u0A0F\u0A10\u0A13-\u0A28\u0A2A-\u0A30\u0A32\u0A33\u0A35\u0A36\u0A38\u0A39\u0A3C\u0A3E-\u0A42\u0A47\u0A48\u0A4B-\u0A4D\u0A51\u0A59-\u0A5C\u0A5E\u0A66-\u0A75\u0A81-\u0A83\u0A85-\u0A8D\u0A8F-\u0A91\u0A93-\u0AA8\u0AAA-\u0AB0\u0AB2\u0AB3\u0AB5-\u0AB9\u0ABC-\u0AC5\u0AC7-\u0AC9\u0ACB-\u0ACD\u0AD0\u0AE0-\u0AE3\u0AE6-\u0AEF\u0AF9-\u0AFF\u0B01-\u0B03\u0B05-\u0B0C\u0B0F\u0B10\u0B13-\u0B28\u0B2A-\u0B30\u0B32\u0B33\u0B35-\u0B39\u0B3C-\u0B44\u0B47\u0B48\u0B4B-\u0B4D\u0B56\u0B57\u0B5C\u0B5D\u0B5F-\u0B63\u0B66-\u0B6F\u0B71\u0B82\u0B83\u0B85-\u0B8A\u0B8E-\u0B90\u0B92-\u0B95\u0B99\u0B9A\u0B9C\u0B9E\u0B9F\u0BA3\u0BA4\u0BA8-\u0BAA\u0BAE-\u0BB9\u0BBE-\u0BC2\u0BC6-\u0BC8\u0BCA-\u0BCD\u0BD0\u0BD7\u0BE6-\u0BEF\u0C00-\u0C03\u0C05-\u0C0C\u0C0E-\u0C10\u0C12-\u0C28\u0C2A-\u0C39\u0C3D-\u0C44\u0C46-\u0C48\u0C4A-\u0C4D\u0C55\u0C56\u0C58-\u0C5A\u0C60-\u0C63\u0C66-\u0C6F\u0C80-\u0C83\u0C85-\u0C8C\u0C8E-\u0C90\u0C92-\u0CA8\u0CAA-\u0CB3\u0CB5-\u0CB9\u0CBC-\u0CC4\u0CC6-\u0CC8\u0CCA-\u0CCD\u0CD5\u0CD6\u0CDE\u0CE0-\u0CE3\u0CE6-\u0CEF\u0CF1\u0CF2\u0D00-\u0D03\u0D05-\u0D0C\u0D0E-\u0D10\u0D12-\u0D44\u0D46-\u0D48\u0D4A-\u0D4E\u0D54-\u0D57\u0D5F-\u0D63\u0D66-\u0D6F\u0D7A-\u0D7F\u0D82\u0D83\u0D85-\u0D96\u0D9A-\u0DB1\u0DB3-\u0DBB\u0DBD\u0DC0-\u0DC6\u0DCA\u0DCF-\u0DD4\u0DD6\u0DD8-\u0DDF\u0DE6-\u0DEF\u0DF2\u0DF3\u0E01-\u0E3A\u0E40-\u0E4E\u0E50-\u0E59\u0E81\u0E82\u0E84\u0E87\u0E88\u0E8A\u0E8D\u0E94-\u0E97\u0E99-\u0E9F\u0EA1-\u0EA3\u0EA5\u0EA7\u0EAA\u0EAB\u0EAD-\u0EB9\u0EBB-\u0EBD\u0EC0-\u0EC4\u0EC6\u0EC8-\u0ECD\u0ED0-\u0ED9\u0EDC-\u0EDF\u0F00\u0F18\u0F19\u0F20-\u0F29\u0F35\u0F37\u0F39\u0F3E-\u0F47\u0F49-\u0F6C\u0F71-\u0F84\u0F86-\u0F97\u0F99-\u0FBC\u0FC6\u1000-\u1049\u1050-\u109D\u10A0-\u10C5\u10C7\u10CD\u10D0-\u10FA\u10FC-\u1248\u124A-\u124D\u1250-\u1256\u1258\u125A-\u125D\u1260-\u1288\u128A-\u128D\u1290-\u12B0\u12B2-\u12B5\u12B8-\u12BE\u12C0\u12C2-\u12C5\u12C8-\u12D6\u12D8-\u1310\u1312-\u1315\u1318-\u135A\u135D-\u135F\u1380-\u138F\u13A0-\u13F5\u13F8-\u13FD\u1401-\u166C\u166F-\u167F\u1681-\u169A\u16A0-\u16EA\u16EE-\u16F8\u1700-\u170C\u170E-\u1714\u1720-\u1734\u1740-\u1753\u1760-\u176C\u176E-\u1770\u1772\u1773\u1780-\u17D3\u17D7\u17DC\u17DD\u17E0-\u17E9\u180B-\u180D\u1810-\u1819\u1820-\u1877\u1880-\u18AA\u18B0-\u18F5\u1900-\u191E\u1920-\u192B\u1930-\u193B\u1946-\u196D\u1970-\u1974\u1980-\u19AB\u19B0-\u19C9\u19D0-\u19D9\u1A00-\u1A1B\u1A20-\u1A5E\u1A60-\u1A7C\u1A7F-\u1A89\u1A90-\u1A99\u1AA7\u1AB0-\u1ABD\u1B00-\u1B4B\u1B50-\u1B59\u1B6B-\u1B73\u1B80-\u1BF3\u1C00-\u1C37\u1C40-\u1C49\u1C4D-\u1C7D\u1C80-\u1C88\u1CD0-\u1CD2\u1CD4-\u1CF9\u1D00-\u1DF9\u1DFB-\u1F15\u1F18-\u1F1D\u1F20-\u1F45\u1F48-\u1F4D\u1F50-\u1F57\u1F59\u1F5B\u1F5D\u1F5F-\u1F7D\u1F80-\u1FB4\u1FB6-\u1FBC\u1FBE\u1FC2-\u1FC4\u1FC6-\u1FCC\u1FD0-\u1FD3\u1FD6-\u1FDB\u1FE0-\u1FEC\u1FF2-\u1FF4\u1FF6-\u1FFC\u203F\u2040\u2054\u2071\u207F\u2090-\u209C\u20D0-\u20DC\u20E1\u20E5-\u20F0\u2102\u2107\u210A-\u2113\u2115\u2119-\u211D\u2124\u2126\u2128\u212A-\u212D\u212F-\u2139\u213C-\u213F\u2145-\u2149\u214E\u2160-\u2188\u2C00-\u2C2E\u2C30-\u2C5E\u2C60-\u2CE4\u2CEB-\u2CF3\u2D00-\u2D25\u2D27\u2D2D\u2D30-\u2D67\u2D6F\u2D7F-\u2D96\u2DA0-\u2DA6\u2DA8-\u2DAE\u2DB0-\u2DB6\u2DB8-\u2DBE\u2DC0-\u2DC6\u2DC8-\u2DCE\u2DD0-\u2DD6\u2DD8-\u2DDE\u2DE0-\u2DFF\u2E2F\u3005-\u3007\u3021-\u302F\u3031-\u3035\u3038-\u303C\u3041-\u3096\u3099\u309A\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FF\u3105-\u312E\u3131-\u318E\u31A0-\u31BA\u31F0-\u31FF\u3400-\u4DB5\u4E00-\u9FEA\uA000-\uA48C\uA4D0-\uA4FD\uA500-\uA60C\uA610-\uA62B\uA640-\uA66F\uA674-\uA67D\uA67F-\uA6F1\uA717-\uA71F\uA722-\uA788\uA78B-\uA7AE\uA7B0-\uA7B7\uA7F7-\uA827\uA840-\uA873\uA880-\uA8C5\uA8D0-\uA8D9\uA8E0-\uA8F7\uA8FB\uA8FD\uA900-\uA92D\uA930-\uA953\uA960-\uA97C\uA980-\uA9C0\uA9CF-\uA9D9\uA9E0-\uA9FE\uAA00-\uAA36\uAA40-\uAA4D\uAA50-\uAA59\uAA60-\uAA76\uAA7A-\uAAC2\uAADB-\uAADD\uAAE0-\uAAEF\uAAF2-\uAAF6\uAB01-\uAB06\uAB09-\uAB0E\uAB11-\uAB16\uAB20-\uAB26\uAB28-\uAB2E\uAB30-\uAB5A\uAB5C-\uAB65\uAB70-\uABEA\uABEC\uABED\uABF0-\uABF9\uAC00-\uD7A3\uD7B0-\uD7C6\uD7CB-\uD7FB\uF900-\uFA6D\uFA70-\uFAD9\uFB00-\uFB06\uFB13-\uFB17\uFB1D-\uFB28\uFB2A-\uFB36\uFB38-\uFB3C\uFB3E\uFB40\uFB41\uFB43\uFB44\uFB46-\uFBB1\uFBD3-\uFD3D\uFD50-\uFD8F\uFD92-\uFDC7\uFDF0-\uFDFB\uFE00-\uFE0F\uFE20-\uFE2F\uFE33\uFE34\uFE4D-\uFE4F\uFE70-\uFE74\uFE76-\uFEFC\uFF10-\uFF19\uFF21-\uFF3A\uFF3F\uFF41-\uFF5A\uFF66-\uFFBE\uFFC2-\uFFC7\uFFCA-\uFFCF\uFFD2-\uFFD7\uFFDA-\uFFDC]|\uD800[\uDC00-\uDC0B\uDC0D-\uDC26\uDC28-\uDC3A\uDC3C\uDC3D\uDC3F-\uDC4D\uDC50-\uDC5D\uDC80-\uDCFA\uDD40-\uDD74\uDDFD\uDE80-\uDE9C\uDEA0-\uDED0\uDEE0\uDF00-\uDF1F\uDF2D-\uDF4A\uDF50-\uDF7A\uDF80-\uDF9D\uDFA0-\uDFC3\uDFC8-\uDFCF\uDFD1-\uDFD5]|\uD801[\uDC00-\uDC9D\uDCA0-\uDCA9\uDCB0-\uDCD3\uDCD8-\uDCFB\uDD00-\uDD27\uDD30-\uDD63\uDE00-\uDF36\uDF40-\uDF55\uDF60-\uDF67]|\uD802[\uDC00-\uDC05\uDC08\uDC0A-\uDC35\uDC37\uDC38\uDC3C\uDC3F-\uDC55\uDC60-\uDC76\uDC80-\uDC9E\uDCE0-\uDCF2\uDCF4\uDCF5\uDD00-\uDD15\uDD20-\uDD39\uDD80-\uDDB7\uDDBE\uDDBF\uDE00-\uDE03\uDE05\uDE06\uDE0C-\uDE13\uDE15-\uDE17\uDE19-\uDE33\uDE38-\uDE3A\uDE3F\uDE60-\uDE7C\uDE80-\uDE9C\uDEC0-\uDEC7\uDEC9-\uDEE6\uDF00-\uDF35\uDF40-\uDF55\uDF60-\uDF72\uDF80-\uDF91]|\uD803[\uDC00-\uDC48\uDC80-\uDCB2\uDCC0-\uDCF2]|\uD804[\uDC00-\uDC46\uDC66-\uDC6F\uDC7F-\uDCBA\uDCD0-\uDCE8\uDCF0-\uDCF9\uDD00-\uDD34\uDD36-\uDD3F\uDD50-\uDD73\uDD76\uDD80-\uDDC4\uDDCA-\uDDCC\uDDD0-\uDDDA\uDDDC\uDE00-\uDE11\uDE13-\uDE37\uDE3E\uDE80-\uDE86\uDE88\uDE8A-\uDE8D\uDE8F-\uDE9D\uDE9F-\uDEA8\uDEB0-\uDEEA\uDEF0-\uDEF9\uDF00-\uDF03\uDF05-\uDF0C\uDF0F\uDF10\uDF13-\uDF28\uDF2A-\uDF30\uDF32\uDF33\uDF35-\uDF39\uDF3C-\uDF44\uDF47\uDF48\uDF4B-\uDF4D\uDF50\uDF57\uDF5D-\uDF63\uDF66-\uDF6C\uDF70-\uDF74]|\uD805[\uDC00-\uDC4A\uDC50-\uDC59\uDC80-\uDCC5\uDCC7\uDCD0-\uDCD9\uDD80-\uDDB5\uDDB8-\uDDC0\uDDD8-\uDDDD\uDE00-\uDE40\uDE44\uDE50-\uDE59\uDE80-\uDEB7\uDEC0-\uDEC9\uDF00-\uDF19\uDF1D-\uDF2B\uDF30-\uDF39]|\uD806[\uDCA0-\uDCE9\uDCFF\uDE00-\uDE3E\uDE47\uDE50-\uDE83\uDE86-\uDE99\uDEC0-\uDEF8]|\uD807[\uDC00-\uDC08\uDC0A-\uDC36\uDC38-\uDC40\uDC50-\uDC59\uDC72-\uDC8F\uDC92-\uDCA7\uDCA9-\uDCB6\uDD00-\uDD06\uDD08\uDD09\uDD0B-\uDD36\uDD3A\uDD3C\uDD3D\uDD3F-\uDD47\uDD50-\uDD59]|\uD808[\uDC00-\uDF99]|\uD809[\uDC00-\uDC6E\uDC80-\uDD43]|[\uD80C\uD81C-\uD820\uD840-\uD868\uD86A-\uD86C\uD86F-\uD872\uD874-\uD879][\uDC00-\uDFFF]|\uD80D[\uDC00-\uDC2E]|\uD811[\uDC00-\uDE46]|\uD81A[\uDC00-\uDE38\uDE40-\uDE5E\uDE60-\uDE69\uDED0-\uDEED\uDEF0-\uDEF4\uDF00-\uDF36\uDF40-\uDF43\uDF50-\uDF59\uDF63-\uDF77\uDF7D-\uDF8F]|\uD81B[\uDF00-\uDF44\uDF50-\uDF7E\uDF8F-\uDF9F\uDFE0\uDFE1]|\uD821[\uDC00-\uDFEC]|\uD822[\uDC00-\uDEF2]|\uD82C[\uDC00-\uDD1E\uDD70-\uDEFB]|\uD82F[\uDC00-\uDC6A\uDC70-\uDC7C\uDC80-\uDC88\uDC90-\uDC99\uDC9D\uDC9E]|\uD834[\uDD65-\uDD69\uDD6D-\uDD72\uDD7B-\uDD82\uDD85-\uDD8B\uDDAA-\uDDAD\uDE42-\uDE44]|\uD835[\uDC00-\uDC54\uDC56-\uDC9C\uDC9E\uDC9F\uDCA2\uDCA5\uDCA6\uDCA9-\uDCAC\uDCAE-\uDCB9\uDCBB\uDCBD-\uDCC3\uDCC5-\uDD05\uDD07-\uDD0A\uDD0D-\uDD14\uDD16-\uDD1C\uDD1E-\uDD39\uDD3B-\uDD3E\uDD40-\uDD44\uDD46\uDD4A-\uDD50\uDD52-\uDEA5\uDEA8-\uDEC0\uDEC2-\uDEDA\uDEDC-\uDEFA\uDEFC-\uDF14\uDF16-\uDF34\uDF36-\uDF4E\uDF50-\uDF6E\uDF70-\uDF88\uDF8A-\uDFA8\uDFAA-\uDFC2\uDFC4-\uDFCB\uDFCE-\uDFFF]|\uD836[\uDE00-\uDE36\uDE3B-\uDE6C\uDE75\uDE84\uDE9B-\uDE9F\uDEA1-\uDEAF]|\uD838[\uDC00-\uDC06\uDC08-\uDC18\uDC1B-\uDC21\uDC23\uDC24\uDC26-\uDC2A]|\uD83A[\uDC00-\uDCC4\uDCD0-\uDCD6\uDD00-\uDD4A\uDD50-\uDD59]|\uD83B[\uDE00-\uDE03\uDE05-\uDE1F\uDE21\uDE22\uDE24\uDE27\uDE29-\uDE32\uDE34-\uDE37\uDE39\uDE3B\uDE42\uDE47\uDE49\uDE4B\uDE4D-\uDE4F\uDE51\uDE52\uDE54\uDE57\uDE59\uDE5B\uDE5D\uDE5F\uDE61\uDE62\uDE64\uDE67-\uDE6A\uDE6C-\uDE72\uDE74-\uDE77\uDE79-\uDE7C\uDE7E\uDE80-\uDE89\uDE8B-\uDE9B\uDEA1-\uDEA3\uDEA5-\uDEA9\uDEAB-\uDEBB]|\uD869[\uDC00-\uDED6\uDF00-\uDFFF]|\uD86D[\uDC00-\uDF34\uDF40-\uDFFF]|\uD86E[\uDC00-\uDC1D\uDC20-\uDFFF]|\uD873[\uDC00-\uDEA1\uDEB0-\uDFFF]|\uD87A[\uDC00-\uDFE0]|\uD87E[\uDC00-\uDE1D]|\uDB40[\uDD00-\uDDEF]/
		};
		var util = {
			isSpaceSeparator: function isSpaceSeparator(c) {
				return typeof c === "string" && unicode.Space_Separator.test(c);
			},
			isIdStartChar: function isIdStartChar(c) {
				return typeof c === "string" && (c >= "a" && c <= "z" || c >= "A" && c <= "Z" || c === "$" || c === "_" || unicode.ID_Start.test(c));
			},
			isIdContinueChar: function isIdContinueChar(c) {
				return typeof c === "string" && (c >= "a" && c <= "z" || c >= "A" && c <= "Z" || c >= "0" && c <= "9" || c === "$" || c === "_" || c === "‌" || c === "‍" || unicode.ID_Continue.test(c));
			},
			isDigit: function isDigit(c) {
				return typeof c === "string" && /[0-9]/.test(c);
			},
			isHexDigit: function isHexDigit(c) {
				return typeof c === "string" && /[0-9A-Fa-f]/.test(c);
			}
		};
		var source;
		var parseState;
		var stack;
		var pos;
		var line;
		var column;
		var token;
		var key;
		var root;
		var parse = function parse(text, reviver) {
			source = String(text);
			parseState = "start";
			stack = [];
			pos = 0;
			line = 1;
			column = 0;
			token = void 0;
			key = void 0;
			root = void 0;
			do {
				token = lex();
				parseStates[parseState]();
			} while (token.type !== "eof");
			if (typeof reviver === "function") return internalize({ "": root }, "", reviver);
			return root;
		};
		function internalize(holder, name, reviver) {
			var value = holder[name];
			if (value != null && typeof value === "object") {
				if (Array.isArray(value)) for (var i = 0; i < value.length; i++) {
					var key = String(i);
					var replacement = internalize(value, key, reviver);
					if (replacement === void 0) delete value[key];
					else Object.defineProperty(value, key, {
						value: replacement,
						writable: true,
						enumerable: true,
						configurable: true
					});
				}
				else for (var key$1 in value) {
					var replacement$1 = internalize(value, key$1, reviver);
					if (replacement$1 === void 0) delete value[key$1];
					else Object.defineProperty(value, key$1, {
						value: replacement$1,
						writable: true,
						enumerable: true,
						configurable: true
					});
				}
			}
			return reviver.call(holder, name, value);
		}
		var lexState;
		var buffer;
		var doubleQuote;
		var sign;
		var c;
		function lex() {
			lexState = "default";
			buffer = "";
			doubleQuote = false;
			sign = 1;
			for (;;) {
				c = peek();
				var token = lexStates[lexState]();
				if (token) return token;
			}
		}
		function peek() {
			if (source[pos]) return String.fromCodePoint(source.codePointAt(pos));
		}
		function read() {
			var c = peek();
			if (c === "\n") {
				line++;
				column = 0;
			} else if (c) column += c.length;
			else column++;
			if (c) pos += c.length;
			return c;
		}
		var lexStates = {
			default: function default$1() {
				switch (c) {
					case "	":
					case "\v":
					case "\f":
					case " ":
					case "\xA0":
					case "﻿":
					case "\n":
					case "\r":
					case "\u2028":
					case "\u2029":
						read();
						return;
					case "/":
						read();
						lexState = "comment";
						return;
					case void 0:
						read();
						return newToken("eof");
				}
				if (util.isSpaceSeparator(c)) {
					read();
					return;
				}
				return lexStates[parseState]();
			},
			comment: function comment() {
				switch (c) {
					case "*":
						read();
						lexState = "multiLineComment";
						return;
					case "/":
						read();
						lexState = "singleLineComment";
						return;
				}
				throw invalidChar(read());
			},
			multiLineComment: function multiLineComment() {
				switch (c) {
					case "*":
						read();
						lexState = "multiLineCommentAsterisk";
						return;
					case void 0: throw invalidChar(read());
				}
				read();
			},
			multiLineCommentAsterisk: function multiLineCommentAsterisk() {
				switch (c) {
					case "*":
						read();
						return;
					case "/":
						read();
						lexState = "default";
						return;
					case void 0: throw invalidChar(read());
				}
				read();
				lexState = "multiLineComment";
			},
			singleLineComment: function singleLineComment() {
				switch (c) {
					case "\n":
					case "\r":
					case "\u2028":
					case "\u2029":
						read();
						lexState = "default";
						return;
					case void 0:
						read();
						return newToken("eof");
				}
				read();
			},
			value: function value() {
				switch (c) {
					case "{":
					case "[": return newToken("punctuator", read());
					case "n":
						read();
						literal("ull");
						return newToken("null", null);
					case "t":
						read();
						literal("rue");
						return newToken("boolean", true);
					case "f":
						read();
						literal("alse");
						return newToken("boolean", false);
					case "-":
					case "+":
						if (read() === "-") sign = -1;
						lexState = "sign";
						return;
					case ".":
						buffer = read();
						lexState = "decimalPointLeading";
						return;
					case "0":
						buffer = read();
						lexState = "zero";
						return;
					case "1":
					case "2":
					case "3":
					case "4":
					case "5":
					case "6":
					case "7":
					case "8":
					case "9":
						buffer = read();
						lexState = "decimalInteger";
						return;
					case "I":
						read();
						literal("nfinity");
						return newToken("numeric", Infinity);
					case "N":
						read();
						literal("aN");
						return newToken("numeric", NaN);
					case "\"":
					case "'":
						doubleQuote = read() === "\"";
						buffer = "";
						lexState = "string";
						return;
				}
				throw invalidChar(read());
			},
			identifierNameStartEscape: function identifierNameStartEscape() {
				if (c !== "u") throw invalidChar(read());
				read();
				var u = unicodeEscape();
				switch (u) {
					case "$":
					case "_": break;
					default: if (!util.isIdStartChar(u)) throw invalidIdentifier();
				}
				buffer += u;
				lexState = "identifierName";
			},
			identifierName: function identifierName() {
				switch (c) {
					case "$":
					case "_":
					case "‌":
					case "‍":
						buffer += read();
						return;
					case "\\":
						read();
						lexState = "identifierNameEscape";
						return;
				}
				if (util.isIdContinueChar(c)) {
					buffer += read();
					return;
				}
				return newToken("identifier", buffer);
			},
			identifierNameEscape: function identifierNameEscape() {
				if (c !== "u") throw invalidChar(read());
				read();
				var u = unicodeEscape();
				switch (u) {
					case "$":
					case "_":
					case "‌":
					case "‍": break;
					default: if (!util.isIdContinueChar(u)) throw invalidIdentifier();
				}
				buffer += u;
				lexState = "identifierName";
			},
			sign: function sign$1() {
				switch (c) {
					case ".":
						buffer = read();
						lexState = "decimalPointLeading";
						return;
					case "0":
						buffer = read();
						lexState = "zero";
						return;
					case "1":
					case "2":
					case "3":
					case "4":
					case "5":
					case "6":
					case "7":
					case "8":
					case "9":
						buffer = read();
						lexState = "decimalInteger";
						return;
					case "I":
						read();
						literal("nfinity");
						return newToken("numeric", sign * Infinity);
					case "N":
						read();
						literal("aN");
						return newToken("numeric", NaN);
				}
				throw invalidChar(read());
			},
			zero: function zero() {
				switch (c) {
					case ".":
						buffer += read();
						lexState = "decimalPoint";
						return;
					case "e":
					case "E":
						buffer += read();
						lexState = "decimalExponent";
						return;
					case "x":
					case "X":
						buffer += read();
						lexState = "hexadecimal";
						return;
				}
				return newToken("numeric", sign * 0);
			},
			decimalInteger: function decimalInteger() {
				switch (c) {
					case ".":
						buffer += read();
						lexState = "decimalPoint";
						return;
					case "e":
					case "E":
						buffer += read();
						lexState = "decimalExponent";
						return;
				}
				if (util.isDigit(c)) {
					buffer += read();
					return;
				}
				return newToken("numeric", sign * Number(buffer));
			},
			decimalPointLeading: function decimalPointLeading() {
				if (util.isDigit(c)) {
					buffer += read();
					lexState = "decimalFraction";
					return;
				}
				throw invalidChar(read());
			},
			decimalPoint: function decimalPoint() {
				switch (c) {
					case "e":
					case "E":
						buffer += read();
						lexState = "decimalExponent";
						return;
				}
				if (util.isDigit(c)) {
					buffer += read();
					lexState = "decimalFraction";
					return;
				}
				return newToken("numeric", sign * Number(buffer));
			},
			decimalFraction: function decimalFraction() {
				switch (c) {
					case "e":
					case "E":
						buffer += read();
						lexState = "decimalExponent";
						return;
				}
				if (util.isDigit(c)) {
					buffer += read();
					return;
				}
				return newToken("numeric", sign * Number(buffer));
			},
			decimalExponent: function decimalExponent() {
				switch (c) {
					case "+":
					case "-":
						buffer += read();
						lexState = "decimalExponentSign";
						return;
				}
				if (util.isDigit(c)) {
					buffer += read();
					lexState = "decimalExponentInteger";
					return;
				}
				throw invalidChar(read());
			},
			decimalExponentSign: function decimalExponentSign() {
				if (util.isDigit(c)) {
					buffer += read();
					lexState = "decimalExponentInteger";
					return;
				}
				throw invalidChar(read());
			},
			decimalExponentInteger: function decimalExponentInteger() {
				if (util.isDigit(c)) {
					buffer += read();
					return;
				}
				return newToken("numeric", sign * Number(buffer));
			},
			hexadecimal: function hexadecimal() {
				if (util.isHexDigit(c)) {
					buffer += read();
					lexState = "hexadecimalInteger";
					return;
				}
				throw invalidChar(read());
			},
			hexadecimalInteger: function hexadecimalInteger() {
				if (util.isHexDigit(c)) {
					buffer += read();
					return;
				}
				return newToken("numeric", sign * Number(buffer));
			},
			string: function string() {
				switch (c) {
					case "\\":
						read();
						buffer += escape();
						return;
					case "\"":
						if (doubleQuote) {
							read();
							return newToken("string", buffer);
						}
						buffer += read();
						return;
					case "'":
						if (!doubleQuote) {
							read();
							return newToken("string", buffer);
						}
						buffer += read();
						return;
					case "\n":
					case "\r": throw invalidChar(read());
					case "\u2028":
					case "\u2029":
						separatorChar(c);
						break;
					case void 0: throw invalidChar(read());
				}
				buffer += read();
			},
			start: function start() {
				switch (c) {
					case "{":
					case "[": return newToken("punctuator", read());
				}
				lexState = "value";
			},
			beforePropertyName: function beforePropertyName() {
				switch (c) {
					case "$":
					case "_":
						buffer = read();
						lexState = "identifierName";
						return;
					case "\\":
						read();
						lexState = "identifierNameStartEscape";
						return;
					case "}": return newToken("punctuator", read());
					case "\"":
					case "'":
						doubleQuote = read() === "\"";
						lexState = "string";
						return;
				}
				if (util.isIdStartChar(c)) {
					buffer += read();
					lexState = "identifierName";
					return;
				}
				throw invalidChar(read());
			},
			afterPropertyName: function afterPropertyName() {
				if (c === ":") return newToken("punctuator", read());
				throw invalidChar(read());
			},
			beforePropertyValue: function beforePropertyValue() {
				lexState = "value";
			},
			afterPropertyValue: function afterPropertyValue() {
				switch (c) {
					case ",":
					case "}": return newToken("punctuator", read());
				}
				throw invalidChar(read());
			},
			beforeArrayValue: function beforeArrayValue() {
				if (c === "]") return newToken("punctuator", read());
				lexState = "value";
			},
			afterArrayValue: function afterArrayValue() {
				switch (c) {
					case ",":
					case "]": return newToken("punctuator", read());
				}
				throw invalidChar(read());
			},
			end: function end() {
				throw invalidChar(read());
			}
		};
		function newToken(type, value) {
			return {
				type,
				value,
				line,
				column
			};
		}
		function literal(s) {
			for (var i = 0, list = s; i < list.length; i += 1) {
				var c = list[i];
				if (peek() !== c) throw invalidChar(read());
				read();
			}
		}
		function escape() {
			switch (peek()) {
				case "b":
					read();
					return "\b";
				case "f":
					read();
					return "\f";
				case "n":
					read();
					return "\n";
				case "r":
					read();
					return "\r";
				case "t":
					read();
					return "	";
				case "v":
					read();
					return "\v";
				case "0":
					read();
					if (util.isDigit(peek())) throw invalidChar(read());
					return "\0";
				case "x":
					read();
					return hexEscape();
				case "u":
					read();
					return unicodeEscape();
				case "\n":
				case "\u2028":
				case "\u2029":
					read();
					return "";
				case "\r":
					read();
					if (peek() === "\n") read();
					return "";
				case "1":
				case "2":
				case "3":
				case "4":
				case "5":
				case "6":
				case "7":
				case "8":
				case "9": throw invalidChar(read());
				case void 0: throw invalidChar(read());
			}
			return read();
		}
		function hexEscape() {
			var buffer = "";
			var c = peek();
			if (!util.isHexDigit(c)) throw invalidChar(read());
			buffer += read();
			c = peek();
			if (!util.isHexDigit(c)) throw invalidChar(read());
			buffer += read();
			return String.fromCodePoint(parseInt(buffer, 16));
		}
		function unicodeEscape() {
			var buffer = "";
			var count = 4;
			while (count-- > 0) {
				var c = peek();
				if (!util.isHexDigit(c)) throw invalidChar(read());
				buffer += read();
			}
			return String.fromCodePoint(parseInt(buffer, 16));
		}
		var parseStates = {
			start: function start() {
				if (token.type === "eof") throw invalidEOF();
				push();
			},
			beforePropertyName: function beforePropertyName() {
				switch (token.type) {
					case "identifier":
					case "string":
						key = token.value;
						parseState = "afterPropertyName";
						return;
					case "punctuator":
						pop();
						return;
					case "eof": throw invalidEOF();
				}
			},
			afterPropertyName: function afterPropertyName() {
				if (token.type === "eof") throw invalidEOF();
				parseState = "beforePropertyValue";
			},
			beforePropertyValue: function beforePropertyValue() {
				if (token.type === "eof") throw invalidEOF();
				push();
			},
			beforeArrayValue: function beforeArrayValue() {
				if (token.type === "eof") throw invalidEOF();
				if (token.type === "punctuator" && token.value === "]") {
					pop();
					return;
				}
				push();
			},
			afterPropertyValue: function afterPropertyValue() {
				if (token.type === "eof") throw invalidEOF();
				switch (token.value) {
					case ",":
						parseState = "beforePropertyName";
						return;
					case "}": pop();
				}
			},
			afterArrayValue: function afterArrayValue() {
				if (token.type === "eof") throw invalidEOF();
				switch (token.value) {
					case ",":
						parseState = "beforeArrayValue";
						return;
					case "]": pop();
				}
			},
			end: function end() {}
		};
		function push() {
			var value;
			switch (token.type) {
				case "punctuator":
					switch (token.value) {
						case "{":
							value = {};
							break;
						case "[": value = [];
					}
					break;
				case "null":
				case "boolean":
				case "numeric":
				case "string": value = token.value;
			}
			if (root === void 0) root = value;
			else {
				var parent = stack[stack.length - 1];
				if (Array.isArray(parent)) parent.push(value);
				else Object.defineProperty(parent, key, {
					value,
					writable: true,
					enumerable: true,
					configurable: true
				});
			}
			if (value !== null && typeof value === "object") {
				stack.push(value);
				if (Array.isArray(value)) parseState = "beforeArrayValue";
				else parseState = "beforePropertyName";
			} else {
				var current = stack[stack.length - 1];
				if (current == null) parseState = "end";
				else if (Array.isArray(current)) parseState = "afterArrayValue";
				else parseState = "afterPropertyValue";
			}
		}
		function pop() {
			stack.pop();
			var current = stack[stack.length - 1];
			if (current == null) parseState = "end";
			else if (Array.isArray(current)) parseState = "afterArrayValue";
			else parseState = "afterPropertyValue";
		}
		function invalidChar(c) {
			if (c === void 0) return syntaxError("JSON5: invalid end of input at " + line + ":" + column);
			return syntaxError("JSON5: invalid character '" + formatChar(c) + "' at " + line + ":" + column);
		}
		function invalidEOF() {
			return syntaxError("JSON5: invalid end of input at " + line + ":" + column);
		}
		function invalidIdentifier() {
			column -= 5;
			return syntaxError("JSON5: invalid identifier character at " + line + ":" + column);
		}
		function separatorChar(c) {
			console.warn("JSON5: '" + formatChar(c) + "' in strings is not valid ECMAScript; consider escaping");
		}
		function formatChar(c) {
			var replacements = {
				"'": "\\'",
				"\"": "\\\"",
				"\\": "\\\\",
				"\b": "\\b",
				"\f": "\\f",
				"\n": "\\n",
				"\r": "\\r",
				"	": "\\t",
				"\v": "\\v",
				"\0": "\\0",
				"\u2028": "\\u2028",
				"\u2029": "\\u2029"
			};
			if (replacements[c]) return replacements[c];
			if (c < " ") {
				var hexString = c.charCodeAt(0).toString(16);
				return "\\x" + ("00" + hexString).substring(hexString.length);
			}
			return c;
		}
		function syntaxError(message) {
			var err = new SyntaxError(message);
			err.lineNumber = line;
			err.columnNumber = column;
			return err;
		}
		return {
			parse,
			stringify: function stringify(value, replacer, space) {
				var stack = [];
				var indent = "";
				var propertyList;
				var replacerFunc;
				var gap = "";
				var quote;
				if (replacer != null && typeof replacer === "object" && !Array.isArray(replacer)) {
					space = replacer.space;
					quote = replacer.quote;
					replacer = replacer.replacer;
				}
				if (typeof replacer === "function") replacerFunc = replacer;
				else if (Array.isArray(replacer)) {
					propertyList = [];
					for (var i = 0, list = replacer; i < list.length; i += 1) {
						var v = list[i];
						var item = void 0;
						if (typeof v === "string") item = v;
						else if (typeof v === "number" || v instanceof String || v instanceof Number) item = String(v);
						if (item !== void 0 && propertyList.indexOf(item) < 0) propertyList.push(item);
					}
				}
				if (space instanceof Number) space = Number(space);
				else if (space instanceof String) space = String(space);
				if (typeof space === "number") {
					if (space > 0) {
						space = Math.min(10, Math.floor(space));
						gap = "          ".substr(0, space);
					}
				} else if (typeof space === "string") gap = space.substr(0, 10);
				return serializeProperty("", { "": value });
				function serializeProperty(key, holder) {
					var value = holder[key];
					if (value != null) {
						if (typeof value.toJSON5 === "function") value = value.toJSON5(key);
						else if (typeof value.toJSON === "function") value = value.toJSON(key);
					}
					if (replacerFunc) value = replacerFunc.call(holder, key, value);
					if (value instanceof Number) value = Number(value);
					else if (value instanceof String) value = String(value);
					else if (value instanceof Boolean) value = value.valueOf();
					switch (value) {
						case null: return "null";
						case true: return "true";
						case false: return "false";
					}
					if (typeof value === "string") return quoteString(value, false);
					if (typeof value === "number") return String(value);
					if (typeof value === "object") return Array.isArray(value) ? serializeArray(value) : serializeObject(value);
				}
				function quoteString(value) {
					var quotes = {
						"'": .1,
						"\"": .2
					};
					var replacements = {
						"'": "\\'",
						"\"": "\\\"",
						"\\": "\\\\",
						"\b": "\\b",
						"\f": "\\f",
						"\n": "\\n",
						"\r": "\\r",
						"	": "\\t",
						"\v": "\\v",
						"\0": "\\0",
						"\u2028": "\\u2028",
						"\u2029": "\\u2029"
					};
					var product = "";
					for (var i = 0; i < value.length; i++) {
						var c = value[i];
						switch (c) {
							case "'":
							case "\"":
								quotes[c]++;
								product += c;
								continue;
							case "\0": if (util.isDigit(value[i + 1])) {
								product += "\\x00";
								continue;
							}
						}
						if (replacements[c]) {
							product += replacements[c];
							continue;
						}
						if (c < " ") {
							var hexString = c.charCodeAt(0).toString(16);
							product += "\\x" + ("00" + hexString).substring(hexString.length);
							continue;
						}
						product += c;
					}
					var quoteChar = quote || Object.keys(quotes).reduce(function(a, b) {
						return quotes[a] < quotes[b] ? a : b;
					});
					product = product.replace(new RegExp(quoteChar, "g"), replacements[quoteChar]);
					return quoteChar + product + quoteChar;
				}
				function serializeObject(value) {
					if (stack.indexOf(value) >= 0) throw TypeError("Converting circular structure to JSON5");
					stack.push(value);
					var stepback = indent;
					indent = indent + gap;
					var keys = propertyList || Object.keys(value);
					var partial = [];
					for (var i = 0, list = keys; i < list.length; i += 1) {
						var key = list[i];
						var propertyString = serializeProperty(key, value);
						if (propertyString !== void 0) {
							var member = serializeKey(key) + ":";
							if (gap !== "") member += " ";
							member += propertyString;
							partial.push(member);
						}
					}
					var final;
					if (partial.length === 0) final = "{}";
					else {
						var properties;
						if (gap === "") {
							properties = partial.join(",");
							final = "{" + properties + "}";
						} else {
							var separator = ",\n" + indent;
							properties = partial.join(separator);
							final = "{\n" + indent + properties + ",\n" + stepback + "}";
						}
					}
					stack.pop();
					indent = stepback;
					return final;
				}
				function serializeKey(key) {
					if (key.length === 0) return quoteString(key, true);
					var firstChar = String.fromCodePoint(key.codePointAt(0));
					if (!util.isIdStartChar(firstChar)) return quoteString(key, true);
					for (var i = firstChar.length; i < key.length; i++) if (!util.isIdContinueChar(String.fromCodePoint(key.codePointAt(i)))) return quoteString(key, true);
					return key;
				}
				function serializeArray(value) {
					if (stack.indexOf(value) >= 0) throw TypeError("Converting circular structure to JSON5");
					stack.push(value);
					var stepback = indent;
					indent = indent + gap;
					var partial = [];
					for (var i = 0; i < value.length; i++) {
						var propertyString = serializeProperty(String(i), value);
						partial.push(propertyString !== void 0 ? propertyString : "null");
					}
					var final;
					if (partial.length === 0) final = "[]";
					else if (gap === "") final = "[" + partial.join(",") + "]";
					else {
						var separator = ",\n" + indent;
						var properties$1 = partial.join(separator);
						final = "[\n" + indent + properties$1 + ",\n" + stepback + "]";
					}
					stack.pop();
					indent = stepback;
					return final;
				}
			}
		};
	}));
}));
//#endregion
//#region ../../packages/util/src/json-worker.ts
var import_dist = /* @__PURE__ */ __toESM(require_dist(), 1);
var JsonWorkerPool = class {
	workers = [];
	blobURL = null;
	nextRequestId = 0;
	pendingRequests = /* @__PURE__ */ new Map();
	poolSize = 4;
	ensureWorkers() {
		if (this.workers.length === 0) {
			const blob = new Blob([kWorkerCode], { type: "application/javascript" });
			this.blobURL = URL.createObjectURL(blob);
			for (let i = 0; i < this.poolSize; i++) this.workers.push(this.createWorker(this.blobURL));
		}
	}
	createWorker(blobURL) {
		const worker = new Worker(blobURL);
		worker.onmessage = (e) => this.handleMessage(e);
		worker.onerror = (error) => this.failWorker(worker, /* @__PURE__ */ new Error(`Worker error: ${error.message}`));
		worker.onmessageerror = () => this.rejectPendingFor(worker, /* @__PURE__ */ new Error("Worker response could not be deserialized"));
		worker.postMessage({
			type: "init",
			scriptContent: kJson5ScriptBase64
		});
		return worker;
	}
	handleMessage(e) {
		const { requestId, success, result, reparse, sourceText, nonFinitePaths, sentinels, error, stack } = e.data;
		const pending = this.pendingRequests.get(requestId);
		if (!pending) return;
		this.pendingRequests.delete(requestId);
		if (success) {
			if (reparse) try {
				const parsed = JSON.parse(sourceText ?? pending.sourceText ?? "");
				if (nonFinitePaths && sentinels) applyNonFinitePaths(parsed, nonFinitePaths, sentinels);
				pending.resolve(parsed);
			} catch (parseError) {
				pending.reject(parseError);
			}
			else pending.resolve(result);
		} else {
			const err = new Error(error);
			if (stack) err.stack = stack;
			pending.reject(err);
		}
	}
	rejectPendingFor(worker, err) {
		for (const [requestId, pending] of this.pendingRequests) if (pending.worker === worker) {
			this.pendingRequests.delete(requestId);
			pending.reject(err);
		}
	}
	failWorker(worker, err) {
		this.rejectPendingFor(worker, err);
		const index = this.workers.indexOf(worker);
		worker.terminate();
		if (index >= 0 && this.blobURL) this.workers[index] = this.createWorker(this.blobURL);
	}
	async parse(text) {
		return this.submit({ text }, [], text);
	}
	async parseBytes(data) {
		const owned = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength && data.buffer instanceof ArrayBuffer ? new Uint8Array(data.buffer) : data.slice();
		return this.submit({ bytes: owned }, [owned.buffer]);
	}
	pickWorker() {
		const inflight = /* @__PURE__ */ new Map();
		for (const pending of this.pendingRequests.values()) inflight.set(pending.worker, (inflight.get(pending.worker) ?? 0) + 1);
		let best = this.workers[this.nextRequestId % this.workers.length];
		let bestCount = inflight.get(best) ?? 0;
		for (const worker of this.workers) {
			const count = inflight.get(worker) ?? 0;
			if (count < bestCount) {
				best = worker;
				bestCount = count;
			}
		}
		return best;
	}
	submit(payload, transfer = [], sourceText) {
		this.ensureWorkers();
		const requestId = this.nextRequestId++;
		const worker = this.pickWorker();
		return new Promise((resolve, reject) => {
			this.pendingRequests.set(requestId, {
				resolve,
				reject,
				worker,
				sourceText
			});
			try {
				worker.postMessage({
					type: "parse",
					requestId,
					...payload
				}, transfer);
			} catch (postError) {
				this.pendingRequests.delete(requestId);
				reject(postError instanceof Error ? postError : new Error(String(postError)));
			}
		});
	}
	terminate() {
		this.workers.forEach((w) => w.terminate());
		this.workers = [];
		if (this.blobURL) {
			URL.revokeObjectURL(this.blobURL);
			this.blobURL = null;
		}
		const err = /* @__PURE__ */ new Error("Worker pool terminated");
		for (const pending of this.pendingRequests.values()) pending.reject(err);
		this.pendingRequests.clear();
	}
};
var kReparseThresholdChars = 1e7;
var repairNonFiniteJson = (source, nanToken, infToken, negInfToken) => {
	const n = source.length;
	const parts = [];
	let copied = 0;
	let i = 0;
	const isKeyPosition = (after) => {
		let j = after;
		while (j < n) {
			const w = source.charCodeAt(j);
			if (w === 32 || w === 9 || w === 10 || w === 13) j++;
			else return w === 58;
		}
		return false;
	};
	while (i < n) {
		const c = source.charCodeAt(i);
		if (c === 34) {
			i++;
			while (i < n) {
				const s = source.charCodeAt(i);
				if (s === 92) i += 2;
				else if (s === 34) break;
				else i++;
			}
			i++;
			continue;
		}
		if (c === 78) {
			if (!source.startsWith("NaN", i) || isKeyPosition(i + 3)) return null;
			parts.push(source.slice(copied, i), nanToken);
			i += 3;
			copied = i;
			continue;
		}
		if (c === 73) {
			if (!source.startsWith("Infinity", i) || isKeyPosition(i + 8)) return null;
			parts.push(source.slice(copied, i), infToken);
			i += 8;
			copied = i;
			continue;
		}
		if (c === 45) {
			if (source.startsWith("-Infinity", i)) {
				if (isKeyPosition(i + 9)) return null;
				parts.push(source.slice(copied, i), negInfToken);
				i += 9;
				copied = i;
			} else i++;
			continue;
		}
		if (c === 116) {
			if (!source.startsWith("true", i)) return null;
			i += 4;
			continue;
		}
		if (c === 102) {
			if (!source.startsWith("false", i)) return null;
			i += 5;
			continue;
		}
		if (c === 110) {
			if (!source.startsWith("null", i)) return null;
			i += 4;
			continue;
		}
		if (c === 32 || c === 9 || c === 10 || c === 13 || c === 44 || c === 58 || c === 123 || c === 125 || c === 91 || c === 93 || c >= 48 && c <= 57 || c === 46 || c === 101 || c === 69 || c === 43) {
			i++;
			continue;
		}
		return null;
	}
	if (parts.length === 0) return null;
	parts.push(source.slice(copied));
	return parts.join("");
};
var applyNonFinitePaths = (root, paths, sentinels) => {
	const isRecord = (v) => typeof v === "object" && v !== null;
	for (const path of paths) {
		let target = root;
		for (let i = 0; i < path.length - 1; i++) {
			if (!isRecord(target)) break;
			target = target[path[i]];
		}
		if (!isRecord(target)) continue;
		const leaf = path[path.length - 1];
		const value = target[leaf];
		target[leaf] = value === sentinels.nan ? NaN : value === sentinels.inf ? Infinity : value === sentinels.ninf ? -Infinity : value;
	}
};
var findSentinelPaths = (root, sentinels, maxPaths) => {
	const isRecord = (v) => typeof v === "object" && v !== null;
	const paths = [];
	const stack = [{
		node: root,
		key: null,
		prev: null
	}];
	while (stack.length > 0) {
		const frame = stack.pop();
		const node = frame.node;
		if (typeof node === "string") {
			if (node === sentinels.nan || node === sentinels.inf || node === sentinels.ninf) {
				if (paths.length >= maxPaths) return null;
				const path = [];
				for (let f = frame; f && f.key !== null; f = f.prev) path.push(f.key);
				path.reverse();
				paths.push(path);
			}
		} else if (Array.isArray(node)) for (let i = 0; i < node.length; i++) {
			const v = node[i];
			if (typeof v === "string" || v && typeof v === "object") stack.push({
				node: v,
				key: i,
				prev: frame
			});
		}
		else if (isRecord(node)) for (const key of Object.keys(node)) {
			const v = node[key];
			if (typeof v === "string" || v && typeof v === "object") stack.push({
				node: v,
				key,
				prev: frame
			});
		}
	}
	return paths;
};
var replaceSentinelsInPlace = (root, sentinels) => {
	const isRecord = (v) => typeof v === "object" && v !== null;
	const restore = (v) => v === sentinels.nan ? NaN : v === sentinels.inf ? Infinity : v === sentinels.ninf ? -Infinity : v;
	const stack = [root];
	while (stack.length > 0) {
		const node = stack.pop();
		if (Array.isArray(node)) for (let i = 0; i < node.length; i++) {
			const v = node[i];
			if (typeof v === "string") node[i] = restore(v);
			else if (v && typeof v === "object") stack.push(v);
		}
		else if (isRecord(node)) for (const key of Object.keys(node)) {
			const v = node[key];
			if (typeof v === "string") node[key] = restore(v);
			else if (v && typeof v === "object") stack.push(v);
		}
	}
};
var isDenseGraph = (source) => {
	const n = Math.min(source.length, 16e6);
	let seps = 0;
	let i = 0;
	while (i < n) {
		const c = source.charCodeAt(i);
		if (c === 34) {
			i++;
			while (i < n) {
				const quote = source.indexOf("\"", i);
				if (quote === -1 || quote >= n) {
					i = n;
					break;
				}
				let backslashes = 0;
				for (let j = quote - 1; j >= 0 && source.charCodeAt(j) === 92; j--) backslashes++;
				i = quote + 1;
				if (backslashes % 2 === 0) break;
			}
			continue;
		}
		if (c === 44 || c === 58) seps++;
		i++;
	}
	return seps / n > .05;
};
var parseFallback = (text) => {
	const nonce = Math.random().toString(36).slice(2);
	const sentinels = {
		nan: `__json5_nan_${nonce}__`,
		inf: `__json5_inf_${nonce}__`,
		ninf: `__json5_ninf_${nonce}__`
	};
	const repaired = repairNonFiniteJson(text, `"${sentinels.nan}"`, `"${sentinels.inf}"`, `"${sentinels.ninf}"`);
	if (repaired !== null) {
		let plain;
		let repairedOk = true;
		try {
			plain = JSON.parse(repaired);
		} catch {
			repairedOk = false;
		}
		if (repairedOk) {
			if (typeof plain === "string") return plain === sentinels.nan ? NaN : plain === sentinels.inf ? Infinity : plain === sentinels.ninf ? -Infinity : plain;
			replaceSentinelsInPlace(plain, sentinels);
			return plain;
		}
	}
	return import_dist.default.parse(text);
};
var workerPool = new JsonWorkerPool();
var kWorkerMinSize = 5e4;
/**
* The one unchecked step in this module. Every entry point here names a `T`
* the parser cannot verify — the same contract `JSON.parse(text) as T` has,
* where the shape is the caller's claim about their own data. Funnelled
* through here so no other line in the module has to assert.
*/ var asParsed = (value) => value;
var asyncJsonParse = async (text) => {
	if (text.length < kWorkerMinSize) return jsonParse(text);
	else return asParsed(await workerPool.parse(text));
};
/**
* Parse JSON from raw UTF-8 bytes, avoiding redundant main-thread
* string allocation for large payloads.
*
* For small data (<50KB) decodes and parses on the main thread.
* For large data, transfers the bytes directly to a Web Worker,
* skipping the main-thread TextDecoder.decode + TextEncoder.encode
* round-trip that asyncJsonParse(string) would require.
*
* NOTE: for large inputs the bytes are TRANSFERRED to the worker — the
* caller's Uint8Array (and its whole ArrayBuffer, when the view covers it)
* is detached and unusable afterwards. Pass a copy if you still need the
* bytes; passing an already-detached view rejects with a DataCloneError.
*/ var asyncJsonParseBytes = async (data) => {
	if (data.length < kWorkerMinSize) return jsonParse(new TextDecoder("utf-8").decode(data));
	else return asParsed(await workerPool.parseBytes(data));
};
var jsonParse = (text) => {
	try {
		return asParsed(JSON.parse(text));
	} catch {
		return asParsed(parseFallback(text));
	}
};
var kWorkerCode = `
// Store the JSON5 parser once loaded
let JSON5 = null;
const decoder = new TextDecoder();

// Injected from the module-scope implementations (kept self-contained and
// typechecked there; any change over there lands here automatically)
const repairNonFiniteJson = ${repairNonFiniteJson.toString()};
const findSentinelPaths = ${findSentinelPaths.toString()};
const replaceSentinelsInPlace = ${replaceSentinelsInPlace.toString()};
const isDenseGraph = ${isDenseGraph.toString()};

// Non-strict JSON: repair Python-style bare NaN/Infinity and parse natively;
// full (slow) JSON5 only for real JSON5 syntax. Returns { result } to clone
// back, or { reparse, sourceText, nonFinitePaths, sentinels } when the main
// thread is better off parsing the repaired text itself. A reviver would be
// ~8x slower than plain parse on either thread, so sentinels are located
// with an off-thread walk and restored by targeted fixup instead.
function parseFallback(source, big, jsonError) {
  const nonce = Math.random().toString(36).slice(2);
  const sentinels = {
    nan: '__json5_nan_' + nonce + '__',
    inf: '__json5_inf_' + nonce + '__',
    ninf: '__json5_ninf_' + nonce + '__'
  };
  const repaired = repairNonFiniteJson(
    source,
    '"' + sentinels.nan + '"',
    '"' + sentinels.inf + '"',
    '"' + sentinels.ninf + '"');
  if (repaired !== null) {
    let plain;
    let repairedOk = true;
    try {
      plain = JSON.parse(repaired);
    } catch (repairError) {
      // repaired text still invalid — let JSON5 produce the real error
      repairedOk = false;
    }
    if (repairedOk) {
      if (typeof plain === 'string') {
        // bare non-finite at the root
        return {
          result: plain === sentinels.nan ? NaN
            : plain === sentinels.inf ? Infinity
            : plain === sentinels.ninf ? -Infinity
            : plain
        };
      }
      if (big && isDenseGraph(source)) {
        const paths = findSentinelPaths(plain, sentinels, 100000);
        if (paths !== null) {
          return { reparse: true, sourceText: repaired, nonFinitePaths: paths, sentinels };
        }
        // Path cap exceeded: a big dense document saturated with non-finite
        // values lands on the (slower) clone path — accepted inversion, the
        // alternative is shipping a path list rivaling the payload itself.
      }
      replaceSentinelsInPlace(plain, sentinels);
      return { result: plain };
    }
  }
  // Surface the original JSON error, not a null-JSON5 one, if init failed
  if (!JSON5) throw jsonError;
  return { result: JSON5.parse(source) };
}

self.onmessage = function (e) {
  const { type } = e.data || {};

  if (type === 'init') {
    const { scriptContent } = e.data;
    try {
      if (!JSON5) {
        const script = atob(scriptContent);
        new Function(script)();
        if (typeof self.JSON5 !== 'object' || typeof self.JSON5.parse !== 'function') {
          throw new Error('Failed to initialize JSON5 parser');
        }
        JSON5 = self.JSON5;
      }
    } catch (err) {
      // nothing to respond to yet; worker will fail on first parse if init failed
      console.error('JSON5 init error in worker', err);
    }
    return;
  }

  if (type === 'parse') {
    const { requestId, text, bytes } = e.data;

    try {
      const source = text !== undefined ? text : decoder.decode(bytes);
      const big = source.length > ${kReparseThresholdChars};

      // Structured clone hands the object graph straight to the main thread,
      // but its cost scales with node count: for big node-dense payloads it
      // blocks the receiving thread longer than a plain JSON.parse of the
      // source would (measured 4x total / 2x blocking on real 186MB
      // transcript data — see bench/). For those, skip the clone and tell
      // the main thread to run one JSON.parse itself — the cheapest possible
      // materialization. String-heavy payloads keep the clone (cheaper than
      // re-parsing).
      let response;
      try {
        // Optimistically, try a regular JSON parse first (this is much faster)
        const result = JSON.parse(source);
        if (big && isDenseGraph(source)) {
          // string requests retain their text on the main thread; byte
          // requests need the decoded source shipped back (cheap flat clone)
          response = text !== undefined
            ? { reparse: true }
            : { reparse: true, sourceText: source };
        } else {
          response = { result };
        }
      } catch (jsonError) {
        response = parseFallback(source, big, jsonError);
      }
      response.requestId = requestId;
      response.success = true;
      postMessage(response);
    } catch (err) {
      postMessage({
        requestId,
        success: false,
        error: err.message,
        stack: err.stack || ''
      });
    }
  }
};`;
var kJson5ScriptBase64 = `IWZ1bmN0aW9uKHUsRCl7Im9iamVjdCI9PXR5cGVvZiBleHBvcnRzJiYidW5kZWZpbmVkIiE9dHlwZW9mIG1vZHVsZT9tb2R1bGUuZXhwb3J0cz1EKCk6ImZ1bmN0aW9uIj09dHlwZW9mIGRlZmluZSYmZGVmaW5lLmFtZD9kZWZpbmUoRCk6dS5KU09ONT1EKCl9KHRoaXMsZnVuY3Rpb24oKXsidXNlIHN0cmljdCI7ZnVuY3Rpb24gdSh1LEQpe3JldHVybiB1KEQ9e2V4cG9ydHM6e319LEQuZXhwb3J0cyksRC5leHBvcnRzfXZhciBEPXUoZnVuY3Rpb24odSl7dmFyIEQ9dS5leHBvcnRzPSJ1bmRlZmluZWQiIT10eXBlb2Ygd2luZG93JiZ3aW5kb3cuTWF0aD09TWF0aD93aW5kb3c6InVuZGVmaW5lZCIhPXR5cGVvZiBzZWxmJiZzZWxmLk1hdGg9PU1hdGg/c2VsZjpGdW5jdGlvbigicmV0dXJuIHRoaXMiKSgpOyJudW1iZXIiPT10eXBlb2YgX19nJiYoX19nPUQpfSksZT11KGZ1bmN0aW9uKHUpe3ZhciBEPXUuZXhwb3J0cz17dmVyc2lvbjoiMi42LjUifTsibnVtYmVyIj09dHlwZW9mIF9fZSYmKF9fZT1EKX0pLHI9KGUudmVyc2lvbixmdW5jdGlvbih1KXtyZXR1cm4ib2JqZWN0Ij09dHlwZW9mIHU/bnVsbCE9PXU6ImZ1bmN0aW9uIj09dHlwZW9mIHV9KSx0PWZ1bmN0aW9uKHUpe2lmKCFyKHUpKXRocm93IFR5cGVFcnJvcih1KyIgaXMgbm90IGFuIG9iamVjdCEiKTtyZXR1cm4gdX0sbj1mdW5jdGlvbih1KXt0cnl7cmV0dXJuISF1KCl9Y2F0Y2godSl7cmV0dXJuITB9fSxGPSFuKGZ1bmN0aW9uKCl7cmV0dXJuIDchPU9iamVjdC5kZWZpbmVQcm9wZXJ0eSh7fSwiYSIse2dldDpmdW5jdGlvbigpe3JldHVybiA3fX0pLmF9KSxDPUQuZG9jdW1lbnQsQT1yKEMpJiZyKEMuY3JlYXRlRWxlbWVudCksaT0hRiYmIW4oZnVuY3Rpb24oKXtyZXR1cm4gNyE9T2JqZWN0LmRlZmluZVByb3BlcnR5KCh1PSJkaXYiLEE/Qy5jcmVhdGVFbGVtZW50KHUpOnt9KSwiYSIse2dldDpmdW5jdGlvbigpe3JldHVybiA3fX0pLmE7dmFyIHV9KSxFPU9iamVjdC5kZWZpbmVQcm9wZXJ0eSxvPXtmOkY/T2JqZWN0LmRlZmluZVByb3BlcnR5OmZ1bmN0aW9uKHUsRCxlKXtpZih0KHUpLEQ9ZnVuY3Rpb24odSxEKXtpZighcih1KSlyZXR1cm4gdTt2YXIgZSx0O2lmKEQmJiJmdW5jdGlvbiI9PXR5cGVvZihlPXUudG9TdHJpbmcpJiYhcih0PWUuY2FsbCh1KSkpcmV0dXJuIHQ7aWYoImZ1bmN0aW9uIj09dHlwZW9mKGU9dS52YWx1ZU9mKSYmIXIodD1lLmNhbGwodSkpKXJldHVybiB0O2lmKCFEJiYiZnVuY3Rpb24iPT10eXBlb2YoZT11LnRvU3RyaW5nKSYmIXIodD1lLmNhbGwodSkpKXJldHVybiB0O3Rocm93IFR5cGVFcnJvcigiQ2FuJ3QgY29udmVydCBvYmplY3QgdG8gcHJpbWl0aXZlIHZhbHVlIil9KEQsITApLHQoZSksaSl0cnl7cmV0dXJuIEUodSxELGUpfWNhdGNoKHUpe31pZigiZ2V0ImluIGV8fCJzZXQiaW4gZSl0aHJvdyBUeXBlRXJyb3IoIkFjY2Vzc29ycyBub3Qgc3VwcG9ydGVkISIpO3JldHVybiJ2YWx1ZSJpbiBlJiYodVtEXT1lLnZhbHVlKSx1fX0sYT1GP2Z1bmN0aW9uKHUsRCxlKXtyZXR1cm4gby5mKHUsRCxmdW5jdGlvbih1LEQpe3JldHVybntlbnVtZXJhYmxlOiEoMSZ1KSxjb25maWd1cmFibGU6ISgyJnUpLHdyaXRhYmxlOiEoNCZ1KSx2YWx1ZTpEfX0oMSxlKSl9OmZ1bmN0aW9uKHUsRCxlKXtyZXR1cm4gdVtEXT1lLHV9LGM9e30uaGFzT3duUHJvcGVydHksQj1mdW5jdGlvbih1LEQpe3JldHVybiBjLmNhbGwodSxEKX0scz0wLGY9TWF0aC5yYW5kb20oKSxsPXUoZnVuY3Rpb24odSl7dmFyIHI9RFsiX19jb3JlLWpzX3NoYXJlZF9fIl18fChEWyJfX2NvcmUtanNfc2hhcmVkX18iXT17fSk7KHUuZXhwb3J0cz1mdW5jdGlvbih1LEQpe3JldHVybiByW3VdfHwoclt1XT12b2lkIDAhPT1EP0Q6e30pfSkoInZlcnNpb25zIixbXSkucHVzaCh7dmVyc2lvbjplLnZlcnNpb24sbW9kZToiZ2xvYmFsIixjb3B5cmlnaHQ6IsKpIDIwMTkgRGVuaXMgUHVzaGthcmV2ICh6bG9pcm9jay5ydSkifSl9KSgibmF0aXZlLWZ1bmN0aW9uLXRvLXN0cmluZyIsRnVuY3Rpb24udG9TdHJpbmcpLGQ9dShmdW5jdGlvbih1KXt2YXIgcix0PSJTeW1ib2woIi5jb25jYXQodm9pZCAwPT09KHI9InNyYyIpPyIiOnIsIilfIiwoKytzK2YpLnRvU3RyaW5nKDM2KSksbj0oIiIrbCkuc3BsaXQoInRvU3RyaW5nIik7ZS5pbnNwZWN0U291cmNlPWZ1bmN0aW9uKHUpe3JldHVybiBsLmNhbGwodSl9LCh1LmV4cG9ydHM9ZnVuY3Rpb24odSxlLHIsRil7dmFyIEM9ImZ1bmN0aW9uIj09dHlwZW9mIHI7QyYmKEIociwibmFtZSIpfHxhKHIsIm5hbWUiLGUpKSx1W2VdIT09ciYmKEMmJihCKHIsdCl8fGEocix0LHVbZV0/IiIrdVtlXTpuLmpvaW4oU3RyaW5nKGUpKSkpLHU9PT1EP3VbZV09cjpGP3VbZV0/dVtlXT1yOmEodSxlLHIpOihkZWxldGUgdVtlXSxhKHUsZSxyKSkpfSkoRnVuY3Rpb24ucHJvdG90eXBlLCJ0b1N0cmluZyIsZnVuY3Rpb24oKXtyZXR1cm4iZnVuY3Rpb24iPT10eXBlb2YgdGhpcyYmdGhpc1t0XXx8bC5jYWxsKHRoaXMpfSl9KSx2PWZ1bmN0aW9uKHUsRCxlKXtpZihmdW5jdGlvbih1KXtpZigiZnVuY3Rpb24iIT10eXBlb2YgdSl0aHJvdyBUeXBlRXJyb3IodSsiIGlzIG5vdCBhIGZ1bmN0aW9uISIpfSh1KSx2b2lkIDA9PT1EKXJldHVybiB1O3N3aXRjaChlKXtjYXNlIDE6cmV0dXJuIGZ1bmN0aW9uKGUpe3JldHVybiB1LmNhbGwoRCxlKX07Y2FzZSAyOnJldHVybiBmdW5jdGlvbihlLHIpe3JldHVybiB1LmNhbGwoRCxlLHIpfTtjYXNlIDM6cmV0dXJuIGZ1bmN0aW9uKGUscix0KXtyZXR1cm4gdS5jYWxsKEQsZSxyLHQpfX1yZXR1cm4gZnVuY3Rpb24oKXtyZXR1cm4gdS5hcHBseShELGFyZ3VtZW50cyl9fSxwPWZ1bmN0aW9uKHUscix0KXt2YXIgbixGLEMsQSxpPXUmcC5GLEU9dSZwLkcsbz11JnAuUyxjPXUmcC5QLEI9dSZwLkIscz1FP0Q6bz9EW3JdfHwoRFtyXT17fSk6KERbcl18fHt9KS5wcm90b3R5cGUsZj1FP2U6ZVtyXXx8KGVbcl09e30pLGw9Zi5wcm90b3R5cGV8fChmLnByb3RvdHlwZT17fSk7Zm9yKG4gaW4gRSYmKHQ9ciksdClDPSgoRj0haSYmcyYmdm9pZCAwIT09c1tuXSk/czp0KVtuXSxBPUImJkY/dihDLEQpOmMmJiJmdW5jdGlvbiI9PXR5cGVvZiBDP3YoRnVuY3Rpb24uY2FsbCxDKTpDLHMmJmQocyxuLEMsdSZwLlUpLGZbbl0hPUMmJmEoZixuLEEpLGMmJmxbbl0hPUMmJihsW25dPUMpfTtELmNvcmU9ZSxwLkY9MSxwLkc9MixwLlM9NCxwLlA9OCxwLkI9MTYscC5XPTMyLHAuVT02NCxwLlI9MTI4O3ZhciBoLG09cCxnPU1hdGguY2VpbCx5PU1hdGguZmxvb3Isdz1mdW5jdGlvbih1KXtyZXR1cm4gaXNOYU4odT0rdSk/MDoodT4wP3k6ZykodSl9LGI9KGg9ITEsZnVuY3Rpb24odSxEKXt2YXIgZSxyLHQ9U3RyaW5nKGZ1bmN0aW9uKHUpe2lmKG51bGw9PXUpdGhyb3cgVHlwZUVycm9yKCJDYW4ndCBjYWxsIG1ldGhvZCBvbiAgIit1KTtyZXR1cm4gdX0odSkpLG49dyhEKSxGPXQubGVuZ3RoO3JldHVybiBuPDB8fG4+PUY/aD8iIjp2b2lkIDA6KGU9dC5jaGFyQ29kZUF0KG4pKTw1NTI5Nnx8ZT41NjMxOXx8bisxPT09Rnx8KHI9dC5jaGFyQ29kZUF0KG4rMSkpPDU2MzIwfHxyPjU3MzQzP2g/dC5jaGFyQXQobik6ZTpoP3Quc2xpY2UobixuKzIpOnItNTYzMjArKGUtNTUyOTY8PDEwKSs2NTUzNn0pO20obS5QLCJTdHJpbmciLHtjb2RlUG9pbnRBdDpmdW5jdGlvbih1KXtyZXR1cm4gYih0aGlzLHUpfX0pO2UuU3RyaW5nLmNvZGVQb2ludEF0O3ZhciBTPU1hdGgubWF4LHg9TWF0aC5taW4sTj1TdHJpbmcuZnJvbUNoYXJDb2RlLFA9U3RyaW5nLmZyb21Db2RlUG9pbnQ7bShtLlMrbS5GKighIVAmJjEhPVAubGVuZ3RoKSwiU3RyaW5nIix7ZnJvbUNvZGVQb2ludDpmdW5jdGlvbih1KXtmb3IodmFyIEQsZSxyLHQ9YXJndW1lbnRzLG49W10sRj1hcmd1bWVudHMubGVuZ3RoLEM9MDtGPkM7KXtpZihEPSt0W0MrK10scj0xMTE0MTExLCgoZT13KGU9RCkpPDA/UyhlK3IsMCk6eChlLHIpKSE9PUQpdGhyb3cgUmFuZ2VFcnJvcihEKyIgaXMgbm90IGEgdmFsaWQgY29kZSBwb2ludCIpO24ucHVzaChEPDY1NTM2P04oRCk6Tig1NTI5NisoKEQtPTY1NTM2KT4+MTApLEQlMTAyNCs1NjMyMCkpfXJldHVybiBuLmpvaW4oIiIpfX0pO2UuU3RyaW5nLmZyb21Db2RlUG9pbnQ7dmFyIF8sTyxqLEksVixKLE0sayxMLFQseixILCQsUixHPXtTcGFjZV9TZXBhcmF0b3I6L1tcdTE2ODBcdTIwMDAtXHUyMDBBXHUyMDJGXHUyMDVGXHUzMDAwXS8sSURfU3RhcnQ6L1tceEFBXHhCNVx4QkFceEMwLVx4RDZceEQ4LVx4RjZceEY4LVx1MDJDMVx1MDJDNi1cdTAyRDFcdTAyRTAtXHUwMkU0XHUwMkVDXHUwMkVFXHUwMzcwLVx1MDM3NFx1MDM3Nlx1MDM3N1x1MDM3QS1cdTAzN0RcdTAzN0ZcdTAzODZcdTAzODgtXHUwMzhBXHUwMzhDXHUwMzhFLVx1MDNBMVx1MDNBMy1cdTAzRjVcdTAzRjctXHUwNDgxXHUwNDhBLVx1MDUyRlx1MDUzMS1cdTA1NTZcdTA1NTlcdTA1NjEtXHUwNTg3XHUwNUQwLVx1MDVFQVx1MDVGMC1cdTA1RjJcdTA2MjAtXHUwNjRBXHUwNjZFXHUwNjZGXHUwNjcxLVx1MDZEM1x1MDZENVx1MDZFNVx1MDZFNlx1MDZFRVx1MDZFRlx1MDZGQS1cdTA2RkNcdTA2RkZcdTA3MTBcdTA3MTItXHUwNzJGXHUwNzRELVx1MDdBNVx1MDdCMVx1MDdDQS1cdTA3RUFcdTA3RjRcdTA3RjVcdTA3RkFcdTA4MDAtXHUwODE1XHUwODFBXHUwODI0XHUwODI4XHUwODQwLVx1MDg1OFx1MDg2MC1cdTA4NkFcdTA4QTAtXHUwOEI0XHUwOEI2LVx1MDhCRFx1MDkwNC1cdTA5MzlcdTA5M0RcdTA5NTBcdTA5NTgtXHUwOTYxXHUwOTcxLVx1MDk4MFx1MDk4NS1cdTA5OENcdTA5OEZcdTA5OTBcdTA5OTMtXHUwOUE4XHUwOUFBLVx1MDlCMFx1MDlCMlx1MDlCNi1cdTA5QjlcdTA5QkRcdTA5Q0VcdTA5RENcdTA5RERcdTA5REYtXHUwOUUxXHUwOUYwXHUwOUYxXHUwOUZDXHUwQTA1LVx1MEEwQVx1MEEwRlx1MEExMFx1MEExMy1cdTBBMjhcdTBBMkEtXHUwQTMwXHUwQTMyXHUwQTMzXHUwQTM1XHUwQTM2XHUwQTM4XHUwQTM5XHUwQTU5LVx1MEE1Q1x1MEE1RVx1MEE3Mi1cdTBBNzRcdTBBODUtXHUwQThEXHUwQThGLVx1MEE5MVx1MEE5My1cdTBBQThcdTBBQUEtXHUwQUIwXHUwQUIyXHUwQUIzXHUwQUI1LVx1MEFCOVx1MEFCRFx1MEFEMFx1MEFFMFx1MEFFMVx1MEFGOVx1MEIwNS1cdTBCMENcdTBCMEZcdTBCMTBcdTBCMTMtXHUwQjI4XHUwQjJBLVx1MEIzMFx1MEIzMlx1MEIzM1x1MEIzNS1cdTBCMzlcdTBCM0RcdTBCNUNcdTBCNURcdTBCNUYtXHUwQjYxXHUwQjcxXHUwQjgzXHUwQjg1LVx1MEI4QVx1MEI4RS1cdTBCOTBcdTBCOTItXHUwQjk1XHUwQjk5XHUwQjlBXHUwQjlDXHUwQjlFXHUwQjlGXHUwQkEzXHUwQkE0XHUwQkE4LVx1MEJBQVx1MEJBRS1cdTBCQjlcdTBCRDBcdTBDMDUtXHUwQzBDXHUwQzBFLVx1MEMxMFx1MEMxMi1cdTBDMjhcdTBDMkEtXHUwQzM5XHUwQzNEXHUwQzU4LVx1MEM1QVx1MEM2MFx1MEM2MVx1MEM4MFx1MEM4NS1cdTBDOENcdTBDOEUtXHUwQzkwXHUwQzkyLVx1MENBOFx1MENBQS1cdTBDQjNcdTBDQjUtXHUwQ0I5XHUwQ0JEXHUwQ0RFXHUwQ0UwXHUwQ0UxXHUwQ0YxXHUwQ0YyXHUwRDA1LVx1MEQwQ1x1MEQwRS1cdTBEMTBcdTBEMTItXHUwRDNBXHUwRDNEXHUwRDRFXHUwRDU0LVx1MEQ1Nlx1MEQ1Ri1cdTBENjFcdTBEN0EtXHUwRDdGXHUwRDg1LVx1MEQ5Nlx1MEQ5QS1cdTBEQjFcdTBEQjMtXHUwREJCXHUwREJEXHUwREMwLVx1MERDNlx1MEUwMS1cdTBFMzBcdTBFMzJcdTBFMzNcdTBFNDAtXHUwRTQ2XHUwRTgxXHUwRTgyXHUwRTg0XHUwRTg3XHUwRTg4XHUwRThBXHUwRThEXHUwRTk0LVx1MEU5N1x1MEU5OS1cdTBFOUZcdTBFQTEtXHUwRUEzXHUwRUE1XHUwRUE3XHUwRUFBXHUwRUFCXHUwRUFELVx1MEVCMFx1MEVCMlx1MEVCM1x1MEVCRFx1MEVDMC1cdTBFQzRcdTBFQzZcdTBFREMtXHUwRURGXHUwRjAwXHUwRjQwLVx1MEY0N1x1MEY0OS1cdTBGNkNcdTBGODgtXHUwRjhDXHUxMDAwLVx1MTAyQVx1MTAzRlx1MTA1MC1cdTEwNTVcdTEwNUEtXHUxMDVEXHUxMDYxXHUxMDY1XHUxMDY2XHUxMDZFLVx1MTA3MFx1MTA3NS1cdTEwODFcdTEwOEVcdTEwQTAtXHUxMEM1XHUxMEM3XHUxMENEXHUxMEQwLVx1MTBGQVx1MTBGQy1cdTEyNDhcdTEyNEEtXHUxMjREXHUxMjUwLVx1MTI1Nlx1MTI1OFx1MTI1QS1cdTEyNURcdTEyNjAtXHUxMjg4XHUxMjhBLVx1MTI4RFx1MTI5MC1cdTEyQjBcdTEyQjItXHUxMkI1XHUxMkI4LVx1MTJCRVx1MTJDMFx1MTJDMi1cdTEyQzVcdTEyQzgtXHUxMkQ2XHUxMkQ4LVx1MTMxMFx1MTMxMi1cdTEzMTVcdTEzMTgtXHUxMzVBXHUxMzgwLVx1MTM4Rlx1MTNBMC1cdTEzRjVcdTEzRjgtXHUxM0ZEXHUxNDAxLVx1MTY2Q1x1MTY2Ri1cdTE2N0ZcdTE2ODEtXHUxNjlBXHUxNkEwLVx1MTZFQVx1MTZFRS1cdTE2RjhcdTE3MDAtXHUxNzBDXHUxNzBFLVx1MTcxMVx1MTcyMC1cdTE3MzFcdTE3NDAtXHUxNzUxXHUxNzYwLVx1MTc2Q1x1MTc2RS1cdTE3NzBcdTE3ODAtXHUxN0IzXHUxN0Q3XHUxN0RDXHUxODIwLVx1MTg3N1x1MTg4MC1cdTE4ODRcdTE4ODctXHUxOEE4XHUxOEFBXHUxOEIwLVx1MThGNVx1MTkwMC1cdTE5MUVcdTE5NTAtXHUxOTZEXHUxOTcwLVx1MTk3NFx1MTk4MC1cdTE5QUJcdTE5QjAtXHUxOUM5XHUxQTAwLVx1MUExNlx1MUEyMC1cdTFBNTRcdTFBQTdcdTFCMDUtXHUxQjMzXHUxQjQ1LVx1MUI0Qlx1MUI4My1cdTFCQTBcdTFCQUVcdTFCQUZcdTFCQkEtXHUxQkU1XHUxQzAwLVx1MUMyM1x1MUM0RC1cdTFDNEZcdTFDNUEtXHUxQzdEXHUxQzgwLVx1MUM4OFx1MUNFOS1cdTFDRUNcdTFDRUUtXHUxQ0YxXHUxQ0Y1XHUxQ0Y2XHUxRDAwLVx1MURCRlx1MUUwMC1cdTFGMTVcdTFGMTgtXHUxRjFEXHUxRjIwLVx1MUY0NVx1MUY0OC1cdTFGNERcdTFGNTAtXHUxRjU3XHUxRjU5XHUxRjVCXHUxRjVEXHUxRjVGLVx1MUY3RFx1MUY4MC1cdTFGQjRcdTFGQjYtXHUxRkJDXHUxRkJFXHUxRkMyLVx1MUZDNFx1MUZDNi1cdTFGQ0NcdTFGRDAtXHUxRkQzXHUxRkQ2LVx1MUZEQlx1MUZFMC1cdTFGRUNcdTFGRjItXHUxRkY0XHUxRkY2LVx1MUZGQ1x1MjA3MVx1MjA3Rlx1MjA5MC1cdTIwOUNcdTIxMDJcdTIxMDdcdTIxMEEtXHUyMTEzXHUyMTE1XHUyMTE5LVx1MjExRFx1MjEyNFx1MjEyNlx1MjEyOFx1MjEyQS1cdTIxMkRcdTIxMkYtXHUyMTM5XHUyMTNDLVx1MjEzRlx1MjE0NS1cdTIxNDlcdTIxNEVcdTIxNjAtXHUyMTg4XHUyQzAwLVx1MkMyRVx1MkMzMC1cdTJDNUVcdTJDNjAtXHUyQ0U0XHUyQ0VCLVx1MkNFRVx1MkNGMlx1MkNGM1x1MkQwMC1cdTJEMjVcdTJEMjdcdTJEMkRcdTJEMzAtXHUyRDY3XHUyRDZGXHUyRDgwLVx1MkQ5Nlx1MkRBMC1cdTJEQTZcdTJEQTgtXHUyREFFXHUyREIwLVx1MkRCNlx1MkRCOC1cdTJEQkVcdTJEQzAtXHUyREM2XHUyREM4LVx1MkRDRVx1MkREMC1cdTJERDZcdTJERDgtXHUyRERFXHUyRTJGXHUzMDA1LVx1MzAwN1x1MzAyMS1cdTMwMjlcdTMwMzEtXHUzMDM1XHUzMDM4LVx1MzAzQ1x1MzA0MS1cdTMwOTZcdTMwOUQtXHUzMDlGXHUzMEExLVx1MzBGQVx1MzBGQy1cdTMwRkZcdTMxMDUtXHUzMTJFXHUzMTMxLVx1MzE4RVx1MzFBMC1cdTMxQkFcdTMxRjAtXHUzMUZGXHUzNDAwLVx1NERCNVx1NEUwMC1cdTlGRUFcdUEwMDAtXHVBNDhDXHVBNEQwLVx1QTRGRFx1QTUwMC1cdUE2MENcdUE2MTAtXHVBNjFGXHVBNjJBXHVBNjJCXHVBNjQwLVx1QTY2RVx1QTY3Ri1cdUE2OURcdUE2QTAtXHVBNkVGXHVBNzE3LVx1QTcxRlx1QTcyMi1cdUE3ODhcdUE3OEItXHVBN0FFXHVBN0IwLVx1QTdCN1x1QTdGNy1cdUE4MDFcdUE4MDMtXHVBODA1XHVBODA3LVx1QTgwQVx1QTgwQy1cdUE4MjJcdUE4NDAtXHVBODczXHVBODgyLVx1QThCM1x1QThGMi1cdUE4RjdcdUE4RkJcdUE4RkRcdUE5MEEtXHVBOTI1XHVBOTMwLVx1QTk0Nlx1QTk2MC1cdUE5N0NcdUE5ODQtXHVBOUIyXHVBOUNGXHVBOUUwLVx1QTlFNFx1QTlFNi1cdUE5RUZcdUE5RkEtXHVBOUZFXHVBQTAwLVx1QUEyOFx1QUE0MC1cdUFBNDJcdUFBNDQtXHVBQTRCXHVBQTYwLVx1QUE3Nlx1QUE3QVx1QUE3RS1cdUFBQUZcdUFBQjFcdUFBQjVcdUFBQjZcdUFBQjktXHVBQUJEXHVBQUMwXHVBQUMyXHVBQURCLVx1QUFERFx1QUFFMC1cdUFBRUFcdUFBRjItXHVBQUY0XHVBQjAxLVx1QUIwNlx1QUIwOS1cdUFCMEVcdUFCMTEtXHVBQjE2XHVBQjIwLVx1QUIyNlx1QUIyOC1cdUFCMkVcdUFCMzAtXHVBQjVBXHVBQjVDLVx1QUI2NVx1QUI3MC1cdUFCRTJcdUFDMDAtXHVEN0EzXHVEN0IwLVx1RDdDNlx1RDdDQi1cdUQ3RkJcdUY5MDAtXHVGQTZEXHVGQTcwLVx1RkFEOVx1RkIwMC1cdUZCMDZcdUZCMTMtXHVGQjE3XHVGQjFEXHVGQjFGLVx1RkIyOFx1RkIyQS1cdUZCMzZcdUZCMzgtXHVGQjNDXHVGQjNFXHVGQjQwXHVGQjQxXHVGQjQzXHVGQjQ0XHVGQjQ2LVx1RkJCMVx1RkJEMy1cdUZEM0RcdUZENTAtXHVGRDhGXHVGRDkyLVx1RkRDN1x1RkRGMC1cdUZERkJcdUZFNzAtXHVGRTc0XHVGRTc2LVx1RkVGQ1x1RkYyMS1cdUZGM0FcdUZGNDEtXHVGRjVBXHVGRjY2LVx1RkZCRVx1RkZDMi1cdUZGQzdcdUZGQ0EtXHVGRkNGXHVGRkQyLVx1RkZEN1x1RkZEQS1cdUZGRENdfFx1RDgwMFtcdURDMDAtXHVEQzBCXHVEQzBELVx1REMyNlx1REMyOC1cdURDM0FcdURDM0NcdURDM0RcdURDM0YtXHVEQzREXHVEQzUwLVx1REM1RFx1REM4MC1cdURDRkFcdURENDAtXHVERDc0XHVERTgwLVx1REU5Q1x1REVBMC1cdURFRDBcdURGMDAtXHVERjFGXHVERjJELVx1REY0QVx1REY1MC1cdURGNzVcdURGODAtXHVERjlEXHVERkEwLVx1REZDM1x1REZDOC1cdURGQ0ZcdURGRDEtXHVERkQ1XXxcdUQ4MDFbXHVEQzAwLVx1REM5RFx1RENCMC1cdURDRDNcdURDRDgtXHVEQ0ZCXHVERDAwLVx1REQyN1x1REQzMC1cdURENjNcdURFMDAtXHVERjM2XHVERjQwLVx1REY1NVx1REY2MC1cdURGNjddfFx1RDgwMltcdURDMDAtXHVEQzA1XHVEQzA4XHVEQzBBLVx1REMzNVx1REMzN1x1REMzOFx1REMzQ1x1REMzRi1cdURDNTVcdURDNjAtXHVEQzc2XHVEQzgwLVx1REM5RVx1RENFMC1cdURDRjJcdURDRjRcdURDRjVcdUREMDAtXHVERDE1XHVERDIwLVx1REQzOVx1REQ4MC1cdUREQjdcdUREQkVcdUREQkZcdURFMDBcdURFMTAtXHVERTEzXHVERTE1LVx1REUxN1x1REUxOS1cdURFMzNcdURFNjAtXHVERTdDXHVERTgwLVx1REU5Q1x1REVDMC1cdURFQzdcdURFQzktXHVERUU0XHVERjAwLVx1REYzNVx1REY0MC1cdURGNTVcdURGNjAtXHVERjcyXHVERjgwLVx1REY5MV18XHVEODAzW1x1REMwMC1cdURDNDhcdURDODAtXHVEQ0IyXHVEQ0MwLVx1RENGMl18XHVEODA0W1x1REMwMy1cdURDMzdcdURDODMtXHVEQ0FGXHVEQ0QwLVx1RENFOFx1REQwMy1cdUREMjZcdURENTAtXHVERDcyXHVERDc2XHVERDgzLVx1RERCMlx1RERDMS1cdUREQzRcdUREREFcdURERENcdURFMDAtXHVERTExXHVERTEzLVx1REUyQlx1REU4MC1cdURFODZcdURFODhcdURFOEEtXHVERThEXHVERThGLVx1REU5RFx1REU5Ri1cdURFQThcdURFQjAtXHVERURFXHVERjA1LVx1REYwQ1x1REYwRlx1REYxMFx1REYxMy1cdURGMjhcdURGMkEtXHVERjMwXHVERjMyXHVERjMzXHVERjM1LVx1REYzOVx1REYzRFx1REY1MFx1REY1RC1cdURGNjFdfFx1RDgwNVtcdURDMDAtXHVEQzM0XHVEQzQ3LVx1REM0QVx1REM4MC1cdURDQUZcdURDQzRcdURDQzVcdURDQzdcdUREODAtXHVEREFFXHVEREQ4LVx1REREQlx1REUwMC1cdURFMkZcdURFNDRcdURFODAtXHVERUFBXHVERjAwLVx1REYxOV18XHVEODA2W1x1RENBMC1cdURDREZcdURDRkZcdURFMDBcdURFMEItXHVERTMyXHVERTNBXHVERTUwXHVERTVDLVx1REU4M1x1REU4Ni1cdURFODlcdURFQzAtXHVERUY4XXxcdUQ4MDdbXHVEQzAwLVx1REMwOFx1REMwQS1cdURDMkVcdURDNDBcdURDNzItXHVEQzhGXHVERDAwLVx1REQwNlx1REQwOFx1REQwOVx1REQwQi1cdUREMzBcdURENDZdfFx1RDgwOFtcdURDMDAtXHVERjk5XXxcdUQ4MDlbXHVEQzAwLVx1REM2RVx1REM4MC1cdURENDNdfFtcdUQ4MENcdUQ4MUMtXHVEODIwXHVEODQwLVx1RDg2OFx1RDg2QS1cdUQ4NkNcdUQ4NkYtXHVEODcyXHVEODc0LVx1RDg3OV1bXHVEQzAwLVx1REZGRl18XHVEODBEW1x1REMwMC1cdURDMkVdfFx1RDgxMVtcdURDMDAtXHVERTQ2XXxcdUQ4MUFbXHVEQzAwLVx1REUzOFx1REU0MC1cdURFNUVcdURFRDAtXHVERUVEXHVERjAwLVx1REYyRlx1REY0MC1cdURGNDNcdURGNjMtXHVERjc3XHVERjdELVx1REY4Rl18XHVEODFCW1x1REYwMC1cdURGNDRcdURGNTBcdURGOTMtXHVERjlGXHVERkUwXHVERkUxXXxcdUQ4MjFbXHVEQzAwLVx1REZFQ118XHVEODIyW1x1REMwMC1cdURFRjJdfFx1RDgyQ1tcdURDMDAtXHVERDFFXHVERDcwLVx1REVGQl18XHVEODJGW1x1REMwMC1cdURDNkFcdURDNzAtXHVEQzdDXHVEQzgwLVx1REM4OFx1REM5MC1cdURDOTldfFx1RDgzNVtcdURDMDAtXHVEQzU0XHVEQzU2LVx1REM5Q1x1REM5RVx1REM5Rlx1RENBMlx1RENBNVx1RENBNlx1RENBOS1cdURDQUNcdURDQUUtXHVEQ0I5XHVEQ0JCXHVEQ0JELVx1RENDM1x1RENDNS1cdUREMDVcdUREMDctXHVERDBBXHVERDBELVx1REQxNFx1REQxNi1cdUREMUNcdUREMUUtXHVERDM5XHVERDNCLVx1REQzRVx1REQ0MC1cdURENDRcdURENDZcdURENEEtXHVERDUwXHVERDUyLVx1REVBNVx1REVBOC1cdURFQzBcdURFQzItXHVERURBXHVERURDLVx1REVGQVx1REVGQy1cdURGMTRcdURGMTYtXHVERjM0XHVERjM2LVx1REY0RVx1REY1MC1cdURGNkVcdURGNzAtXHVERjg4XHVERjhBLVx1REZBOFx1REZBQS1cdURGQzJcdURGQzQtXHVERkNCXXxcdUQ4M0FbXHVEQzAwLVx1RENDNFx1REQwMC1cdURENDNdfFx1RDgzQltcdURFMDAtXHVERTAzXHVERTA1LVx1REUxRlx1REUyMVx1REUyMlx1REUyNFx1REUyN1x1REUyOS1cdURFMzJcdURFMzQtXHVERTM3XHVERTM5XHVERTNCXHVERTQyXHVERTQ3XHVERTQ5XHVERTRCXHVERTRELVx1REU0Rlx1REU1MVx1REU1Mlx1REU1NFx1REU1N1x1REU1OVx1REU1Qlx1REU1RFx1REU1Rlx1REU2MVx1REU2Mlx1REU2NFx1REU2Ny1cdURFNkFcdURFNkMtXHVERTcyXHVERTc0LVx1REU3N1x1REU3OS1cdURFN0NcdURFN0VcdURFODAtXHVERTg5XHVERThCLVx1REU5Qlx1REVBMS1cdURFQTNcdURFQTUtXHVERUE5XHVERUFCLVx1REVCQl18XHVEODY5W1x1REMwMC1cdURFRDZcdURGMDAtXHVERkZGXXxcdUQ4NkRbXHVEQzAwLVx1REYzNFx1REY0MC1cdURGRkZdfFx1RDg2RVtcdURDMDAtXHVEQzFEXHVEQzIwLVx1REZGRl18XHVEODczW1x1REMwMC1cdURFQTFcdURFQjAtXHVERkZGXXxcdUQ4N0FbXHVEQzAwLVx1REZFMF18XHVEODdFW1x1REMwMC1cdURFMURdLyxJRF9Db250aW51ZTovW1x4QUFceEI1XHhCQVx4QzAtXHhENlx4RDgtXHhGNlx4RjgtXHUwMkMxXHUwMkM2LVx1MDJEMVx1MDJFMC1cdTAyRTRcdTAyRUNcdTAyRUVcdTAzMDAtXHUwMzc0XHUwMzc2XHUwMzc3XHUwMzdBLVx1MDM3RFx1MDM3Rlx1MDM4Nlx1MDM4OC1cdTAzOEFcdTAzOENcdTAzOEUtXHUwM0ExXHUwM0EzLVx1MDNGNVx1MDNGNy1cdTA0ODFcdTA0ODMtXHUwNDg3XHUwNDhBLVx1MDUyRlx1MDUzMS1cdTA1NTZcdTA1NTlcdTA1NjEtXHUwNTg3XHUwNTkxLVx1MDVCRFx1MDVCRlx1MDVDMVx1MDVDMlx1MDVDNFx1MDVDNVx1MDVDN1x1MDVEMC1cdTA1RUFcdTA1RjAtXHUwNUYyXHUwNjEwLVx1MDYxQVx1MDYyMC1cdTA2NjlcdTA2NkUtXHUwNkQzXHUwNkQ1LVx1MDZEQ1x1MDZERi1cdTA2RThcdTA2RUEtXHUwNkZDXHUwNkZGXHUwNzEwLVx1MDc0QVx1MDc0RC1cdTA3QjFcdTA3QzAtXHUwN0Y1XHUwN0ZBXHUwODAwLVx1MDgyRFx1MDg0MC1cdTA4NUJcdTA4NjAtXHUwODZBXHUwOEEwLVx1MDhCNFx1MDhCNi1cdTA4QkRcdTA4RDQtXHUwOEUxXHUwOEUzLVx1MDk2M1x1MDk2Ni1cdTA5NkZcdTA5NzEtXHUwOTgzXHUwOTg1LVx1MDk4Q1x1MDk4Rlx1MDk5MFx1MDk5My1cdTA5QThcdTA5QUEtXHUwOUIwXHUwOUIyXHUwOUI2LVx1MDlCOVx1MDlCQy1cdTA5QzRcdTA5QzdcdTA5QzhcdTA5Q0ItXHUwOUNFXHUwOUQ3XHUwOURDXHUwOUREXHUwOURGLVx1MDlFM1x1MDlFNi1cdTA5RjFcdTA5RkNcdTBBMDEtXHUwQTAzXHUwQTA1LVx1MEEwQVx1MEEwRlx1MEExMFx1MEExMy1cdTBBMjhcdTBBMkEtXHUwQTMwXHUwQTMyXHUwQTMzXHUwQTM1XHUwQTM2XHUwQTM4XHUwQTM5XHUwQTNDXHUwQTNFLVx1MEE0Mlx1MEE0N1x1MEE0OFx1MEE0Qi1cdTBBNERcdTBBNTFcdTBBNTktXHUwQTVDXHUwQTVFXHUwQTY2LVx1MEE3NVx1MEE4MS1cdTBBODNcdTBBODUtXHUwQThEXHUwQThGLVx1MEE5MVx1MEE5My1cdTBBQThcdTBBQUEtXHUwQUIwXHUwQUIyXHUwQUIzXHUwQUI1LVx1MEFCOVx1MEFCQy1cdTBBQzVcdTBBQzctXHUwQUM5XHUwQUNCLVx1MEFDRFx1MEFEMFx1MEFFMC1cdTBBRTNcdTBBRTYtXHUwQUVGXHUwQUY5LVx1MEFGRlx1MEIwMS1cdTBCMDNcdTBCMDUtXHUwQjBDXHUwQjBGXHUwQjEwXHUwQjEzLVx1MEIyOFx1MEIyQS1cdTBCMzBcdTBCMzJcdTBCMzNcdTBCMzUtXHUwQjM5XHUwQjNDLVx1MEI0NFx1MEI0N1x1MEI0OFx1MEI0Qi1cdTBCNERcdTBCNTZcdTBCNTdcdTBCNUNcdTBCNURcdTBCNUYtXHUwQjYzXHUwQjY2LVx1MEI2Rlx1MEI3MVx1MEI4Mlx1MEI4M1x1MEI4NS1cdTBCOEFcdTBCOEUtXHUwQjkwXHUwQjkyLVx1MEI5NVx1MEI5OVx1MEI5QVx1MEI5Q1x1MEI5RVx1MEI5Rlx1MEJBM1x1MEJBNFx1MEJBOC1cdTBCQUFcdTBCQUUtXHUwQkI5XHUwQkJFLVx1MEJDMlx1MEJDNi1cdTBCQzhcdTBCQ0EtXHUwQkNEXHUwQkQwXHUwQkQ3XHUwQkU2LVx1MEJFRlx1MEMwMC1cdTBDMDNcdTBDMDUtXHUwQzBDXHUwQzBFLVx1MEMxMFx1MEMxMi1cdTBDMjhcdTBDMkEtXHUwQzM5XHUwQzNELVx1MEM0NFx1MEM0Ni1cdTBDNDhcdTBDNEEtXHUwQzREXHUwQzU1XHUwQzU2XHUwQzU4LVx1MEM1QVx1MEM2MC1cdTBDNjNcdTBDNjYtXHUwQzZGXHUwQzgwLVx1MEM4M1x1MEM4NS1cdTBDOENcdTBDOEUtXHUwQzkwXHUwQzkyLVx1MENBOFx1MENBQS1cdTBDQjNcdTBDQjUtXHUwQ0I5XHUwQ0JDLVx1MENDNFx1MENDNi1cdTBDQzhcdTBDQ0EtXHUwQ0NEXHUwQ0Q1XHUwQ0Q2XHUwQ0RFXHUwQ0UwLVx1MENFM1x1MENFNi1cdTBDRUZcdTBDRjFcdTBDRjJcdTBEMDAtXHUwRDAzXHUwRDA1LVx1MEQwQ1x1MEQwRS1cdTBEMTBcdTBEMTItXHUwRDQ0XHUwRDQ2LVx1MEQ0OFx1MEQ0QS1cdTBENEVcdTBENTQtXHUwRDU3XHUwRDVGLVx1MEQ2M1x1MEQ2Ni1cdTBENkZcdTBEN0EtXHUwRDdGXHUwRDgyXHUwRDgzXHUwRDg1LVx1MEQ5Nlx1MEQ5QS1cdTBEQjFcdTBEQjMtXHUwREJCXHUwREJEXHUwREMwLVx1MERDNlx1MERDQVx1MERDRi1cdTBERDRcdTBERDZcdTBERDgtXHUwRERGXHUwREU2LVx1MERFRlx1MERGMlx1MERGM1x1MEUwMS1cdTBFM0FcdTBFNDAtXHUwRTRFXHUwRTUwLVx1MEU1OVx1MEU4MVx1MEU4Mlx1MEU4NFx1MEU4N1x1MEU4OFx1MEU4QVx1MEU4RFx1MEU5NC1cdTBFOTdcdTBFOTktXHUwRTlGXHUwRUExLVx1MEVBM1x1MEVBNVx1MEVBN1x1MEVBQVx1MEVBQlx1MEVBRC1cdTBFQjlcdTBFQkItXHUwRUJEXHUwRUMwLVx1MEVDNFx1MEVDNlx1MEVDOC1cdTBFQ0RcdTBFRDAtXHUwRUQ5XHUwRURDLVx1MEVERlx1MEYwMFx1MEYxOFx1MEYxOVx1MEYyMC1cdTBGMjlcdTBGMzVcdTBGMzdcdTBGMzlcdTBGM0UtXHUwRjQ3XHUwRjQ5LVx1MEY2Q1x1MEY3MS1cdTBGODRcdTBGODYtXHUwRjk3XHUwRjk5LVx1MEZCQ1x1MEZDNlx1MTAwMC1cdTEwNDlcdTEwNTAtXHUxMDlEXHUxMEEwLVx1MTBDNVx1MTBDN1x1MTBDRFx1MTBEMC1cdTEwRkFcdTEwRkMtXHUxMjQ4XHUxMjRBLVx1MTI0RFx1MTI1MC1cdTEyNTZcdTEyNThcdTEyNUEtXHUxMjVEXHUxMjYwLVx1MTI4OFx1MTI4QS1cdTEyOERcdTEyOTAtXHUxMkIwXHUxMkIyLVx1MTJCNVx1MTJCOC1cdTEyQkVcdTEyQzBcdTEyQzItXHUxMkM1XHUxMkM4LVx1MTJENlx1MTJEOC1cdTEzMTBcdTEzMTItXHUxMzE1XHUxMzE4LVx1MTM1QVx1MTM1RC1cdTEzNUZcdTEzODAtXHUxMzhGXHUxM0EwLVx1MTNGNVx1MTNGOC1cdTEzRkRcdTE0MDEtXHUxNjZDXHUxNjZGLVx1MTY3Rlx1MTY4MS1cdTE2OUFcdTE2QTAtXHUxNkVBXHUxNkVFLVx1MTZGOFx1MTcwMC1cdTE3MENcdTE3MEUtXHUxNzE0XHUxNzIwLVx1MTczNFx1MTc0MC1cdTE3NTNcdTE3NjAtXHUxNzZDXHUxNzZFLVx1MTc3MFx1MTc3Mlx1MTc3M1x1MTc4MC1cdTE3RDNcdTE3RDdcdTE3RENcdTE3RERcdTE3RTAtXHUxN0U5XHUxODBCLVx1MTgwRFx1MTgxMC1cdTE4MTlcdTE4MjAtXHUxODc3XHUxODgwLVx1MThBQVx1MThCMC1cdTE4RjVcdTE5MDAtXHUxOTFFXHUxOTIwLVx1MTkyQlx1MTkzMC1cdTE5M0JcdTE5NDYtXHUxOTZEXHUxOTcwLVx1MTk3NFx1MTk4MC1cdTE5QUJcdTE5QjAtXHUxOUM5XHUxOUQwLVx1MTlEOVx1MUEwMC1cdTFBMUJcdTFBMjAtXHUxQTVFXHUxQTYwLVx1MUE3Q1x1MUE3Ri1cdTFBODlcdTFBOTAtXHUxQTk5XHUxQUE3XHUxQUIwLVx1MUFCRFx1MUIwMC1cdTFCNEJcdTFCNTAtXHUxQjU5XHUxQjZCLVx1MUI3M1x1MUI4MC1cdTFCRjNcdTFDMDAtXHUxQzM3XHUxQzQwLVx1MUM0OVx1MUM0RC1cdTFDN0RcdTFDODAtXHUxQzg4XHUxQ0QwLVx1MUNEMlx1MUNENC1cdTFDRjlcdTFEMDAtXHUxREY5XHUxREZCLVx1MUYxNVx1MUYxOC1cdTFGMURcdTFGMjAtXHUxRjQ1XHUxRjQ4LVx1MUY0RFx1MUY1MC1cdTFGNTdcdTFGNTlcdTFGNUJcdTFGNURcdTFGNUYtXHUxRjdEXHUxRjgwLVx1MUZCNFx1MUZCNi1cdTFGQkNcdTFGQkVcdTFGQzItXHUxRkM0XHUxRkM2LVx1MUZDQ1x1MUZEMC1cdTFGRDNcdTFGRDYtXHUxRkRCXHUxRkUwLVx1MUZFQ1x1MUZGMi1cdTFGRjRcdTFGRjYtXHUxRkZDXHUyMDNGXHUyMDQwXHUyMDU0XHUyMDcxXHUyMDdGXHUyMDkwLVx1MjA5Q1x1MjBEMC1cdTIwRENcdTIwRTFcdTIwRTUtXHUyMEYwXHUyMTAyXHUyMTA3XHUyMTBBLVx1MjExM1x1MjExNVx1MjExOS1cdTIxMURcdTIxMjRcdTIxMjZcdTIxMjhcdTIxMkEtXHUyMTJEXHUyMTJGLVx1MjEzOVx1MjEzQy1cdTIxM0ZcdTIxNDUtXHUyMTQ5XHUyMTRFXHUyMTYwLVx1MjE4OFx1MkMwMC1cdTJDMkVcdTJDMzAtXHUyQzVFXHUyQzYwLVx1MkNFNFx1MkNFQi1cdTJDRjNcdTJEMDAtXHUyRDI1XHUyRDI3XHUyRDJEXHUyRDMwLVx1MkQ2N1x1MkQ2Rlx1MkQ3Ri1cdTJEOTZcdTJEQTAtXHUyREE2XHUyREE4LVx1MkRBRVx1MkRCMC1cdTJEQjZcdTJEQjgtXHUyREJFXHUyREMwLVx1MkRDNlx1MkRDOC1cdTJEQ0VcdTJERDAtXHUyREQ2XHUyREQ4LVx1MkRERVx1MkRFMC1cdTJERkZcdTJFMkZcdTMwMDUtXHUzMDA3XHUzMDIxLVx1MzAyRlx1MzAzMS1cdTMwMzVcdTMwMzgtXHUzMDNDXHUzMDQxLVx1MzA5Nlx1MzA5OVx1MzA5QVx1MzA5RC1cdTMwOUZcdTMwQTEtXHUzMEZBXHUzMEZDLVx1MzBGRlx1MzEwNS1cdTMxMkVcdTMxMzEtXHUzMThFXHUzMUEwLVx1MzFCQVx1MzFGMC1cdTMxRkZcdTM0MDAtXHU0REI1XHU0RTAwLVx1OUZFQVx1QTAwMC1cdUE0OENcdUE0RDAtXHVBNEZEXHVBNTAwLVx1QTYwQ1x1QTYxMC1cdUE2MkJcdUE2NDAtXHVBNjZGXHVBNjc0LVx1QTY3RFx1QTY3Ri1cdUE2RjFcdUE3MTctXHVBNzFGXHVBNzIyLVx1QTc4OFx1QTc4Qi1cdUE3QUVcdUE3QjAtXHVBN0I3XHVBN0Y3LVx1QTgyN1x1QTg0MC1cdUE4NzNcdUE4ODAtXHVBOEM1XHVBOEQwLVx1QThEOVx1QThFMC1cdUE4RjdcdUE4RkJcdUE4RkRcdUE5MDAtXHVBOTJEXHVBOTMwLVx1QTk1M1x1QTk2MC1cdUE5N0NcdUE5ODAtXHVBOUMwXHVBOUNGLVx1QTlEOVx1QTlFMC1cdUE5RkVcdUFBMDAtXHVBQTM2XHVBQTQwLVx1QUE0RFx1QUE1MC1cdUFBNTlcdUFBNjAtXHVBQTc2XHVBQTdBLVx1QUFDMlx1QUFEQi1cdUFBRERcdUFBRTAtXHVBQUVGXHVBQUYyLVx1QUFGNlx1QUIwMS1cdUFCMDZcdUFCMDktXHVBQjBFXHVBQjExLVx1QUIxNlx1QUIyMC1cdUFCMjZcdUFCMjgtXHVBQjJFXHVBQjMwLVx1QUI1QVx1QUI1Qy1cdUFCNjVcdUFCNzAtXHVBQkVBXHVBQkVDXHVBQkVEXHVBQkYwLVx1QUJGOVx1QUMwMC1cdUQ3QTNcdUQ3QjAtXHVEN0M2XHVEN0NCLVx1RDdGQlx1RjkwMC1cdUZBNkRcdUZBNzAtXHVGQUQ5XHVGQjAwLVx1RkIwNlx1RkIxMy1cdUZCMTdcdUZCMUQtXHVGQjI4XHVGQjJBLVx1RkIzNlx1RkIzOC1cdUZCM0NcdUZCM0VcdUZCNDBcdUZCNDFcdUZCNDNcdUZCNDRcdUZCNDYtXHVGQkIxXHVGQkQzLVx1RkQzRFx1RkQ1MC1cdUZEOEZcdUZEOTItXHVGREM3XHVGREYwLVx1RkRGQlx1RkUwMC1cdUZFMEZcdUZFMjAtXHVGRTJGXHVGRTMzXHVGRTM0XHVGRTRELVx1RkU0Rlx1RkU3MC1cdUZFNzRcdUZFNzYtXHVGRUZDXHVGRjEwLVx1RkYxOVx1RkYyMS1cdUZGM0FcdUZGM0ZcdUZGNDEtXHVGRjVBXHVGRjY2LVx1RkZCRVx1RkZDMi1cdUZGQzdcdUZGQ0EtXHVGRkNGXHVGRkQyLVx1RkZEN1x1RkZEQS1cdUZGRENdfFx1RDgwMFtcdURDMDAtXHVEQzBCXHVEQzBELVx1REMyNlx1REMyOC1cdURDM0FcdURDM0NcdURDM0RcdURDM0YtXHVEQzREXHVEQzUwLVx1REM1RFx1REM4MC1cdURDRkFcdURENDAtXHVERDc0XHVEREZEXHVERTgwLVx1REU5Q1x1REVBMC1cdURFRDBcdURFRTBcdURGMDAtXHVERjFGXHVERjJELVx1REY0QVx1REY1MC1cdURGN0FcdURGODAtXHVERjlEXHVERkEwLVx1REZDM1x1REZDOC1cdURGQ0ZcdURGRDEtXHVERkQ1XXxcdUQ4MDFbXHVEQzAwLVx1REM5RFx1RENBMC1cdURDQTlcdURDQjAtXHVEQ0QzXHVEQ0Q4LVx1RENGQlx1REQwMC1cdUREMjdcdUREMzAtXHVERDYzXHVERTAwLVx1REYzNlx1REY0MC1cdURGNTVcdURGNjAtXHVERjY3XXxcdUQ4MDJbXHVEQzAwLVx1REMwNVx1REMwOFx1REMwQS1cdURDMzVcdURDMzdcdURDMzhcdURDM0NcdURDM0YtXHVEQzU1XHVEQzYwLVx1REM3Nlx1REM4MC1cdURDOUVcdURDRTAtXHVEQ0YyXHVEQ0Y0XHVEQ0Y1XHVERDAwLVx1REQxNVx1REQyMC1cdUREMzlcdUREODAtXHVEREI3XHVEREJFXHVEREJGXHVERTAwLVx1REUwM1x1REUwNVx1REUwNlx1REUwQy1cdURFMTNcdURFMTUtXHVERTE3XHVERTE5LVx1REUzM1x1REUzOC1cdURFM0FcdURFM0ZcdURFNjAtXHVERTdDXHVERTgwLVx1REU5Q1x1REVDMC1cdURFQzdcdURFQzktXHVERUU2XHVERjAwLVx1REYzNVx1REY0MC1cdURGNTVcdURGNjAtXHVERjcyXHVERjgwLVx1REY5MV18XHVEODAzW1x1REMwMC1cdURDNDhcdURDODAtXHVEQ0IyXHVEQ0MwLVx1RENGMl18XHVEODA0W1x1REMwMC1cdURDNDZcdURDNjYtXHVEQzZGXHVEQzdGLVx1RENCQVx1RENEMC1cdURDRThcdURDRjAtXHVEQ0Y5XHVERDAwLVx1REQzNFx1REQzNi1cdUREM0ZcdURENTAtXHVERDczXHVERDc2XHVERDgwLVx1RERDNFx1RERDQS1cdUREQ0NcdURERDAtXHVERERBXHVERERDXHVERTAwLVx1REUxMVx1REUxMy1cdURFMzdcdURFM0VcdURFODAtXHVERTg2XHVERTg4XHVERThBLVx1REU4RFx1REU4Ri1cdURFOURcdURFOUYtXHVERUE4XHVERUIwLVx1REVFQVx1REVGMC1cdURFRjlcdURGMDAtXHVERjAzXHVERjA1LVx1REYwQ1x1REYwRlx1REYxMFx1REYxMy1cdURGMjhcdURGMkEtXHVERjMwXHVERjMyXHVERjMzXHVERjM1LVx1REYzOVx1REYzQy1cdURGNDRcdURGNDdcdURGNDhcdURGNEItXHVERjREXHVERjUwXHVERjU3XHVERjVELVx1REY2M1x1REY2Ni1cdURGNkNcdURGNzAtXHVERjc0XXxcdUQ4MDVbXHVEQzAwLVx1REM0QVx1REM1MC1cdURDNTlcdURDODAtXHVEQ0M1XHVEQ0M3XHVEQ0QwLVx1RENEOVx1REQ4MC1cdUREQjVcdUREQjgtXHVEREMwXHVEREQ4LVx1RERERFx1REUwMC1cdURFNDBcdURFNDRcdURFNTAtXHVERTU5XHVERTgwLVx1REVCN1x1REVDMC1cdURFQzlcdURGMDAtXHVERjE5XHVERjFELVx1REYyQlx1REYzMC1cdURGMzldfFx1RDgwNltcdURDQTAtXHVEQ0U5XHVEQ0ZGXHVERTAwLVx1REUzRVx1REU0N1x1REU1MC1cdURFODNcdURFODYtXHVERTk5XHVERUMwLVx1REVGOF18XHVEODA3W1x1REMwMC1cdURDMDhcdURDMEEtXHVEQzM2XHVEQzM4LVx1REM0MFx1REM1MC1cdURDNTlcdURDNzItXHVEQzhGXHVEQzkyLVx1RENBN1x1RENBOS1cdURDQjZcdUREMDAtXHVERDA2XHVERDA4XHVERDA5XHVERDBCLVx1REQzNlx1REQzQVx1REQzQ1x1REQzRFx1REQzRi1cdURENDdcdURENTAtXHVERDU5XXxcdUQ4MDhbXHVEQzAwLVx1REY5OV18XHVEODA5W1x1REMwMC1cdURDNkVcdURDODAtXHVERDQzXXxbXHVEODBDXHVEODFDLVx1RDgyMFx1RDg0MC1cdUQ4NjhcdUQ4NkEtXHVEODZDXHVEODZGLVx1RDg3Mlx1RDg3NC1cdUQ4NzldW1x1REMwMC1cdURGRkZdfFx1RDgwRFtcdURDMDAtXHVEQzJFXXxcdUQ4MTFbXHVEQzAwLVx1REU0Nl18XHVEODFBW1x1REMwMC1cdURFMzhcdURFNDAtXHVERTVFXHVERTYwLVx1REU2OVx1REVEMC1cdURFRURcdURFRjAtXHVERUY0XHVERjAwLVx1REYzNlx1REY0MC1cdURGNDNcdURGNTAtXHVERjU5XHVERjYzLVx1REY3N1x1REY3RC1cdURGOEZdfFx1RDgxQltcdURGMDAtXHVERjQ0XHVERjUwLVx1REY3RVx1REY4Ri1cdURGOUZcdURGRTBcdURGRTFdfFx1RDgyMVtcdURDMDAtXHVERkVDXXxcdUQ4MjJbXHVEQzAwLVx1REVGMl18XHVEODJDW1x1REMwMC1cdUREMUVcdURENzAtXHVERUZCXXxcdUQ4MkZbXHVEQzAwLVx1REM2QVx1REM3MC1cdURDN0NcdURDODAtXHVEQzg4XHVEQzkwLVx1REM5OVx1REM5RFx1REM5RV18XHVEODM0W1x1REQ2NS1cdURENjlcdURENkQtXHVERDcyXHVERDdCLVx1REQ4Mlx1REQ4NS1cdUREOEJcdUREQUEtXHVEREFEXHVERTQyLVx1REU0NF18XHVEODM1W1x1REMwMC1cdURDNTRcdURDNTYtXHVEQzlDXHVEQzlFXHVEQzlGXHVEQ0EyXHVEQ0E1XHVEQ0E2XHVEQ0E5LVx1RENBQ1x1RENBRS1cdURDQjlcdURDQkJcdURDQkQtXHVEQ0MzXHVEQ0M1LVx1REQwNVx1REQwNy1cdUREMEFcdUREMEQtXHVERDE0XHVERDE2LVx1REQxQ1x1REQxRS1cdUREMzlcdUREM0ItXHVERDNFXHVERDQwLVx1REQ0NFx1REQ0Nlx1REQ0QS1cdURENTBcdURENTItXHVERUE1XHVERUE4LVx1REVDMFx1REVDMi1cdURFREFcdURFREMtXHVERUZBXHVERUZDLVx1REYxNFx1REYxNi1cdURGMzRcdURGMzYtXHVERjRFXHVERjUwLVx1REY2RVx1REY3MC1cdURGODhcdURGOEEtXHVERkE4XHVERkFBLVx1REZDMlx1REZDNC1cdURGQ0JcdURGQ0UtXHVERkZGXXxcdUQ4MzZbXHVERTAwLVx1REUzNlx1REUzQi1cdURFNkNcdURFNzVcdURFODRcdURFOUItXHVERTlGXHVERUExLVx1REVBRl18XHVEODM4W1x1REMwMC1cdURDMDZcdURDMDgtXHVEQzE4XHVEQzFCLVx1REMyMVx1REMyM1x1REMyNFx1REMyNi1cdURDMkFdfFx1RDgzQVtcdURDMDAtXHVEQ0M0XHVEQ0QwLVx1RENENlx1REQwMC1cdURENEFcdURENTAtXHVERDU5XXxcdUQ4M0JbXHVERTAwLVx1REUwM1x1REUwNS1cdURFMUZcdURFMjFcdURFMjJcdURFMjRcdURFMjdcdURFMjktXHVERTMyXHVERTM0LVx1REUzN1x1REUzOVx1REUzQlx1REU0Mlx1REU0N1x1REU0OVx1REU0Qlx1REU0RC1cdURFNEZcdURFNTFcdURFNTJcdURFNTRcdURFNTdcdURFNTlcdURFNUJcdURFNURcdURFNUZcdURFNjFcdURFNjJcdURFNjRcdURFNjctXHVERTZBXHVERTZDLVx1REU3Mlx1REU3NC1cdURFNzdcdURFNzktXHVERTdDXHVERTdFXHVERTgwLVx1REU4OVx1REU4Qi1cdURFOUJcdURFQTEtXHVERUEzXHVERUE1LVx1REVBOVx1REVBQi1cdURFQkJdfFx1RDg2OVtcdURDMDAtXHVERUQ2XHVERjAwLVx1REZGRl18XHVEODZEW1x1REMwMC1cdURGMzRcdURGNDAtXHVERkZGXXxcdUQ4NkVbXHVEQzAwLVx1REMxRFx1REMyMC1cdURGRkZdfFx1RDg3M1tcdURDMDAtXHVERUExXHVERUIwLVx1REZGRl18XHVEODdBW1x1REMwMC1cdURGRTBdfFx1RDg3RVtcdURDMDAtXHVERTFEXXxcdURCNDBbXHVERDAwLVx1RERFRl0vfSxVPXtpc1NwYWNlU2VwYXJhdG9yOmZ1bmN0aW9uKHUpe3JldHVybiJzdHJpbmciPT10eXBlb2YgdSYmRy5TcGFjZV9TZXBhcmF0b3IudGVzdCh1KX0saXNJZFN0YXJ0Q2hhcjpmdW5jdGlvbih1KXtyZXR1cm4ic3RyaW5nIj09dHlwZW9mIHUmJih1Pj0iYSImJnU8PSJ6Inx8dT49IkEiJiZ1PD0iWiJ8fCIkIj09PXV8fCJfIj09PXV8fEcuSURfU3RhcnQudGVzdCh1KSl9LGlzSWRDb250aW51ZUNoYXI6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYodT49ImEiJiZ1PD0ieiJ8fHU+PSJBIiYmdTw9IloifHx1Pj0iMCImJnU8PSI5Inx8IiQiPT09dXx8Il8iPT09dXx8IuKAjCI9PT11fHwi4oCNIj09PXV8fEcuSURfQ29udGludWUudGVzdCh1KSl9LGlzRGlnaXQ6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYvWzAtOV0vLnRlc3QodSl9LGlzSGV4RGlnaXQ6ZnVuY3Rpb24odSl7cmV0dXJuInN0cmluZyI9PXR5cGVvZiB1JiYvWzAtOUEtRmEtZl0vLnRlc3QodSl9fTtmdW5jdGlvbiBaKCl7Zm9yKFQ9ImRlZmF1bHQiLHo9IiIsSD0hMSwkPTE7Oyl7Uj1xKCk7dmFyIHU9WFtUXSgpO2lmKHUpcmV0dXJuIHV9fWZ1bmN0aW9uIHEoKXtpZihfW0ldKXJldHVybiBTdHJpbmcuZnJvbUNvZGVQb2ludChfLmNvZGVQb2ludEF0KEkpKX1mdW5jdGlvbiBXKCl7dmFyIHU9cSgpO3JldHVybiJcbiI9PT11PyhWKyssSj0wKTp1P0orPXUubGVuZ3RoOkorKyx1JiYoSSs9dS5sZW5ndGgpLHV9dmFyIFg9e2RlZmF1bHQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJcdCI6Y2FzZSJcdiI6Y2FzZSJcZiI6Y2FzZSIgIjpjYXNlIiAiOmNhc2UiXHVmZWZmIjpjYXNlIlxuIjpjYXNlIlxyIjpjYXNlIlx1MjAyOCI6Y2FzZSJcdTIwMjkiOnJldHVybiB2b2lkIFcoKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJjb21tZW50Iik7Y2FzZSB2b2lkIDA6cmV0dXJuIFcoKSxLKCJlb2YiKX1pZighVS5pc1NwYWNlU2VwYXJhdG9yKFIpKXJldHVybiBYW09dKCk7VygpfSxjb21tZW50OmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiKiI6cmV0dXJuIFcoKSx2b2lkKFQ9Im11bHRpTGluZUNvbW1lbnQiKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJzaW5nbGVMaW5lQ29tbWVudCIpfXRocm93IHJ1KFcoKSl9LG11bHRpTGluZUNvbW1lbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIqIjpyZXR1cm4gVygpLHZvaWQoVD0ibXVsdGlMaW5lQ29tbWVudEFzdGVyaXNrIik7Y2FzZSB2b2lkIDA6dGhyb3cgcnUoVygpKX1XKCl9LG11bHRpTGluZUNvbW1lbnRBc3RlcmlzazpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIioiOnJldHVybiB2b2lkIFcoKTtjYXNlIi8iOnJldHVybiBXKCksdm9pZChUPSJkZWZhdWx0Iik7Y2FzZSB2b2lkIDA6dGhyb3cgcnUoVygpKX1XKCksVD0ibXVsdGlMaW5lQ29tbWVudCJ9LHNpbmdsZUxpbmVDb21tZW50OmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiXG4iOmNhc2UiXHIiOmNhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6cmV0dXJuIFcoKSx2b2lkKFQ9ImRlZmF1bHQiKTtjYXNlIHZvaWQgMDpyZXR1cm4gVygpLEsoImVvZiIpfVcoKX0sdmFsdWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJ7IjpjYXNlIlsiOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO2Nhc2UibiI6cmV0dXJuIFcoKSxRKCJ1bGwiKSxLKCJudWxsIixudWxsKTtjYXNlInQiOnJldHVybiBXKCksUSgicnVlIiksSygiYm9vbGVhbiIsITApO2Nhc2UiZiI6cmV0dXJuIFcoKSxRKCJhbHNlIiksSygiYm9vbGVhbiIsITEpO2Nhc2UiLSI6Y2FzZSIrIjpyZXR1cm4iLSI9PT1XKCkmJigkPS0xKSx2b2lkKFQ9InNpZ24iKTtjYXNlIi4iOnJldHVybiB6PVcoKSx2b2lkKFQ9ImRlY2ltYWxQb2ludExlYWRpbmciKTtjYXNlIjAiOnJldHVybiB6PVcoKSx2b2lkKFQ9Inplcm8iKTtjYXNlIjEiOmNhc2UiMiI6Y2FzZSIzIjpjYXNlIjQiOmNhc2UiNSI6Y2FzZSI2IjpjYXNlIjciOmNhc2UiOCI6Y2FzZSI5IjpyZXR1cm4gej1XKCksdm9pZChUPSJkZWNpbWFsSW50ZWdlciIpO2Nhc2UiSSI6cmV0dXJuIFcoKSxRKCJuZmluaXR5IiksSygibnVtZXJpYyIsMS8wKTtjYXNlIk4iOnJldHVybiBXKCksUSgiYU4iKSxLKCJudW1lcmljIixOYU4pO2Nhc2UnIic6Y2FzZSInIjpyZXR1cm4gSD0nIic9PT1XKCksej0iIix2b2lkKFQ9InN0cmluZyIpfXRocm93IHJ1KFcoKSl9LGlkZW50aWZpZXJOYW1lU3RhcnRFc2NhcGU6ZnVuY3Rpb24oKXtpZigidSIhPT1SKXRocm93IHJ1KFcoKSk7VygpO3ZhciB1PVkoKTtzd2l0Y2godSl7Y2FzZSIkIjpjYXNlIl8iOmJyZWFrO2RlZmF1bHQ6aWYoIVUuaXNJZFN0YXJ0Q2hhcih1KSl0aHJvdyBudSgpfXorPXUsVD0iaWRlbnRpZmllck5hbWUifSxpZGVudGlmaWVyTmFtZTpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIiQiOmNhc2UiXyI6Y2FzZSLigIwiOmNhc2Ui4oCNIjpyZXR1cm4gdm9pZCh6Kz1XKCkpO2Nhc2UiXFwiOnJldHVybiBXKCksdm9pZChUPSJpZGVudGlmaWVyTmFtZUVzY2FwZSIpfWlmKCFVLmlzSWRDb250aW51ZUNoYXIoUikpcmV0dXJuIEsoImlkZW50aWZpZXIiLHopO3orPVcoKX0saWRlbnRpZmllck5hbWVFc2NhcGU6ZnVuY3Rpb24oKXtpZigidSIhPT1SKXRocm93IHJ1KFcoKSk7VygpO3ZhciB1PVkoKTtzd2l0Y2godSl7Y2FzZSIkIjpjYXNlIl8iOmNhc2Ui4oCMIjpjYXNlIuKAjSI6YnJlYWs7ZGVmYXVsdDppZighVS5pc0lkQ29udGludWVDaGFyKHUpKXRocm93IG51KCl9eis9dSxUPSJpZGVudGlmaWVyTmFtZSJ9LHNpZ246ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIuIjpyZXR1cm4gej1XKCksdm9pZChUPSJkZWNpbWFsUG9pbnRMZWFkaW5nIik7Y2FzZSIwIjpyZXR1cm4gej1XKCksdm9pZChUPSJ6ZXJvIik7Y2FzZSIxIjpjYXNlIjIiOmNhc2UiMyI6Y2FzZSI0IjpjYXNlIjUiOmNhc2UiNiI6Y2FzZSI3IjpjYXNlIjgiOmNhc2UiOSI6cmV0dXJuIHo9VygpLHZvaWQoVD0iZGVjaW1hbEludGVnZXIiKTtjYXNlIkkiOnJldHVybiBXKCksUSgibmZpbml0eSIpLEsoIm51bWVyaWMiLCQqKDEvMCkpO2Nhc2UiTiI6cmV0dXJuIFcoKSxRKCJhTiIpLEsoIm51bWVyaWMiLE5hTil9dGhyb3cgcnUoVygpKX0semVybzpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIi4iOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsUG9pbnQiKTtjYXNlImUiOmNhc2UiRSI6cmV0dXJuIHorPVcoKSx2b2lkKFQ9ImRlY2ltYWxFeHBvbmVudCIpO2Nhc2UieCI6Y2FzZSJYIjpyZXR1cm4geis9VygpLHZvaWQoVD0iaGV4YWRlY2ltYWwiKX1yZXR1cm4gSygibnVtZXJpYyIsMCokKX0sZGVjaW1hbEludGVnZXI6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIuIjpyZXR1cm4geis9VygpLHZvaWQoVD0iZGVjaW1hbFBvaW50Iik7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1pZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxkZWNpbWFsUG9pbnRMZWFkaW5nOmZ1bmN0aW9uKCl7aWYoVS5pc0RpZ2l0KFIpKXJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRnJhY3Rpb24iKTt0aHJvdyBydShXKCkpfSxkZWNpbWFsUG9pbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1yZXR1cm4gVS5pc0RpZ2l0KFIpPyh6Kz1XKCksdm9pZChUPSJkZWNpbWFsRnJhY3Rpb24iKSk6SygibnVtZXJpYyIsJCpOdW1iZXIoeikpfSxkZWNpbWFsRnJhY3Rpb246ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSJlIjpjYXNlIkUiOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnQiKX1pZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxkZWNpbWFsRXhwb25lbnQ6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIrIjpjYXNlIi0iOnJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnRTaWduIil9aWYoVS5pc0RpZ2l0KFIpKXJldHVybiB6Kz1XKCksdm9pZChUPSJkZWNpbWFsRXhwb25lbnRJbnRlZ2VyIik7dGhyb3cgcnUoVygpKX0sZGVjaW1hbEV4cG9uZW50U2lnbjpmdW5jdGlvbigpe2lmKFUuaXNEaWdpdChSKSlyZXR1cm4geis9VygpLHZvaWQoVD0iZGVjaW1hbEV4cG9uZW50SW50ZWdlciIpO3Rocm93IHJ1KFcoKSl9LGRlY2ltYWxFeHBvbmVudEludGVnZXI6ZnVuY3Rpb24oKXtpZighVS5pc0RpZ2l0KFIpKXJldHVybiBLKCJudW1lcmljIiwkKk51bWJlcih6KSk7eis9VygpfSxoZXhhZGVjaW1hbDpmdW5jdGlvbigpe2lmKFUuaXNIZXhEaWdpdChSKSlyZXR1cm4geis9VygpLHZvaWQoVD0iaGV4YWRlY2ltYWxJbnRlZ2VyIik7dGhyb3cgcnUoVygpKX0saGV4YWRlY2ltYWxJbnRlZ2VyOmZ1bmN0aW9uKCl7aWYoIVUuaXNIZXhEaWdpdChSKSlyZXR1cm4gSygibnVtZXJpYyIsJCpOdW1iZXIoeikpO3orPVcoKX0sc3RyaW5nOmZ1bmN0aW9uKCl7c3dpdGNoKFIpe2Nhc2UiXFwiOnJldHVybiBXKCksdm9pZCh6Kz1mdW5jdGlvbigpe3N3aXRjaChxKCkpe2Nhc2UiYiI6cmV0dXJuIFcoKSwiXGIiO2Nhc2UiZiI6cmV0dXJuIFcoKSwiXGYiO2Nhc2UibiI6cmV0dXJuIFcoKSwiXG4iO2Nhc2UiciI6cmV0dXJuIFcoKSwiXHIiO2Nhc2UidCI6cmV0dXJuIFcoKSwiXHQiO2Nhc2UidiI6cmV0dXJuIFcoKSwiXHYiO2Nhc2UiMCI6aWYoVygpLFUuaXNEaWdpdChxKCkpKXRocm93IHJ1KFcoKSk7cmV0dXJuIlwwIjtjYXNlIngiOnJldHVybiBXKCksZnVuY3Rpb24oKXt2YXIgdT0iIixEPXEoKTtpZighVS5pc0hleERpZ2l0KEQpKXRocm93IHJ1KFcoKSk7aWYodSs9VygpLEQ9cSgpLCFVLmlzSGV4RGlnaXQoRCkpdGhyb3cgcnUoVygpKTtyZXR1cm4gdSs9VygpLFN0cmluZy5mcm9tQ29kZVBvaW50KHBhcnNlSW50KHUsMTYpKX0oKTtjYXNlInUiOnJldHVybiBXKCksWSgpO2Nhc2UiXG4iOmNhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6cmV0dXJuIFcoKSwiIjtjYXNlIlxyIjpyZXR1cm4gVygpLCJcbiI9PT1xKCkmJlcoKSwiIjtjYXNlIjEiOmNhc2UiMiI6Y2FzZSIzIjpjYXNlIjQiOmNhc2UiNSI6Y2FzZSI2IjpjYXNlIjciOmNhc2UiOCI6Y2FzZSI5IjpjYXNlIHZvaWQgMDp0aHJvdyBydShXKCkpfXJldHVybiBXKCl9KCkpO2Nhc2UnIic6cmV0dXJuIEg/KFcoKSxLKCJzdHJpbmciLHopKTp2b2lkKHorPVcoKSk7Y2FzZSInIjpyZXR1cm4gSD92b2lkKHorPVcoKSk6KFcoKSxLKCJzdHJpbmciLHopKTtjYXNlIlxuIjpjYXNlIlxyIjp0aHJvdyBydShXKCkpO2Nhc2UiXHUyMDI4IjpjYXNlIlx1MjAyOSI6IWZ1bmN0aW9uKHUpe2NvbnNvbGUud2FybigiSlNPTjU6ICciK0Z1KHUpKyInIGluIHN0cmluZ3MgaXMgbm90IHZhbGlkIEVDTUFTY3JpcHQ7IGNvbnNpZGVyIGVzY2FwaW5nIil9KFIpO2JyZWFrO2Nhc2Ugdm9pZCAwOnRocm93IHJ1KFcoKSl9eis9VygpfSxzdGFydDpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlInsiOmNhc2UiWyI6cmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSl9VD0idmFsdWUifSxiZWZvcmVQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIkIjpjYXNlIl8iOnJldHVybiB6PVcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lIik7Y2FzZSJcXCI6cmV0dXJuIFcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lU3RhcnRFc2NhcGUiKTtjYXNlIn0iOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO2Nhc2UnIic6Y2FzZSInIjpyZXR1cm4gSD0nIic9PT1XKCksdm9pZChUPSJzdHJpbmciKX1pZihVLmlzSWRTdGFydENoYXIoUikpcmV0dXJuIHorPVcoKSx2b2lkKFQ9ImlkZW50aWZpZXJOYW1lIik7dGhyb3cgcnUoVygpKX0sYWZ0ZXJQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtpZigiOiI9PT1SKXJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpO3Rocm93IHJ1KFcoKSl9LGJlZm9yZVByb3BlcnR5VmFsdWU6ZnVuY3Rpb24oKXtUPSJ2YWx1ZSJ9LGFmdGVyUHJvcGVydHlWYWx1ZTpmdW5jdGlvbigpe3N3aXRjaChSKXtjYXNlIiwiOmNhc2UifSI6cmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSl9dGhyb3cgcnUoVygpKX0sYmVmb3JlQXJyYXlWYWx1ZTpmdW5jdGlvbigpe2lmKCJdIj09PVIpcmV0dXJuIEsoInB1bmN0dWF0b3IiLFcoKSk7VD0idmFsdWUifSxhZnRlckFycmF5VmFsdWU6ZnVuY3Rpb24oKXtzd2l0Y2goUil7Y2FzZSIsIjpjYXNlIl0iOnJldHVybiBLKCJwdW5jdHVhdG9yIixXKCkpfXRocm93IHJ1KFcoKSl9LGVuZDpmdW5jdGlvbigpe3Rocm93IHJ1KFcoKSl9fTtmdW5jdGlvbiBLKHUsRCl7cmV0dXJue3R5cGU6dSx2YWx1ZTpELGxpbmU6Vixjb2x1bW46Sn19ZnVuY3Rpb24gUSh1KXtmb3IodmFyIEQ9MCxlPXU7RDxlLmxlbmd0aDtEKz0xKXt2YXIgcj1lW0RdO2lmKHEoKSE9PXIpdGhyb3cgcnUoVygpKTtXKCl9fWZ1bmN0aW9uIFkoKXtmb3IodmFyIHU9IiIsRD00O0QtLSA+MDspe3ZhciBlPXEoKTtpZighVS5pc0hleERpZ2l0KGUpKXRocm93IHJ1KFcoKSk7dSs9VygpfXJldHVybiBTdHJpbmcuZnJvbUNvZGVQb2ludChwYXJzZUludCh1LDE2KSl9dmFyIHV1PXtzdGFydDpmdW5jdGlvbigpe2lmKCJlb2YiPT09TS50eXBlKXRocm93IHR1KCk7RHUoKX0sYmVmb3JlUHJvcGVydHlOYW1lOmZ1bmN0aW9uKCl7c3dpdGNoKE0udHlwZSl7Y2FzZSJpZGVudGlmaWVyIjpjYXNlInN0cmluZyI6cmV0dXJuIGs9TS52YWx1ZSx2b2lkKE89ImFmdGVyUHJvcGVydHlOYW1lIik7Y2FzZSJwdW5jdHVhdG9yIjpyZXR1cm4gdm9pZCBldSgpO2Nhc2UiZW9mIjp0aHJvdyB0dSgpfX0sYWZ0ZXJQcm9wZXJ0eU5hbWU6ZnVuY3Rpb24oKXtpZigiZW9mIj09PU0udHlwZSl0aHJvdyB0dSgpO089ImJlZm9yZVByb3BlcnR5VmFsdWUifSxiZWZvcmVQcm9wZXJ0eVZhbHVlOmZ1bmN0aW9uKCl7aWYoImVvZiI9PT1NLnR5cGUpdGhyb3cgdHUoKTtEdSgpfSxiZWZvcmVBcnJheVZhbHVlOmZ1bmN0aW9uKCl7aWYoImVvZiI9PT1NLnR5cGUpdGhyb3cgdHUoKTsicHVuY3R1YXRvciIhPT1NLnR5cGV8fCJdIiE9PU0udmFsdWU/RHUoKTpldSgpfSxhZnRlclByb3BlcnR5VmFsdWU6ZnVuY3Rpb24oKXtpZigiZW9mIj09PU0udHlwZSl0aHJvdyB0dSgpO3N3aXRjaChNLnZhbHVlKXtjYXNlIiwiOnJldHVybiB2b2lkKE89ImJlZm9yZVByb3BlcnR5TmFtZSIpO2Nhc2UifSI6ZXUoKX19LGFmdGVyQXJyYXlWYWx1ZTpmdW5jdGlvbigpe2lmKCJlb2YiPT09TS50eXBlKXRocm93IHR1KCk7c3dpdGNoKE0udmFsdWUpe2Nhc2UiLCI6cmV0dXJuIHZvaWQoTz0iYmVmb3JlQXJyYXlWYWx1ZSIpO2Nhc2UiXSI6ZXUoKX19LGVuZDpmdW5jdGlvbigpe319O2Z1bmN0aW9uIER1KCl7dmFyIHU7c3dpdGNoKE0udHlwZSl7Y2FzZSJwdW5jdHVhdG9yIjpzd2l0Y2goTS52YWx1ZSl7Y2FzZSJ7Ijp1PXt9O2JyZWFrO2Nhc2UiWyI6dT1bXX1icmVhaztjYXNlIm51bGwiOmNhc2UiYm9vbGVhbiI6Y2FzZSJudW1lcmljIjpjYXNlInN0cmluZyI6dT1NLnZhbHVlfWlmKHZvaWQgMD09PUwpTD11O2Vsc2V7dmFyIEQ9altqLmxlbmd0aC0xXTtBcnJheS5pc0FycmF5KEQpP0QucHVzaCh1KTpPYmplY3QuZGVmaW5lUHJvcGVydHkoRCxrLHt2YWx1ZTp1LHdyaXRhYmxlOiEwLGVudW1lcmFibGU6ITAsY29uZmlndXJhYmxlOiEwfSl9aWYobnVsbCE9PXUmJiJvYmplY3QiPT10eXBlb2YgdSlqLnB1c2godSksTz1BcnJheS5pc0FycmF5KHUpPyJiZWZvcmVBcnJheVZhbHVlIjoiYmVmb3JlUHJvcGVydHlOYW1lIjtlbHNle3ZhciBlPWpbai5sZW5ndGgtMV07Tz1udWxsPT1lPyJlbmQiOkFycmF5LmlzQXJyYXkoZSk/ImFmdGVyQXJyYXlWYWx1ZSI6ImFmdGVyUHJvcGVydHlWYWx1ZSJ9fWZ1bmN0aW9uIGV1KCl7ai5wb3AoKTt2YXIgdT1qW2oubGVuZ3RoLTFdO089bnVsbD09dT8iZW5kIjpBcnJheS5pc0FycmF5KHUpPyJhZnRlckFycmF5VmFsdWUiOiJhZnRlclByb3BlcnR5VmFsdWUifWZ1bmN0aW9uIHJ1KHUpe3JldHVybiBDdSh2b2lkIDA9PT11PyJKU09ONTogaW52YWxpZCBlbmQgb2YgaW5wdXQgYXQgIitWKyI6IitKOiJKU09ONTogaW52YWxpZCBjaGFyYWN0ZXIgJyIrRnUodSkrIicgYXQgIitWKyI6IitKKX1mdW5jdGlvbiB0dSgpe3JldHVybiBDdSgiSlNPTjU6IGludmFsaWQgZW5kIG9mIGlucHV0IGF0ICIrVisiOiIrSil9ZnVuY3Rpb24gbnUoKXtyZXR1cm4gQ3UoIkpTT041OiBpbnZhbGlkIGlkZW50aWZpZXIgY2hhcmFjdGVyIGF0ICIrVisiOiIrKEotPTUpKX1mdW5jdGlvbiBGdSh1KXt2YXIgRD17IiciOiJcXCciLCciJzonXFwiJywiXFwiOiJcXFxcIiwiXGIiOiJcXGIiLCJcZiI6IlxcZiIsIlxuIjoiXFxuIiwiXHIiOiJcXHIiLCJcdCI6IlxcdCIsIlx2IjoiXFx2IiwiXDAiOiJcXDAiLCJcdTIwMjgiOiJcXHUyMDI4IiwiXHUyMDI5IjoiXFx1MjAyOSJ9O2lmKERbdV0pcmV0dXJuIERbdV07aWYodTwiICIpe3ZhciBlPXUuY2hhckNvZGVBdCgwKS50b1N0cmluZygxNik7cmV0dXJuIlxceCIrKCIwMCIrZSkuc3Vic3RyaW5nKGUubGVuZ3RoKX1yZXR1cm4gdX1mdW5jdGlvbiBDdSh1KXt2YXIgRD1uZXcgU3ludGF4RXJyb3IodSk7cmV0dXJuIEQubGluZU51bWJlcj1WLEQuY29sdW1uTnVtYmVyPUosRH1yZXR1cm57cGFyc2U6ZnVuY3Rpb24odSxEKXtfPVN0cmluZyh1KSxPPSJzdGFydCIsaj1bXSxJPTAsVj0xLEo9MCxNPXZvaWQgMCxrPXZvaWQgMCxMPXZvaWQgMDtkb3tNPVooKSx1dVtPXSgpfXdoaWxlKCJlb2YiIT09TS50eXBlKTtyZXR1cm4iZnVuY3Rpb24iPT10eXBlb2YgRD9mdW5jdGlvbiB1KEQsZSxyKXt2YXIgdD1EW2VdO2lmKG51bGwhPXQmJiJvYmplY3QiPT10eXBlb2YgdClpZihBcnJheS5pc0FycmF5KHQpKWZvcih2YXIgbj0wO248dC5sZW5ndGg7bisrKXt2YXIgRj1TdHJpbmcobiksQz11KHQsRixyKTt2b2lkIDA9PT1DP2RlbGV0ZSB0W0ZdOk9iamVjdC5kZWZpbmVQcm9wZXJ0eSh0LEYse3ZhbHVlOkMsd3JpdGFibGU6ITAsZW51bWVyYWJsZTohMCxjb25maWd1cmFibGU6ITB9KX1lbHNlIGZvcih2YXIgQSBpbiB0KXt2YXIgaT11KHQsQSxyKTt2b2lkIDA9PT1pP2RlbGV0ZSB0W0FdOk9iamVjdC5kZWZpbmVQcm9wZXJ0eSh0LEEse3ZhbHVlOmksd3JpdGFibGU6ITAsZW51bWVyYWJsZTohMCxjb25maWd1cmFibGU6ITB9KX1yZXR1cm4gci5jYWxsKEQsZSx0KX0oeyIiOkx9LCIiLEQpOkx9LHN0cmluZ2lmeTpmdW5jdGlvbih1LEQsZSl7dmFyIHIsdCxuLEY9W10sQz0iIixBPSIiO2lmKG51bGw9PUR8fCJvYmplY3QiIT10eXBlb2YgRHx8QXJyYXkuaXNBcnJheShEKXx8KGU9RC5zcGFjZSxuPUQucXVvdGUsRD1ELnJlcGxhY2VyKSwiZnVuY3Rpb24iPT10eXBlb2YgRCl0PUQ7ZWxzZSBpZihBcnJheS5pc0FycmF5KEQpKXtyPVtdO2Zvcih2YXIgaT0wLEU9RDtpPEUubGVuZ3RoO2krPTEpe3ZhciBvPUVbaV0sYT12b2lkIDA7InN0cmluZyI9PXR5cGVvZiBvP2E9bzooIm51bWJlciI9PXR5cGVvZiBvfHxvIGluc3RhbmNlb2YgU3RyaW5nfHxvIGluc3RhbmNlb2YgTnVtYmVyKSYmKGE9U3RyaW5nKG8pKSx2b2lkIDAhPT1hJiZyLmluZGV4T2YoYSk8MCYmci5wdXNoKGEpfX1yZXR1cm4gZSBpbnN0YW5jZW9mIE51bWJlcj9lPU51bWJlcihlKTplIGluc3RhbmNlb2YgU3RyaW5nJiYoZT1TdHJpbmcoZSkpLCJudW1iZXIiPT10eXBlb2YgZT9lPjAmJihlPU1hdGgubWluKDEwLE1hdGguZmxvb3IoZSkpLEE9IiAgICAgICAgICAiLnN1YnN0cigwLGUpKToic3RyaW5nIj09dHlwZW9mIGUmJihBPWUuc3Vic3RyKDAsMTApKSxjKCIiLHsiIjp1fSk7ZnVuY3Rpb24gYyh1LEQpe3ZhciBlPURbdV07c3dpdGNoKG51bGwhPWUmJigiZnVuY3Rpb24iPT10eXBlb2YgZS50b0pTT041P2U9ZS50b0pTT041KHUpOiJmdW5jdGlvbiI9PXR5cGVvZiBlLnRvSlNPTiYmKGU9ZS50b0pTT04odSkpKSx0JiYoZT10LmNhbGwoRCx1LGUpKSxlIGluc3RhbmNlb2YgTnVtYmVyP2U9TnVtYmVyKGUpOmUgaW5zdGFuY2VvZiBTdHJpbmc/ZT1TdHJpbmcoZSk6ZSBpbnN0YW5jZW9mIEJvb2xlYW4mJihlPWUudmFsdWVPZigpKSxlKXtjYXNlIG51bGw6cmV0dXJuIm51bGwiO2Nhc2UhMDpyZXR1cm4idHJ1ZSI7Y2FzZSExOnJldHVybiJmYWxzZSJ9cmV0dXJuInN0cmluZyI9PXR5cGVvZiBlP0IoZSk6Im51bWJlciI9PXR5cGVvZiBlP1N0cmluZyhlKToib2JqZWN0Ij09dHlwZW9mIGU/QXJyYXkuaXNBcnJheShlKT9mdW5jdGlvbih1KXtpZihGLmluZGV4T2YodSk+PTApdGhyb3cgVHlwZUVycm9yKCJDb252ZXJ0aW5nIGNpcmN1bGFyIHN0cnVjdHVyZSB0byBKU09ONSIpO0YucHVzaCh1KTt2YXIgRD1DO0MrPUE7Zm9yKHZhciBlLHI9W10sdD0wO3Q8dS5sZW5ndGg7dCsrKXt2YXIgbj1jKFN0cmluZyh0KSx1KTtyLnB1c2godm9pZCAwIT09bj9uOiJudWxsIil9aWYoMD09PXIubGVuZ3RoKWU9IltdIjtlbHNlIGlmKCIiPT09QSl7dmFyIGk9ci5qb2luKCIsIik7ZT0iWyIraSsiXSJ9ZWxzZXt2YXIgRT0iLFxuIitDLG89ci5qb2luKEUpO2U9IltcbiIrQytvKyIsXG4iK0QrIl0ifXJldHVybiBGLnBvcCgpLEM9RCxlfShlKTpmdW5jdGlvbih1KXtpZihGLmluZGV4T2YodSk+PTApdGhyb3cgVHlwZUVycm9yKCJDb252ZXJ0aW5nIGNpcmN1bGFyIHN0cnVjdHVyZSB0byBKU09ONSIpO0YucHVzaCh1KTt2YXIgRD1DO0MrPUE7Zm9yKHZhciBlLHQsbj1yfHxPYmplY3Qua2V5cyh1KSxpPVtdLEU9MCxvPW47RTxvLmxlbmd0aDtFKz0xKXt2YXIgYT1vW0VdLEI9YyhhLHUpO2lmKHZvaWQgMCE9PUIpe3ZhciBmPXMoYSkrIjoiOyIiIT09QSYmKGYrPSIgIiksZis9QixpLnB1c2goZil9fWlmKDA9PT1pLmxlbmd0aCllPSJ7fSI7ZWxzZSBpZigiIj09PUEpdD1pLmpvaW4oIiwiKSxlPSJ7Iit0KyJ9IjtlbHNle3ZhciBsPSIsXG4iK0M7dD1pLmpvaW4obCksZT0ie1xuIitDK3QrIixcbiIrRCsifSJ9cmV0dXJuIEYucG9wKCksQz1ELGV9KGUpOnZvaWQgMH1mdW5jdGlvbiBCKHUpe2Zvcih2YXIgRD17IiciOi4xLCciJzouMn0sZT17IiciOiJcXCciLCciJzonXFwiJywiXFwiOiJcXFxcIiwiXGIiOiJcXGIiLCJcZiI6IlxcZiIsIlxuIjoiXFxuIiwiXHIiOiJcXHIiLCJcdCI6IlxcdCIsIlx2IjoiXFx2IiwiXDAiOiJcXDAiLCJcdTIwMjgiOiJcXHUyMDI4IiwiXHUyMDI5IjoiXFx1MjAyOSJ9LHI9IiIsdD0wO3Q8dS5sZW5ndGg7dCsrKXt2YXIgRj11W3RdO3N3aXRjaChGKXtjYXNlIiciOmNhc2UnIic6RFtGXSsrLHIrPUY7Y29udGludWU7Y2FzZSJcMCI6aWYoVS5pc0RpZ2l0KHVbdCsxXSkpe3IrPSJcXHgwMCI7Y29udGludWV9fWlmKGVbRl0pcis9ZVtGXTtlbHNlIGlmKEY8IiAiKXt2YXIgQz1GLmNoYXJDb2RlQXQoMCkudG9TdHJpbmcoMTYpO3IrPSJcXHgiKygiMDAiK0MpLnN1YnN0cmluZyhDLmxlbmd0aCl9ZWxzZSByKz1GfXZhciBBPW58fE9iamVjdC5rZXlzKEQpLnJlZHVjZShmdW5jdGlvbih1LGUpe3JldHVybiBEW3VdPERbZV0/dTplfSk7cmV0dXJuIEErKHI9ci5yZXBsYWNlKG5ldyBSZWdFeHAoQSwiZyIpLGVbQV0pKStBfWZ1bmN0aW9uIHModSl7aWYoMD09PXUubGVuZ3RoKXJldHVybiBCKHUpO3ZhciBEPVN0cmluZy5mcm9tQ29kZVBvaW50KHUuY29kZVBvaW50QXQoMCkpO2lmKCFVLmlzSWRTdGFydENoYXIoRCkpcmV0dXJuIEIodSk7Zm9yKHZhciBlPUQubGVuZ3RoO2U8dS5sZW5ndGg7ZSsrKWlmKCFVLmlzSWRDb250aW51ZUNoYXIoU3RyaW5nLmZyb21Db2RlUG9pbnQodS5jb2RlUG9pbnRBdChlKSkpKXJldHVybiBCKHUpO3JldHVybiB1fX19fSk7`;
//#endregion
//#region ../../packages/util/src/logger.ts
var loggingFilter = "*";
var getEnabledNamespaces = () => {
	return loggingFilter.split(",").map((ns) => ns.trim()).filter(Boolean);
};
new Set(getEnabledNamespaces());
var createLogger = (namespace) => {
	return {
		debug: (message, ...args) => {},
		info: (message, ...args) => {},
		warn: (message, ...args) => {},
		error: (message, ...args) => {
			console.error(`[${namespace}] ${message}`, ...args);
		},
		debugIf: (fn) => {}
	};
};
//#endregion
export { revealHiddenCharacters as a, compose as c, map as d, isAnsiOutput as f, require_dist as i, data as l, asyncJsonParse as n, fetchRange as o, stripAnsi as p, asyncJsonParseBytes as r, logFetchInit as s, createLogger as t, loading as u };

//# sourceMappingURL=src.js.map