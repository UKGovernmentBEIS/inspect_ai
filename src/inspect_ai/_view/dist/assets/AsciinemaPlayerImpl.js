import { i as __toESM } from "./rolldown-runtime.js";
import { n as require_react, r as require_jsx_runtime, t as require_compiler_runtime } from "./compiler-runtime.js";
import { t as useLatestRef } from "./useLatestRef.js";
// ../../node_modules/.pnpm/asciinema-player@3.18.0/node_modules/asciinema-player/dist/logging-CQ2B4GZY.js
var import_jsx_runtime = require_jsx_runtime();
var import_compiler_runtime = require_compiler_runtime();
function parseNpt(time) {
	if (typeof time === "number") return time;
	else if (typeof time === "string") return time.split(":").reverse().map(parseFloat).reduce((sum, n, i) => sum + n * Math.pow(60, i));
	else return;
}
function debounce(f, delay) {
	let timeout;
	return function(...args) {
		clearTimeout(timeout);
		timeout = setTimeout(() => f.apply(this, args), delay);
	};
}
function throttle(f, interval) {
	let enableCall = true;
	return function(...args) {
		if (!enableCall) return;
		enableCall = false;
		f.apply(this, args);
		setTimeout(() => enableCall = true, interval);
	};
}
function toErrorPayload(error) {
	return {
		name: typeof error?.name === "string" ? error.name : "Error",
		message: typeof error?.message === "string" ? error.message : String(error)
	};
}
function createTiming(time, rate) {
	return {
		time,
		rate,
		sampledAt: performance.timeOrigin + performance.now()
	};
}
function getTime(timing) {
	if (typeof timing?.time !== "number") return null;
	const elapsed = performance.timeOrigin + performance.now() - timing.sampledAt;
	return timing.time + elapsed / 1e3 * timing.rate;
}
var FULL_HEX_COLOR_REGEX = /^#[0-9a-f]{6}$/;
var SHORT_HEX_COLOR_REGEX = /^#[0-9a-f]{3}$/;
function normalizeHexColor(color, fallback = void 0) {
	if (typeof color !== "string") return fallback;
	const normalized = color.trim().toLowerCase();
	if (FULL_HEX_COLOR_REGEX.test(normalized)) return normalized;
	if (SHORT_HEX_COLOR_REGEX.test(normalized)) return `#${normalized[1]}${normalized[1]}${normalized[2]}${normalized[2]}${normalized[3]}${normalized[3]}`;
	return fallback;
}
function lerpOklab(t, c1, c2) {
	return [
		c1[0] + t * (c2[0] - c1[0]),
		c1[1] + t * (c2[1] - c1[1]),
		c1[2] + t * (c2[2] - c1[2])
	];
}
function hexToOklab(hex) {
	const [r, g, b] = hexToSrgb(hex).map(srgbToLinear);
	const l = .4122214708 * r + .5363325363 * g + .0514459929 * b;
	const m = .2119034982 * r + .6806995451 * g + .1073969566 * b;
	const s = .0883024619 * r + .2817188376 * g + .6299787005 * b;
	const l_ = Math.cbrt(l);
	const m_ = Math.cbrt(m);
	const s_ = Math.cbrt(s);
	return [
		.2104542553 * l_ + .793617785 * m_ - .0040720468 * s_,
		1.9779984951 * l_ - 2.428592205 * m_ + .4505937099 * s_,
		.0259040371 * l_ + .7827717662 * m_ - .808675766 * s_
	];
}
function oklabToHex(lab) {
	const rgb = oklabToSrgb(lab);
	if (isSrgbInGamut(rgb)) return srgbToHex(rgb);
	const [L, C, h] = oklabToOklch(lab);
	let low = 0;
	let high = C;
	let best = [
		L,
		0,
		h
	];
	for (let i = 0; i < 24; i += 1) {
		const mid = (low + high) / 2;
		const candidate = [
			L,
			mid,
			h
		];
		if (isSrgbInGamut(oklabToSrgb(oklchToOklab(candidate)))) {
			low = mid;
			best = candidate;
		} else high = mid;
	}
	return srgbToHex(oklabToSrgb(oklchToOklab(best)));
}
function oklabToSrgb(lab) {
	const L = clamp$1(lab[0], 0, 1);
	const a = lab[1];
	const b = lab[2];
	const l_ = L + .3963377774 * a + .2158037573 * b;
	const m_ = L - .1055613458 * a - .0638541728 * b;
	const s_ = L - .0894841775 * a - 1.291485548 * b;
	const l = l_ ** 3;
	const m = m_ ** 3;
	const s = s_ ** 3;
	const r = 4.0767416621 * l - 3.3077115913 * m + .2309699292 * s;
	const g = -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s;
	const blue = -.0041960863 * l - .7034186147 * m + 1.707614701 * s;
	return [
		linearToSrgb(r),
		linearToSrgb(g),
		linearToSrgb(blue)
	];
}
function oklabToOklch([L, a, b]) {
	return [
		L,
		Math.hypot(a, b),
		Math.atan2(b, a)
	];
}
function oklchToOklab([L, C, h]) {
	return [
		L,
		C * Math.cos(h),
		C * Math.sin(h)
	];
}
function hexToSrgb(hex) {
	return [
		Number.parseInt(hex.slice(1, 3), 16) / 255,
		Number.parseInt(hex.slice(3, 5), 16) / 255,
		Number.parseInt(hex.slice(5, 7), 16) / 255
	];
}
function rgbToHex(r, g, b) {
	return `#${toHexByte(r)}${toHexByte(g)}${toHexByte(b)}`;
}
function srgbToHex(rgb) {
	return rgbToHex(rgb[0] * 255, rgb[1] * 255, rgb[2] * 255);
}
function srgbToLinear(c) {
	if (c <= .04045) return c / 12.92;
	return ((c + .055) / 1.055) ** 2.4;
}
function linearToSrgb(c) {
	if (c <= .0031308) return c * 12.92;
	return 1.055 * c ** (1 / 2.4) - .055;
}
function isSrgbInGamut([r, g, b]) {
	return r >= 0 && r <= 1 && g >= 0 && g <= 1 && b >= 0 && b <= 1;
}
function clamp$1(value, min, max) {
	return Math.max(min, Math.min(max, value));
}
function toHexByte(value) {
	return Math.round(clamp$1(value, 0, 255)).toString(16).padStart(2, "0");
}
var DummyLogger = class {
	log(..._args) {}
	debug(..._args) {}
	info(..._args) {}
	warn(..._args) {}
	error(..._args) {}
};
var PrefixedLogger = class {
	constructor(logger, prefix) {
		this.logger = logger;
		this.prefix = prefix;
	}
	log(message, ...args) {
		this.logger.log(`${this.prefix}${message}`, ...args);
	}
	debug(message, ...args) {
		this.logger.debug(`${this.prefix}${message}`, ...args);
	}
	info(message, ...args) {
		this.logger.info(`${this.prefix}${message}`, ...args);
	}
	warn(message, ...args) {
		this.logger.warn(`${this.prefix}${message}`, ...args);
	}
	error(message, ...args) {
		this.logger.error(`${this.prefix}${message}`, ...args);
	}
};
// ../../node_modules/.pnpm/asciinema-player@3.18.0/node_modules/asciinema-player/dist/core-BMGzPqRb.js
var Stream = class Stream {
	constructor(input, xfs) {
		this.input = typeof input.next === "function" ? input : input[Symbol.iterator]();
		this.xfs = xfs ?? [];
	}
	map(f) {
		return this.transform(Map$1(f));
	}
	flatMap(f) {
		return this.transform(FlatMap(f));
	}
	filter(f) {
		return this.transform(Filter(f));
	}
	take(n) {
		return this.transform(Take(n));
	}
	drop(n) {
		return this.transform(Drop(n));
	}
	transform(f) {
		return new Stream(this.input, this.xfs.concat([f]));
	}
	multiplex(other, comparator) {
		return new Stream(new Multiplexer(this[Symbol.iterator](), other[Symbol.iterator](), comparator));
	}
	toArray() {
		return Array.from(this);
	}
	[Symbol.iterator]() {
		let v = 0;
		let values = [];
		let flushed = false;
		const xf = compose(this.xfs, (val) => values.push(val));
		return { next: () => {
			if (v === values.length) {
				values = [];
				v = 0;
			}
			while (values.length === 0) {
				const next = this.input.next();
				if (next.done) break;
				else xf.step(next.value);
			}
			if (values.length === 0 && !flushed) {
				xf.flush();
				flushed = true;
			}
			if (values.length > 0) return {
				done: false,
				value: values[v++]
			};
			else return { done: true };
		} };
	}
};
function Map$1(f) {
	return (emit) => {
		return (input) => {
			emit(f(input));
		};
	};
}
function FlatMap(f) {
	return (emit) => {
		return (input) => {
			f(input).forEach(emit);
		};
	};
}
function Filter(f) {
	return (emit) => {
		return (input) => {
			if (f(input)) emit(input);
		};
	};
}
function Take(n) {
	let c = 0;
	return (emit) => {
		return (input) => {
			if (c < n) emit(input);
			c += 1;
		};
	};
}
function Drop(n) {
	let c = 0;
	return (emit) => {
		return (input) => {
			c += 1;
			if (c > n) emit(input);
		};
	};
}
function compose(xfs, push) {
	return xfs.reverse().reduce((next, curr) => {
		const xf = toXf(curr(next.step));
		return {
			step: xf.step,
			flush: () => {
				xf.flush();
				next.flush();
			}
		};
	}, toXf(push));
}
function toXf(xf) {
	if (typeof xf === "function") return {
		step: xf,
		flush: () => {}
	};
	else return xf;
}
var Multiplexer = class {
	constructor(left, right, comparator) {
		this.left = left;
		this.right = right;
		this.comparator = comparator;
	}
	[Symbol.iterator]() {
		let leftItem;
		let rightItem;
		return { next: () => {
			if (leftItem === void 0 && this.left !== void 0) {
				const result = this.left.next();
				if (result.done) this.left = void 0;
				else leftItem = result.value;
			}
			if (rightItem === void 0 && this.right !== void 0) {
				const result = this.right.next();
				if (result.done) this.right = void 0;
				else rightItem = result.value;
			}
			if (leftItem === void 0 && rightItem === void 0) return { done: true };
			else if (leftItem === void 0) {
				const value = rightItem;
				rightItem = void 0;
				return {
					done: false,
					value
				};
			} else if (rightItem === void 0) {
				const value = leftItem;
				leftItem = void 0;
				return {
					done: false,
					value
				};
			} else if (this.comparator(leftItem, rightItem)) {
				const value = leftItem;
				leftItem = void 0;
				return {
					done: false,
					value
				};
			} else {
				const value = rightItem;
				rightItem = void 0;
				return {
					done: false,
					value
				};
			}
		} };
	}
};
async function loadFullRecording(src, options) {
	return wrapFullRecording(prepareRecording(await loadRecording(src), options));
}
async function loadRecording(src) {
	const { parser, encoding = "utf-8" } = src;
	return await parser(await doFetch(src), { encoding });
}
function wrapFullRecording(recording) {
	const segment = { start: 0 };
	const markers = recording.events.filter((event) => event[1] === "m").map((event) => [event[0], event[2].label]);
	return {
		cols: recording.cols,
		rows: recording.rows,
		theme: recording.theme,
		duration: recording.duration,
		effectiveStartAt: recording.effectiveStartAt,
		markers,
		segments: [segment],
		async loadSegment(index) {
			if (index !== 0) throw new Error("unknown recording segment");
			return {
				snapshot: {
					cols: recording.cols,
					rows: recording.rows,
					init: ""
				},
				events: recording.events
			};
		}
	};
}
async function doFetch({ url, data, fetchOpts = {} }) {
	if (typeof url === "string") return await doFetchOne(url, fetchOpts);
	else if (Array.isArray(url)) return await Promise.all(url.map((url) => doFetchOne(url, fetchOpts)));
	else if (data !== void 0) {
		if (typeof data === "function") data = data();
		if (!(data instanceof Promise)) data = Promise.resolve(data);
		const value = await data;
		if (typeof value === "string" || value instanceof ArrayBuffer) return new Response(value);
		else return value;
	} else throw new Error("failed fetching recording file: url/data missing in src");
}
async function doFetchOne(url, fetchOpts) {
	const response = await fetch(url, fetchOpts);
	if (!response.ok) throw new Error(`failed fetching recording from ${url}: ${response.status} ${response.statusText}`);
	return response;
}
function prepareRecording(recording, { startAt = 0, idleTimeLimit, inputOffset, markers }) {
	let { events } = recording;
	if (!(events instanceof Stream)) events = new Stream(events);
	startAt = startAt * 1e3;
	idleTimeLimit = idleTimeLimit ?? recording.idleTimeLimit;
	idleTimeLimit = idleTimeLimit !== void 0 ? idleTimeLimit * 1e3 : Infinity;
	inputOffset = inputOffset !== void 0 ? inputOffset * 1e3 : void 0;
	const limiterOutput = { offset: 0 };
	events = events.map(timeLimiter(idleTimeLimit, startAt, limiterOutput));
	if (markers !== void 0) {
		markers = new Stream(markers).map(normalizeMarker);
		events = events.filter((e) => e[1] !== "m").multiplex(markers, (a, b) => a[0] < b[0]);
	}
	events = events.map(markerWrapper());
	events = events.toArray();
	if (inputOffset !== void 0) {
		events = events.map((e) => e[1] === "i" ? [
			e[0] + inputOffset,
			e[1],
			e[2]
		] : e);
		events.sort((a, b) => a[0] - b[0]);
	}
	if (events.length === 0) throw new Error("recording is missing events");
	const duration = events[events.length - 1][0];
	const effectiveStartAt = startAt - limiterOutput.offset;
	return {
		...recording,
		events,
		duration,
		effectiveStartAt
	};
}
function normalizeMarker(marker) {
	return typeof marker === "number" ? [
		marker * 1e3,
		"m",
		""
	] : [
		marker[0] * 1e3,
		"m",
		marker[1]
	];
}
function timeLimiter(idleTimeLimit, startAt, output) {
	let previousTime = 0;
	let shift = 0;
	return function(event) {
		const delta = event[0] - previousTime - idleTimeLimit;
		previousTime = event[0];
		if (delta > 0) {
			shift += delta;
			if (event[0] < startAt) output.offset += delta;
		}
		return [
			event[0] - shift,
			event[1],
			event[2]
		];
	};
}
function markerWrapper() {
	let index = 0;
	return function(event) {
		if (event[1] === "m") return [
			event[0],
			event[1],
			{
				index: index++,
				time: event[0],
				label: event[2]
			}
		];
		else return event;
	};
}
function normalizeTheme(theme) {
	const foreground = normalizeHexColor(theme.foreground);
	const background = normalizeHexColor(theme.background);
	const paletteInput = theme.palette;
	if (paletteInput === void 0) return;
	if (!foreground || !background || paletteInput.length < 8) return;
	const palette = [];
	const limit = Math.min(paletteInput.length, 16);
	for (let i = 0; i < limit; i += 1) {
		const color = normalizeHexColor(paletteInput[i]);
		if (!color) return;
		palette.push(color);
	}
	for (let i = palette.length; i < 16; i += 1) palette.push(palette[i - 8]);
	return {
		foreground,
		background,
		palette
	};
}
function loadSegmentedRecording(src, opts = {}) {
	validateOptions(src, opts);
	return doLoadSegmentedRecording(src, opts);
}
async function doLoadSegmentedRecording(src, { startAt = 0 }) {
	const response = await fetchResponse(src.url, src.fetchOpts ?? {});
	let index;
	try {
		index = await response.json();
	} catch (error) {
		throw new Error(`failed parsing segmented recording index from ${src.url}: ${error.message}`, { cause: error });
	}
	validateIndex(index);
	const duration = index.duration * 1e3;
	const markers = (index.markers ?? []).map(([time, label]) => [time * 1e3, label]);
	const segments = index.segments.map((segment) => ({
		start: segment.start * 1e3,
		url: resolveUrl(segment.url, response.url || src.url)
	}));
	const recording = {
		cols: index.term.cols,
		rows: index.term.rows,
		theme: parseTheme$2(index.term.theme),
		duration,
		effectiveStartAt: Math.min(Math.max(startAt * 1e3, 0), duration),
		markers,
		segments,
		async loadSegment(segmentIndex) {
			if (!Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= segments.length) throw new Error("unknown recording segment");
			const segment = segments[segmentIndex];
			const segmentResponse = await fetchResponse(segment.url, src.fetchOpts ?? {});
			let payload;
			try {
				payload = await segmentResponse.json();
			} catch (error) {
				throw new Error(`failed parsing recording segment from ${segment.url}: ${error.message}`, { cause: error });
			}
			return normalizeSegment(recording, segmentIndex, payload);
		}
	};
	return recording;
}
function validateOptions(src, { idleTimeLimit, markers }) {
	if (typeof src.url !== "string") throw new Error("segmented recording source requires a URL");
	const unsupported = [];
	if (idleTimeLimit !== void 0) unsupported.push("idleTimeLimit");
	if (markers !== void 0) unsupported.push("markers");
	for (const option of [
		"inputOffset",
		"parser",
		"encoding"
	]) if (Object.hasOwn(src, option)) unsupported.push(option);
	if (unsupported.length > 0) throw new Error(`segmented recordings do not support option: ${unsupported.join(", ")}`);
}
function validateIndex(index) {
	if (index?.version !== 1) throw new Error(`unsupported segmented recording version: ${JSON.stringify(index?.version)}`);
	validateFiniteTime(index.duration, "recording duration");
	validateTerminalSize(index.term, "recording terminal");
	if (!Array.isArray(index.segments) || index.segments.length === 0) throw new Error("segmented recording index is missing segments");
	let previousStart = -1;
	index.segments.forEach((segment, i) => {
		validateFiniteTime(segment?.start, `segment ${i} start`);
		if (typeof segment?.url !== "string" || segment.url.length === 0) throw new Error(`segment ${i} is missing its URL`);
		if (i === 0 && segment.start !== 0) throw new Error("first segment must start at 0");
		if (i > 0 && (segment.start <= previousStart || segment.start >= index.duration)) throw new Error(`segment ${i} start must be strictly increasing and before duration`);
		previousStart = segment.start;
	});
	if (index.markers !== void 0 && !Array.isArray(index.markers)) throw new Error("segmented recording markers must be an array");
	let previousMarkerTime = -1;
	for (const [i, marker] of (index.markers ?? []).entries()) {
		if (!Array.isArray(marker) || marker.length !== 2 || typeof marker[1] !== "string") throw new Error(`invalid marker ${i} in segmented recording index`);
		validateFiniteTime(marker[0], `marker ${i} time`);
		if (marker[0] < previousMarkerTime || marker[0] > index.duration) throw new Error(`marker ${i} time is out of order or range`);
		previousMarkerTime = marker[0];
	}
}
function normalizeSegment(recording, index, payload) {
	const snapshot = payload?.snapshot;
	validateTerminalSize(snapshot, `segment ${index} snapshot`);
	if (typeof snapshot.init !== "string") throw new Error(`segment ${index} snapshot init must be a string`);
	if (!Array.isArray(payload.events) || payload.events.length === 0) throw new Error(`segment ${index} is missing events`);
	const start = recording.segments[index].start;
	const end = recording.segments[index + 1]?.start ?? recording.duration;
	let previousTime = -1;
	let markerIndex = recording.markers.findIndex(([time]) => time >= start);
	if (markerIndex === -1) markerIndex = recording.markers.length;
	const events = payload.events.map((event, eventIndex) => {
		if (!Array.isArray(event) || event.length !== 3 || typeof event[1] !== "string") throw new Error(`invalid event ${eventIndex} in segment ${index}`);
		const time = event[0] * 1e3;
		validateFiniteTime(time, `event ${eventIndex} time in segment ${index}`, true);
		if (time < previousTime || time < start || (index + 1 < recording.segments.length ? time >= end : time > end)) throw new Error(`event ${eventIndex} time is out of range in segment ${index}`);
		previousTime = time;
		if (event[1] === "m") {
			if (typeof event[2] !== "string") throw new Error(`marker event ${eventIndex} in segment ${index} must have a string label`);
			return [
				time,
				"m",
				{
					index: markerIndex++,
					time,
					label: event[2]
				}
			];
		}
		return [
			time,
			event[1],
			event[2]
		];
	});
	if (index > 0 && events[0][0] !== start) throw new Error(`segment ${index} first event must match its start`);
	if (index === recording.segments.length - 1 && events[events.length - 1][0] !== recording.duration) throw new Error("final segment event must match recording duration");
	return {
		snapshot: {
			cols: snapshot.cols,
			rows: snapshot.rows,
			init: snapshot.init
		},
		events
	};
}
async function fetchResponse(url, fetchOpts) {
	const response = await fetch(url, fetchOpts);
	if (!response.ok) throw new Error(`failed fetching recording from ${url}: ${response.status} ${response.statusText}`);
	return response;
}
function validateFiniteTime(value, label, milliseconds = false) {
	if (!Number.isFinite(value) || value < 0) throw new Error(`${label} must be a finite non-negative ${milliseconds ? "millisecond" : "second"} value`);
}
function validateTerminalSize(term, label) {
	if (!Number.isInteger(term?.cols) || term.cols <= 0 || !Number.isInteger(term?.rows) || term.rows <= 0) throw new Error(`${label} must have positive integer cols and rows`);
}
function parseTheme$2(theme) {
	return normalizeTheme({
		foreground: theme?.fg,
		background: theme?.bg,
		palette: typeof theme?.palette === "string" ? theme.palette.split(":") : void 0
	});
}
function resolveUrl(url, indexUrl) {
	return new URL(url, new URL(indexUrl, globalThis.location?.href ?? "http://localhost/")).href;
}
function recording(src, { dispatch, logger }, { speed, idleTimeLimit, startAt, preload, loop, poster, markers: markers_, pauseOnMarkers, cols: optionCols, rows: optionRows, audioUrl }) {
	const STATE = {
		COLD: "cold",
		LOADING: "loading",
		READY_INITIAL: "ready.initial",
		READY_PAUSED: "ready.paused",
		READY_STARTING: "ready.starting",
		READY_PLAYING: "ready.playing",
		READY_BUFFERING_WHILE_PAUSED: "ready.buffering.whilePaused",
		READY_BUFFERING_TO_RESUME: "ready.buffering.toResume",
		READY_ENDED: "ready.ended",
		FAILED: "failed",
		STOPPED: "stopped"
	};
	const EVENT = {
		INIT_REQUESTED: "initRequested",
		PLAY_REQUESTED: "playRequested",
		DEFERRED_PLAY_READY: "deferredPlayReady",
		PAUSE_REQUESTED: "pauseRequested",
		SEEK_REQUESTED: "seekRequested",
		STEP_REQUESTED: "stepRequested",
		STOP_REQUESTED: "stopRequested",
		LOAD_SUCCEEDED: "loadSucceeded",
		LOAD_FAILED: "loadFailed",
		PLAYBACK_START_CONFIRMED: "playbackStartConfirmed",
		PLAYBACK_START_REJECTED: "playbackStartRejected",
		PLAYBACK_ENDED: "playbackEnded",
		AUDIO_WAITING: "audioWaiting",
		AUDIO_PLAYING: "audioPlaying",
		SEGMENT_WAITING: "segmentWaiting",
		SEGMENT_READY: "segmentReady",
		MARKER_REACHED: "markerReached"
	};
	const PLAYBACK_START_REASON = {
		PLAY: "play",
		SEEK: "seek"
	};
	const outputBatchWindow = (src.minFrameTime ?? 1 / 60) * 1e3;
	let now = () => performance.now() * speed;
	let state = STATE.COLD;
	let queuedDriverEvents = [];
	let processingDriverEvents = false;
	const ctx = {
		recording: void 0,
		segmentIndex: void 0,
		segment: void 0,
		segmentCache: /* @__PURE__ */ new Map(),
		positionGeneration: 0,
		markers: void 0,
		duration: void 0,
		effectiveStartAt: void 0,
		recordingEventTimeoutId: void 0,
		audioTimingIntervalId: void 0,
		nextEventIndex: 0,
		lastEventTime: 0,
		startTime: void 0,
		pauseElapsedTime: void 0,
		playCount: 0,
		waitingTimeout: void 0,
		loadingTimeout: void 0,
		audioCtx: void 0,
		audioElement: void 0,
		audioSeekable: false,
		loaded: void 0,
		posterVisible: false,
		posterRenderableAfterLoad: poster !== void 0,
		failureError: null,
		segmentWaiting: false
	};
	function isBufferingState(value = state) {
		return value === STATE.READY_BUFFERING_WHILE_PAUSED || value === STATE.READY_BUFFERING_TO_RESUME;
	}
	function canLoopPlayback() {
		return loop === true || typeof loop === "number" && ctx.playCount < loop;
	}
	function loadPromise(initialTime) {
		if (ctx.loaded === void 0) {
			ctx.loaded = load(initialTime);
			ctx.loaded.catch(() => {});
		}
		return ctx.loaded;
	}
	function transition(currentState, event, payload = {}) {
		switch (event) {
			case EVENT.INIT_REQUESTED:
				if (currentState === STATE.COLD) {
					if (preload || poster?.type == "npt") return {
						nextState: STATE.LOADING,
						action: () => loadPromise()
					};
					if (poster?.type == "text") return {
						nextState: currentState,
						action: () => renderTextPoster()
					};
				}
				return { nextState: currentState };
			case EVENT.LOAD_SUCCEEDED:
				if (currentState !== STATE.LOADING) return { nextState: currentState };
				return {
					nextState: STATE.READY_INITIAL,
					action: () => {
						dispatch("metadata", {
							duration: ctx.duration / 1e3,
							markers: ctx.markers.map(([t, label]) => [t / 1e3, label]),
							hasAudio: payload.hasAudio
						});
						resetTerminalFromSnapshot(ctx.segment);
						renderPoster();
						reportTiming();
					}
				};
			case EVENT.LOAD_FAILED:
				if (currentState !== STATE.LOADING) return { nextState: currentState };
				return {
					nextState: STATE.FAILED,
					action: () => {
						ctx.failureError = payload.error;
						reportTiming();
						dispatch("error", toErrorPayload(payload.error));
					}
				};
			case EVENT.PLAY_REQUESTED:
				if (currentState === STATE.COLD) return {
					nextState: STATE.LOADING,
					action: () => {
						clearPoster();
						dispatch("play");
						return loadPromise().then(() => sendDriverEvent(EVENT.DEFERRED_PLAY_READY));
					}
				};
				if (currentState === STATE.READY_INITIAL || currentState === STATE.READY_PAUSED || currentState === STATE.READY_ENDED) return {
					nextState: STATE.READY_STARTING,
					action: () => {
						dispatch("play");
						clearPoster();
						return startPlayback(PLAYBACK_START_REASON.PLAY);
					}
				};
				if (currentState === STATE.READY_BUFFERING_WHILE_PAUSED) return {
					nextState: STATE.READY_BUFFERING_TO_RESUME,
					action: () => {
						dispatch("play");
						if (ctx.segmentWaiting) return true;
						if (ctx.audioElement) return ctx.audioElement.play().catch((error) => {
							sendDriverEvent(EVENT.PLAYBACK_START_REJECTED);
							throw error;
						});
						return true;
					}
				};
				if (currentState === STATE.READY_BUFFERING_TO_RESUME || currentState === STATE.READY_PLAYING) return {
					nextState: currentState,
					action: () => {
						dispatch("play");
						return true;
					}
				};
				return { nextState: currentState };
			case EVENT.DEFERRED_PLAY_READY:
				if (currentState === STATE.READY_INITIAL) return {
					nextState: STATE.READY_STARTING,
					action: () => {
						clearPoster();
						return startPlayback(PLAYBACK_START_REASON.PLAY);
					}
				};
				return { nextState: currentState };
			case EVENT.PLAYBACK_START_CONFIRMED:
				if (currentState !== STATE.READY_STARTING) return { nextState: currentState };
				return {
					nextState: STATE.READY_PLAYING,
					action: () => {
						confirmPlaybackClockStart();
						if (payload.reason === PLAYBACK_START_REASON.SEEK) dispatch("seeked");
						else dispatch("playing");
						return true;
					}
				};
			case EVENT.PLAYBACK_START_REJECTED:
				if (currentState === STATE.READY_STARTING) return { nextState: STATE.READY_PAUSED };
				if (currentState === STATE.READY_BUFFERING_TO_RESUME) return { nextState: STATE.READY_BUFFERING_WHILE_PAUSED };
				return { nextState: currentState };
			case EVENT.PLAYBACK_ENDED:
				if (currentState !== STATE.READY_PLAYING) return { nextState: currentState };
				if (canLoopPlayback()) return {
					nextState: STATE.READY_PLAYING,
					action: restartLoop
				};
				return {
					nextState: STATE.READY_ENDED,
					action: finishPlayback
				};
			case EVENT.AUDIO_WAITING:
				if (currentState === STATE.READY_PLAYING) return {
					nextState: STATE.READY_BUFFERING_TO_RESUME,
					action: () => {
						logger.debug("pausing session playback");
						pausePlaybackClock();
						restartWaitingTimeout();
					}
				};
				if (currentState === STATE.READY_BUFFERING_WHILE_PAUSED || currentState === STATE.READY_BUFFERING_TO_RESUME) return {
					nextState: currentState,
					action: restartWaitingTimeout
				};
				return { nextState: currentState };
			case EVENT.AUDIO_PLAYING:
				if (ctx.segmentWaiting) return { nextState: currentState };
				if (currentState === STATE.READY_BUFFERING_TO_RESUME) return {
					nextState: STATE.READY_PLAYING,
					action: () => {
						logger.debug("resuming session playback");
						clearWaitingTimeout();
						confirmPlaybackClockStart();
						dispatch("playing");
					}
				};
				if (currentState === STATE.READY_BUFFERING_WHILE_PAUSED) return {
					nextState: STATE.READY_PAUSED,
					action: () => {
						clearWaitingTimeout();
					}
				};
				return { nextState: currentState };
			case EVENT.SEGMENT_WAITING:
				if (currentState === STATE.READY_PLAYING) return {
					nextState: STATE.READY_BUFFERING_TO_RESUME,
					action: () => {
						ctx.segmentWaiting = true;
						pausePlaybackAt(payload.time);
						restartWaitingTimeout();
						if (ctx.audioElement) ctx.audioElement.pause();
					}
				};
				return { nextState: currentState };
			case EVENT.SEGMENT_READY:
				ctx.segmentWaiting = false;
				if (currentState === STATE.READY_BUFFERING_TO_RESUME) return {
					nextState: currentState,
					action: resumeAfterSegmentWait
				};
				if (currentState === STATE.READY_BUFFERING_WHILE_PAUSED) return {
					nextState: STATE.READY_PAUSED,
					action: clearWaitingTimeout
				};
				return { nextState: currentState };
			case EVENT.PAUSE_REQUESTED:
				if (currentState === STATE.READY_PLAYING) return {
					nextState: STATE.READY_PAUSED,
					action: performPause
				};
				if (currentState === STATE.READY_BUFFERING_TO_RESUME) return {
					nextState: STATE.READY_BUFFERING_WHILE_PAUSED,
					action: () => {
						if (ctx.audioElement) ctx.audioElement.pause();
						return true;
					}
				};
				return {
					nextState: currentState,
					action: () => true
				};
			case EVENT.SEEK_REQUESTED: {
				if (currentState === STATE.COLD) return {
					nextState: STATE.LOADING,
					action: () => loadPromise(typeof payload.where === "number" ? payload.where * 1e3 : void 0).then(() => seek(payload.where))
				};
				if (isBufferingState(currentState) && !ctx.segmentWaiting) return {
					nextState: currentState,
					action: () => false
				};
				if (currentState !== STATE.READY_INITIAL && currentState !== STATE.READY_PAUSED && currentState !== STATE.READY_ENDED && currentState !== STATE.READY_PLAYING && currentState !== STATE.READY_BUFFERING_WHILE_PAUSED && currentState !== STATE.READY_BUFFERING_TO_RESUME) return { nextState: currentState };
				const seekOperation = payload.seekOperation;
				if (seekOperation.noOp) return {
					nextState: currentState,
					action: () => false
				};
				return {
					nextState: seekOperation.reachedEnd ? STATE.READY_ENDED : currentState === STATE.READY_PLAYING || currentState === STATE.READY_BUFFERING_TO_RESUME ? STATE.READY_STARTING : STATE.READY_PAUSED,
					action: () => {
						clearPoster();
						return performSeek(seekOperation, currentState);
					}
				};
			}
			case EVENT.STEP_REQUESTED:
				if (currentState === STATE.COLD) return {
					nextState: STATE.LOADING,
					action: () => loadPromise().then(() => sendCommand(EVENT.STEP_REQUESTED, payload))
				};
				if (currentState === STATE.READY_PLAYING || isBufferingState(currentState)) return { nextState: currentState };
				if (currentState !== STATE.READY_INITIAL && currentState !== STATE.READY_PAUSED && currentState !== STATE.READY_ENDED) return { nextState: currentState };
				return {
					nextState: currentState,
					action: () => performStep(payload.n)
				};
			case EVENT.MARKER_REACHED:
				if (currentState !== STATE.READY_PLAYING) return { nextState: currentState };
				if (pauseOnMarkers) return {
					nextState: STATE.READY_PAUSED,
					action: () => {
						dispatchMarker(payload.data);
						return performPause(payload.time);
					}
				};
				return {
					nextState: currentState,
					action: () => dispatchMarker(payload.data)
				};
			case EVENT.STOP_REQUESTED: return {
				nextState: STATE.STOPPED,
				action: teardown
			};
			default: return { nextState: currentState };
		}
	}
	function enqueueDriverEvent(event, payload = {}) {
		queuedDriverEvents.push({
			event,
			payload
		});
	}
	function processDriverEvent(event, payload = {}) {
		const { nextState, action } = transition(state, event, payload);
		if (nextState !== state) state = nextState;
		return action?.();
	}
	function failDriver(error) {
		if (ctx.failureError || state === STATE.STOPPED) return;
		pausePlaybackAt(getCurrentTimeMs());
		queuedDriverEvents.length = 0;
		ctx.segmentWaiting = false;
		cancelPendingTimers();
		if (ctx.audioElement) ctx.audioElement.pause();
		ctx.failureError = error;
		state = STATE.FAILED;
		dispatch("error", toErrorPayload(error));
	}
	function assertCommandAllowed() {
		if (ctx.failureError) throw ctx.failureError;
		if (state === STATE.STOPPED) throw new Error("driver has been stopped");
	}
	function sendCommand(event, payload = {}) {
		assertCommandAllowed();
		return sendDriverEvent(event, payload);
	}
	function sendDriverEvent(event, payload = {}) {
		if (ctx.failureError || state === STATE.STOPPED) return;
		if (processingDriverEvents) throw new Error("re-entrant sendDriverEvent() is not allowed during queue processing");
		processingDriverEvents = true;
		try {
			const result = processDriverEvent(event, payload);
			while (queuedDriverEvents.length > 0) {
				const queuedEvent = queuedDriverEvents.shift();
				processDriverEvent(queuedEvent.event, queuedEvent.payload);
			}
			return result;
		} catch (error) {
			failDriver(error);
			throw error;
		} finally {
			processingDriverEvents = false;
			queuedDriverEvents.length = 0;
		}
	}
	function raiseDriverEvent(event, payload = {}) {
		if (processingDriverEvents) {
			enqueueDriverEvent(event, payload);
			return true;
		}
		return sendDriverEvent(event, payload);
	}
	function init() {
		return sendCommand(EVENT.INIT_REQUESTED);
	}
	async function load(requestedInitialTime) {
		const generation = ctx.positionGeneration;
		ctx.loadingTimeout = setTimeout(() => {
			dispatch("loading");
		}, 3e3);
		try {
			const loadedRecording = loadRecordingSource(src, {
				idleTimeLimit,
				startAt,
				markers: markers_,
				inputOffset: src.inputOffset
			});
			const audioLoaded = loadAudio(audioUrl).catch((error) => {
				logger.warn(`audio load failed: ${error.message}`);
				return false;
			});
			const recording = await loadedRecording;
			if (generation !== ctx.positionGeneration) return false;
			ctx.recording = recording;
			ctx.duration = recording.duration;
			ctx.effectiveStartAt = recording.effectiveStartAt;
			ctx.markers = recording.markers;
			const segmentIndex = findSegmentIndex(recording, requestedInitialTime ?? (poster?.type === "npt" ? poster.value * 1e3 : ctx.effectiveStartAt) ?? 0);
			const segment = await getSegment(segmentIndex, true);
			if (generation !== ctx.positionGeneration) return false;
			activateSegment(segmentIndex, segment);
			const hasAudio = await audioLoaded;
			if (generation !== ctx.positionGeneration) return false;
			sendDriverEvent(EVENT.LOAD_SUCCEEDED, { hasAudio });
		} catch (e) {
			raiseDriverEvent(EVENT.LOAD_FAILED, { error: e });
			throw e;
		} finally {
			clearLoadingTimeout();
		}
	}
	async function loadAudio(audioUrl) {
		if (!audioUrl) return false;
		ctx.audioElement = await createAudioElement(audioUrl);
		ctx.audioSeekable = !Number.isNaN(ctx.audioElement.duration) && ctx.audioElement.duration !== Infinity && ctx.audioElement.seekable.length > 0 && ctx.audioElement.seekable.end(ctx.audioElement.seekable.length - 1) === ctx.audioElement.duration;
		if (ctx.audioSeekable) {
			ctx.audioElement.addEventListener("playing", onAudioPlaying);
			ctx.audioElement.addEventListener("waiting", onAudioWaiting);
		} else logger.warn(`audio is not seekable - you must enable range request support on the server providing ${ctx.audioElement.src} for audio seeking to work`);
		return true;
	}
	function renderPoster() {
		if (!ctx.posterRenderableAfterLoad) return;
		if (poster.type == "npt") syncActiveSegmentToTime(poster.value * 1e3, false, false);
		else if (poster.type == "text") feed(poster.value);
		ctx.posterVisible = true;
	}
	function clearPoster() {
		if (ctx.posterVisible) feed("\x1Bc");
		ctx.posterVisible = false;
		ctx.posterRenderableAfterLoad = false;
	}
	function activateSegment(index, segment) {
		ctx.segmentIndex = index;
		ctx.segment = segment;
		ctx.nextEventIndex = 0;
		ctx.lastEventTime = ctx.recording.segments[index].start;
	}
	function getSegment(index, required = false) {
		let entry = ctx.segmentCache.get(index);
		if (entry === void 0) {
			entry = {};
			entry.promise = ctx.recording.loadSegment(index).then((data) => {
				if (ctx.segmentCache.get(index) === entry) entry.data = data;
				return data;
			}, (error) => {
				if (ctx.segmentCache.get(index) === entry) ctx.segmentCache.delete(index);
				if (!required) logger.warn(`segment prefetch failed: ${error.message}`);
				throw error;
			});
			ctx.segmentCache.set(index, entry);
			if (!required) entry.promise.catch(() => {});
		}
		return entry.promise;
	}
	async function getRequiredSegment(index, generation, onWaiting) {
		if (ctx.segmentCache.get(index)?.data === void 0) onWaiting?.();
		try {
			return await getSegment(index, true);
		} catch (error) {
			if (generation === ctx.positionGeneration && state !== STATE.STOPPED) failDriver(error);
			throw error;
		}
	}
	function retainSegments(indexes) {
		const retained = new Set(indexes.filter((index) => index >= 0));
		for (const index of ctx.segmentCache.keys()) if (!retained.has(index)) ctx.segmentCache.delete(index);
	}
	function prefetchNextSegment() {
		const lastIndex = ctx.recording.segments.length - 1;
		const nextIndex = ctx.segmentIndex < lastIndex ? ctx.segmentIndex + 1 : canLoopPlayback() ? 0 : void 0;
		retainSegments([
			ctx.segmentIndex - 1,
			ctx.segmentIndex,
			nextIndex
		]);
		if (nextIndex !== void 0) getSegment(nextIndex);
	}
	async function advanceSegment() {
		const nextIndex = ctx.segmentIndex + 1;
		const boundary = ctx.recording.segments[nextIndex].start;
		const generation = ++ctx.positionGeneration;
		try {
			const segment = await getRequiredSegment(nextIndex, generation, () => {
				sendDriverEvent(EVENT.SEGMENT_WAITING, { time: boundary });
			});
			if (generation !== ctx.positionGeneration || state === STATE.STOPPED) return;
			activateSegment(nextIndex, segment);
			prefetchNextSegment();
			if (state === STATE.READY_BUFFERING_TO_RESUME || state === STATE.READY_BUFFERING_WHILE_PAUSED) await sendDriverEvent(EVENT.SEGMENT_READY);
			else if (state === STATE.READY_PLAYING) scheduleNextRecordingEvent();
		} catch {}
	}
	function pausePlaybackAt(time) {
		cancelScheduledRecordingEvent();
		clearInterval(ctx.audioTimingIntervalId);
		ctx.pauseElapsedTime = time;
		reportTiming();
	}
	function resumeAfterSegmentWait() {
		clearWaitingTimeout();
		if (ctx.audioElement) return ctx.audioElement.play().then(() => sendDriverEvent(EVENT.AUDIO_PLAYING), (error) => {
			sendDriverEvent(EVENT.PLAYBACK_START_REJECTED);
			logger.warn(`audio resume failed: ${error.message}`);
			return false;
		});
		enqueueDriverEvent(EVENT.AUDIO_PLAYING);
	}
	function scheduleNextRecordingEvent() {
		const nextEvent = ctx.segment.events[ctx.nextEventIndex];
		if (nextEvent) ctx.recordingEventTimeoutId = scheduleAt(runDueRecordingEvents, nextEvent[0]);
		else if (ctx.segmentIndex < ctx.recording.segments.length - 1) {
			const boundary = ctx.recording.segments[ctx.segmentIndex + 1].start;
			ctx.recordingEventTimeoutId = scheduleAt(advanceSegment, boundary);
		} else raiseDriverEvent(EVENT.PLAYBACK_ENDED);
	}
	function scheduleAt(f, targetTime) {
		let timeout = (targetTime - (now() - ctx.startTime)) / speed;
		if (timeout < 0) timeout = 0;
		return setTimeout(f, timeout);
	}
	function runDueRecordingEvents() {
		while (ctx.segment.events[ctx.nextEventIndex] !== void 0) {
			if (applyNextRecordingEvents()) return;
			const nextEvent = ctx.segment.events[ctx.nextEventIndex];
			if (nextEvent === void 0) break;
			if (now() - ctx.startTime <= nextEvent[0]) break;
		}
		scheduleNextRecordingEvent();
	}
	function applyNextRecordingEvents() {
		const event = ctx.segment.events[ctx.nextEventIndex];
		if (event[1] === "o") {
			applyOutputGroup();
			return false;
		}
		ctx.lastEventTime = event[0];
		ctx.nextEventIndex++;
		return applyRecordingEvent(event);
	}
	function applyOutputGroup() {
		const firstEvent = ctx.segment.events[ctx.nextEventIndex];
		const batchDeadline = firstEvent[0] + outputBatchWindow;
		const output = [];
		let event = firstEvent;
		while (event !== void 0 && event[1] === "o" && event[0] < batchDeadline) {
			output.push(event[2]);
			ctx.lastEventTime = event[0];
			ctx.nextEventIndex++;
			event = ctx.segment.events[ctx.nextEventIndex];
		}
		feed(output);
	}
	function cancelScheduledRecordingEvent() {
		clearTimeout(ctx.recordingEventTimeoutId);
		ctx.recordingEventTimeoutId = null;
	}
	async function teardownAudio() {
		clearTimeout(ctx.waitingTimeout);
		if (ctx.audioElement) {
			ctx.audioElement.removeEventListener("playing", onAudioPlaying);
			ctx.audioElement.removeEventListener("waiting", onAudioWaiting);
			ctx.audioElement.pause();
			ctx.audioElement.src = "";
			ctx.audioElement.load();
			ctx.audioElement = void 0;
		}
		if (ctx.audioCtx) {
			await ctx.audioCtx.close();
			ctx.audioCtx = void 0;
		}
	}
	function applyRecordingEvent(event) {
		const [time, type, data] = event;
		if (type === "o") feed(data);
		else if (type === "i") dispatch("input", { data });
		else if (type === "r") {
			const [cols, rows] = data.split("x").map((n) => Number.parseInt(n, 10));
			dispatch("resize", effectiveSize(cols, rows));
		} else if (type === "m") return sendDriverEvent(EVENT.MARKER_REACHED, {
			data,
			time
		}) === true;
		return false;
	}
	function play() {
		return sendCommand(EVENT.PLAY_REQUESTED);
	}
	function pause() {
		return sendCommand(EVENT.PAUSE_REQUESTED);
	}
	function pausePlaybackClock(time = now() - ctx.startTime) {
		pausePlaybackAt(time);
	}
	function preparePlaybackClock() {
		if (ctx.audioElement && !ctx.audioCtx) setupAudioCtx();
	}
	function confirmPlaybackClockStart() {
		ctx.startTime = now() - (ctx.pauseElapsedTime ?? 0);
		ctx.pauseElapsedTime = null;
		reportTiming();
		if (ctx.audioCtx) {
			clearInterval(ctx.audioTimingIntervalId);
			ctx.audioTimingIntervalId = setInterval(reportTiming, 1e3);
		}
		scheduleNextRecordingEvent();
	}
	function seek(where) {
		assertCommandAllowed();
		validateSeekInput(where);
		if (state === STATE.COLD) return sendDriverEvent(EVENT.SEEK_REQUESTED, { where });
		return sendDriverEvent(EVENT.SEEK_REQUESTED, { seekOperation: resolveSeek(state, where) });
	}
	function findMarkerTimeBefore(time) {
		if (ctx.markers.length == 0) return;
		let i = 0;
		let marker = ctx.markers[i];
		let lastMarkerTimeBefore;
		while (marker && marker[0] < time) {
			lastMarkerTimeBefore = marker[0];
			marker = ctx.markers[++i];
		}
		return lastMarkerTimeBefore;
	}
	function findMarkerTimeAfter(time) {
		if (ctx.markers.length == 0) return;
		let i = ctx.markers.length - 1;
		let marker = ctx.markers[i];
		let firstMarkerTimeAfter;
		while (marker && marker[0] > time) {
			firstMarkerTimeAfter = marker[0];
			marker = ctx.markers[--i];
		}
		return firstMarkerTimeAfter;
	}
	function step(n) {
		return sendCommand(EVENT.STEP_REQUESTED, { n });
	}
	function getDuration() {
		return ctx.duration === void 0 ? void 0 : ctx.duration / 1e3;
	}
	function getCurrentTimeMs() {
		if (ctx.pauseElapsedTime === null) return now() - ctx.startTime;
		else return ctx.pauseElapsedTime ?? 0;
	}
	function getTiming() {
		const rate = ctx.pauseElapsedTime === null ? ctx.audioCtx ? 1 : speed : 0;
		return createTiming(getCurrentTimeMs() / 1e3, rate);
	}
	function reportTiming() {
		dispatch("timing", getTiming());
	}
	function setupAudioCtx() {
		ctx.audioCtx = new AudioContext({ latencyHint: "interactive" });
		ctx.audioCtx.createMediaElementSource(ctx.audioElement).connect(ctx.audioCtx.destination);
		now = audioNow;
	}
	function audioNow() {
		if (!ctx.audioCtx) throw new Error("audio context not started - can't tell time!");
		const { contextTime, performanceTime } = ctx.audioCtx.getOutputTimestamp();
		return performanceTime === 0 ? contextTime * 1e3 : contextTime * 1e3 + (performance.now() - performanceTime);
	}
	function onAudioWaiting() {
		logger.debug("audio buffering");
		sendDriverEvent(EVENT.AUDIO_WAITING);
	}
	function onAudioPlaying() {
		logger.debug("audio resumed");
		sendDriverEvent(EVENT.AUDIO_PLAYING);
	}
	function mute() {
		if (ctx.audioElement) {
			ctx.audioElement.muted = true;
			dispatch("muted", true);
			return true;
		}
	}
	function unmute() {
		if (ctx.audioElement) {
			ctx.audioElement.muted = false;
			dispatch("muted", false);
			return true;
		}
	}
	function stop() {
		return sendCommand(EVENT.STOP_REQUESTED);
	}
	function feed(data) {
		dispatch("output", data);
	}
	function dispatchMarker(data) {
		dispatch("marker", {
			...data,
			time: data.time / 1e3
		});
	}
	function renderTextPoster() {
		renderPoster();
		ctx.posterRenderableAfterLoad = false;
	}
	function validateSeekInput(where) {
		if (typeof where === "number") {
			if (Number.isFinite(where)) return;
		} else if (typeof where === "string") {
			if (isRelativeSeek(where) || parseSeekPercentage(where) !== void 0) return;
		} else if (typeof where === "object" && where !== null) {
			if (where.marker === "prev" || where.marker === "next" || Number.isInteger(where.marker) && where.marker >= 0) return;
		}
		throw new Error(`invalid seek target: ${JSON.stringify(where)}`);
	}
	function isRelativeSeek(where) {
		return where === "<<" || where === ">>" || where === "<<<" || where === ">>>";
	}
	function parseSeekPercentage(where) {
		if (!where.endsWith("%")) return;
		const percentage = Number(where.slice(0, -1));
		if (Number.isFinite(percentage)) return percentage;
	}
	function resolveSeek(currentState, where) {
		const currentTime = getCurrentTimeMs();
		const isPlaying = currentState === STATE.READY_PLAYING;
		let target = where;
		if (typeof target === "number") target = target * 1e3;
		else if (typeof target === "string") {
			if (target === "<<") target = currentTime - 5e3;
			else if (target === ">>") target = currentTime + 5e3;
			else if (target === "<<<") target = currentTime - .1 * ctx.duration;
			else if (target === ">>>") target = currentTime + .1 * ctx.duration;
			else if (target[target.length - 1] === "%") target = parseSeekPercentage(target) / 100 * ctx.duration;
		} else if (typeof target === "object") {
			if (target.marker === "prev") {
				target = findMarkerTimeBefore(currentTime) ?? 0;
				if (isPlaying && currentTime - target < 1e3) target = findMarkerTimeBefore(target) ?? 0;
			} else if (target.marker === "next") target = findMarkerTimeAfter(currentTime) ?? ctx.duration;
			else if (typeof target.marker === "number") {
				const marker = ctx.markers[target.marker];
				if (marker === void 0) throw new Error(`invalid marker index: ${target.marker}`);
				target = marker[0];
			}
		}
		const targetTime = Math.min(Math.max(target, 0), ctx.duration);
		return {
			targetTime,
			reachedEnd: targetTime >= ctx.duration,
			noOp: targetTime === ctx.pauseElapsedTime
		};
	}
	function effectiveSize(cols, rows) {
		return {
			cols: optionCols ?? cols,
			rows: optionRows ?? rows
		};
	}
	function resetTerminalFromSnapshot(segment, emitClear = false) {
		if (emitClear) feed("\x1Bc");
		dispatch("reset", {
			size: effectiveSize(segment.snapshot.cols, segment.snapshot.rows),
			init: segment.snapshot.init,
			theme: ctx.recording.theme ?? null
		});
	}
	function syncActiveSegmentToTime(targetTime, clearStartAt = true, inclusive = true) {
		let event = ctx.segment.events[ctx.nextEventIndex];
		let output = [];
		while (event && (inclusive ? event[0] <= targetTime : event[0] < targetTime)) {
			if (event[1] === "o") output.push(event[2]);
			else if (event[1] === "r") {
				if (output.length > 0) {
					feed(output);
					output = [];
				}
				applyRecordingEvent(event);
			}
			ctx.lastEventTime = event[0];
			event = ctx.segment.events[++ctx.nextEventIndex];
		}
		if (output.length > 0) feed(output);
		ctx.pauseElapsedTime = targetTime;
		if (clearStartAt) ctx.effectiveStartAt = null;
		if (ctx.audioElement && ctx.audioSeekable) ctx.audioElement.currentTime = targetTime / 1e3 / speed;
		reportTiming();
	}
	async function positionAt(targetTime, generation, forceReset = false) {
		const targetIndex = findSegmentIndex(ctx.recording, targetTime);
		if (generation !== ctx.positionGeneration) return false;
		if (!forceReset && targetIndex === ctx.segmentIndex && targetTime >= ctx.lastEventTime) {
			syncActiveSegmentToTime(targetTime);
			return true;
		}
		retainSegments([
			targetIndex - 1,
			targetIndex,
			targetIndex + 1
		]);
		const segment = await getRequiredSegment(targetIndex, generation);
		if (generation !== ctx.positionGeneration) return false;
		activateSegment(targetIndex, segment);
		resetTerminalFromSnapshot(segment, true);
		syncActiveSegmentToTime(targetTime);
		return true;
	}
	async function startPlayback(reason) {
		const generation = ctx.positionGeneration;
		if (ctx.segmentIndex === ctx.recording.segments.length - 1 && ctx.segment.events[ctx.nextEventIndex] === void 0) {
			if (!await positionAt(0, generation, true)) return false;
		} else if (ctx.effectiveStartAt !== null) {
			if (!await positionAt(ctx.effectiveStartAt, generation)) return false;
		}
		if (generation !== ctx.positionGeneration) return false;
		prefetchNextSegment();
		preparePlaybackClock();
		if (ctx.audioElement) try {
			await ctx.audioElement.play();
			return sendDriverEvent(EVENT.PLAYBACK_START_CONFIRMED, { reason });
		} catch (error) {
			sendDriverEvent(EVENT.PLAYBACK_START_REJECTED);
			throw error;
		}
		return raiseDriverEvent(EVENT.PLAYBACK_START_CONFIRMED, { reason });
	}
	function performPause(time) {
		if (ctx.audioElement) ctx.audioElement.pause();
		pausePlaybackClock(time);
		dispatch("pause");
		return true;
	}
	async function performSeek(seekOperation, stateBeforeSeek) {
		const resumeAfterSeek = stateBeforeSeek === STATE.READY_PLAYING || stateBeforeSeek === STATE.READY_BUFFERING_TO_RESUME;
		const generation = ++ctx.positionGeneration;
		if (stateBeforeSeek === STATE.READY_PLAYING) pausePlaybackClock();
		ctx.segmentWaiting = false;
		clearWaitingTimeout();
		if (ctx.audioElement) ctx.audioElement.pause();
		if (!await positionAt(seekOperation.targetTime, generation)) return false;
		if (generation !== ctx.positionGeneration) return false;
		if (seekOperation.reachedEnd) {
			dispatch("seeked");
			dispatch("ended");
			return true;
		}
		if (resumeAfterSeek) return await startPlayback(PLAYBACK_START_REASON.SEEK);
		dispatch("seeked");
		return true;
	}
	async function performStep(n = 1) {
		const generation = ++ctx.positionGeneration;
		const target = await findStepTarget(n, generation);
		if (target === void 0 || generation !== ctx.positionGeneration) return;
		clearPoster();
		if (!await positionAt(target.time, generation, n < 0)) return;
		if (ctx.audioElement && ctx.audioSeekable) ctx.audioElement.currentTime = target.time / 1e3 / speed;
		if (target.reachedEnd) {
			state = STATE.READY_ENDED;
			dispatch("ended");
		} else state = STATE.READY_PAUSED;
	}
	async function findStepTarget(n, generation) {
		let remaining = Math.abs(n);
		let segmentIndex = ctx.segmentIndex;
		let eventIndex = n > 0 ? ctx.nextEventIndex : ctx.nextEventIndex - 2;
		let target;
		while (segmentIndex >= 0 && segmentIndex < ctx.recording.segments.length) {
			if (generation !== ctx.positionGeneration) return;
			retainSegments([
				segmentIndex - 1,
				segmentIndex,
				segmentIndex + 1
			]);
			const segment = await getRequiredSegment(segmentIndex, generation);
			if (generation !== ctx.positionGeneration) return;
			if (n > 0) {
				for (let i = Math.max(eventIndex, 0); i < segment.events.length; i++) if (segment.events[i][1] === "o" && --remaining === 0) {
					target = { time: segment.events[i][0] };
					break;
				}
				if (target) break;
				segmentIndex++;
				eventIndex = 0;
			} else {
				for (let i = Math.min(eventIndex, segment.events.length - 1); i >= 0; i--) if (segment.events[i][1] === "o" && --remaining === 0) {
					target = { time: segment.events[i][0] };
					break;
				}
				if (target) break;
				segmentIndex--;
				eventIndex = Number.MAX_SAFE_INTEGER;
			}
		}
		if (target) target.reachedEnd = target.time >= ctx.duration;
		return target;
	}
	function restartWaitingTimeout() {
		clearTimeout(ctx.waitingTimeout);
		ctx.waitingTimeout = setTimeout(() => {
			dispatch("loading");
		}, 1e3);
	}
	function clearWaitingTimeout() {
		clearTimeout(ctx.waitingTimeout);
		ctx.waitingTimeout = null;
	}
	function clearLoadingTimeout() {
		clearTimeout(ctx.loadingTimeout);
		ctx.loadingTimeout = null;
	}
	function cancelPendingTimers() {
		clearLoadingTimeout();
		clearWaitingTimeout();
		cancelScheduledRecordingEvent();
	}
	async function restartLoop() {
		pausePlaybackAt(ctx.duration);
		ctx.playCount++;
		const generation = ++ctx.positionGeneration;
		try {
			const segment = await getRequiredSegment(0, generation, () => {
				enqueueDriverEvent(EVENT.SEGMENT_WAITING, { time: ctx.duration });
			});
			if (generation !== ctx.positionGeneration) return;
			activateSegment(0, segment);
			resetTerminalFromSnapshot(segment, true);
			pausePlaybackAt(0);
			prefetchNextSegment();
			if (ctx.audioElement && ctx.audioSeekable) ctx.audioElement.currentTime = 0;
			if (state === STATE.READY_BUFFERING_TO_RESUME || state === STATE.READY_BUFFERING_WHILE_PAUSED) await sendDriverEvent(EVENT.SEGMENT_READY);
			else confirmPlaybackClockStart();
		} catch {}
	}
	function finishPlayback() {
		pausePlaybackAt(ctx.duration);
		ctx.playCount++;
		if (ctx.audioElement) ctx.audioElement.pause();
		retainSegments([ctx.segmentIndex - 1, ctx.segmentIndex]);
		dispatch("ended");
	}
	function teardown() {
		pausePlaybackAt(getCurrentTimeMs());
		ctx.positionGeneration++;
		ctx.segmentCache.clear();
		cancelPendingTimers();
		return teardownAudio();
	}
	return {
		init,
		stop,
		getDuration,
		getTiming,
		play,
		pause,
		seek,
		step,
		mute,
		unmute
	};
}
function loadRecordingSource(src, options) {
	if (src.format === "segmented") return loadSegmentedRecording(src, options);
	return loadFullRecording(src, options);
}
function findSegmentIndex(recording, time) {
	let low = 0;
	let high = recording.segments.length;
	while (low + 1 < high) {
		const middle = Math.floor((low + high) / 2);
		if (recording.segments[middle].start <= time) low = middle;
		else high = middle;
	}
	return low;
}
async function createAudioElement(src) {
	const audio = new Audio();
	audio.preload = "metadata";
	audio.loop = false;
	audio.crossOrigin = "anonymous";
	let resolve;
	let reject;
	const canPlay = new Promise((resolve_, reject_) => {
		resolve = resolve_;
		reject = reject_;
	});
	function cleanup() {
		audio.removeEventListener("canplay", onCanPlay);
		audio.removeEventListener("error", onError);
		audio.removeEventListener("abort", onAbort);
	}
	function onCanPlay() {
		cleanup();
		resolve();
	}
	function onError() {
		cleanup();
		reject(/* @__PURE__ */ new Error(`failed loading audio from ${src}`));
	}
	function onAbort() {
		cleanup();
		reject(/* @__PURE__ */ new Error(`audio loading aborted for ${src}`));
	}
	audio.addEventListener("canplay", onCanPlay);
	audio.addEventListener("error", onError);
	audio.addEventListener("abort", onAbort);
	audio.src = src;
	audio.load();
	await canPlay;
	return audio;
}
function clock({ hourColor = 3, minuteColor = 4, separatorColor = 9 }, { dispatch }, { cols = 5, rows = 1 }) {
	const middleRow = Math.floor(rows / 2);
	const leftPad = Math.floor(cols / 2) - 2;
	const setupCursor = `\x1b[?25l\x1b[1m\x1b[${middleRow}B`;
	let intervalId;
	const getTimeSequences = () => {
		const d = /* @__PURE__ */ new Date();
		const h = d.getHours();
		const m = d.getMinutes();
		const seqs = [];
		seqs.push("\r");
		for (let i = 0; i < leftPad; i++) seqs.push(" ");
		seqs.push(`\x1b[3${hourColor}m`);
		if (h < 10) seqs.push("0");
		seqs.push(`${h}`);
		seqs.push(`\x1b[3${separatorColor};5m:\x1b[25m`);
		seqs.push(`\x1b[3${minuteColor}m`);
		if (m < 10) seqs.push("0");
		seqs.push(`${m}`);
		return seqs;
	};
	const updateTime = () => {
		getTimeSequences().forEach((seq) => {
			dispatch("output", seq);
		});
		dispatch("timing", getTiming());
	};
	const getTiming = () => {
		const d = /* @__PURE__ */ new Date();
		return createTiming(d.getHours() * 60 + d.getMinutes(), 0);
	};
	return {
		init: () => {
			dispatch("reset", { size: {
				cols,
				rows
			} });
			dispatch("output", setupCursor);
			updateTime();
		},
		play: () => {
			if (intervalId !== void 0) return true;
			dispatch("play");
			dispatch("playing");
			dispatch("output", setupCursor);
			updateTime();
			intervalId = setInterval(updateTime, 1e3);
			return true;
		},
		stop: () => {
			clearInterval(intervalId);
			intervalId = void 0;
		},
		getTiming
	};
}
var Clock = class {
	constructor(onChange) {
		this.onChange = onChange;
		this.timing = createTiming(null, 0);
	}
	getTiming() {
		return createTiming(getTime(this.timing), this.timing.rate);
	}
	setTime(time, rate = this.timing.rate) {
		this.timing = createTiming(time, rate);
		this.onChange(this.timing);
	}
	stop() {
		this.setTime(getTime(this.timing), 0);
	}
};
function random(_src, { dispatch }, { speed }) {
	const base = " ".charCodeAt(0);
	const range = "~".charCodeAt(0) - base;
	const clock = new Clock((timing) => dispatch("timing", timing));
	let timeoutId;
	const schedule = () => {
		const t = Math.pow(5, Math.random() * 4);
		timeoutId = setTimeout(print, t / speed);
	};
	const print = () => {
		schedule();
		dispatch("output", String.fromCharCode(base + Math.floor(Math.random() * range)));
	};
	return {
		play() {
			if (timeoutId !== void 0) return true;
			dispatch("play");
			clock.setTime(0, speed);
			dispatch("playing");
			schedule();
		},
		stop() {
			clearTimeout(timeoutId);
			timeoutId = void 0;
			clock.stop();
		},
		getTiming: () => clock.getTiming()
	};
}
var DEFAULT_COLS = 80;
var DEFAULT_ROWS = 24;
async function parse$2(data) {
	if (data instanceof Response) {
		const text = await data.text();
		const result = parseJsonl(text);
		if (result !== void 0) {
			const { header, events } = result;
			if (header.version === 2) return parseAsciicastV2(header, events);
			else if (header.version === 3) return parseAsciicastV3(header, events);
			else throw new Error(`asciicast v${header.version} format not supported`);
		} else {
			const header = JSON.parse(text);
			if (header.version === 1) return parseAsciicastV1(header);
		}
	} else if (typeof data === "object" && data.version === 1) return parseAsciicastV1(data);
	else if (Array.isArray(data)) {
		const header = data[0];
		if (header.version === 2) return parseAsciicastV2(header, data.slice(1, data.length));
		else if (header.version === 3) return parseAsciicastV3(header, data.slice(1, data.length));
		else throw new Error(`asciicast v${header.version} format not supported`);
	}
	throw new Error("invalid data");
}
function parseJsonl(jsonl) {
	const lines = jsonl.split("\n");
	let header;
	try {
		header = JSON.parse(lines[0]);
	} catch (_error) {
		return;
	}
	const events = new Stream(lines).drop(1).filter((l) => l[0] === "[").map(JSON.parse);
	return {
		header,
		events
	};
}
function parseAsciicastV1(data) {
	let time = 0;
	const events = new Stream(data.stdout).map((e) => {
		time += e[0] * 1e3;
		return [
			time,
			"o",
			e[1]
		];
	});
	return {
		cols: data.width === 0 ? DEFAULT_COLS : data.width,
		rows: data.height === 0 ? DEFAULT_ROWS : data.height,
		events
	};
}
function parseAsciicastV2(header, events) {
	if (!(events instanceof Stream)) events = new Stream(events);
	events = events.map((e) => [
		e[0] * 1e3,
		e[1],
		e[2]
	]);
	return {
		cols: header.width === 0 ? DEFAULT_COLS : header.width,
		rows: header.height === 0 ? DEFAULT_ROWS : header.height,
		theme: parseTheme$1(header.theme),
		events,
		idleTimeLimit: header.idle_time_limit
	};
}
function parseAsciicastV3(header, events) {
	if (!(events instanceof Stream)) events = new Stream(events);
	let time = 0;
	events = events.map((e) => {
		time += e[0] * 1e3;
		return [
			time,
			e[1],
			e[2]
		];
	});
	return {
		cols: header.term.cols === 0 ? DEFAULT_COLS : header.term.cols,
		rows: header.term.rows === 0 ? DEFAULT_ROWS : header.term.rows,
		theme: parseTheme$1(header.term?.theme),
		events,
		idleTimeLimit: header.idle_time_limit
	};
}
function parseTheme$1(theme) {
	const palette = typeof theme?.palette === "string" ? theme.palette.split(":") : void 0;
	return normalizeTheme({
		foreground: theme?.fg,
		background: theme?.bg,
		palette
	});
}
function benchmark({ url, iterations = 10 }, { dispatch }) {
	const clock = new Clock((timing) => dispatch("timing", timing));
	let data;
	let byteCount = 0;
	let endTimeoutId;
	return {
		async init() {
			const { cols, rows, events } = await parse$2(await fetch(url));
			data = Array.from(events).filter(([_time, type, _text]) => type === "o").map(([time, _type, text]) => [time, text]);
			for (const [_, text] of data) byteCount += new Blob([text]).size;
			dispatch("reset", { size: {
				cols,
				rows
			} });
		},
		play() {
			clearTimeout(endTimeoutId);
			clock.setTime(0, 1);
			const startTime = performance.now();
			for (let i = 0; i < iterations; i++) {
				for (const [_, text] of data) dispatch("output", text);
				dispatch("output", "\x1Bc");
			}
			const endTime = performance.now();
			clock.stop();
			const duration = (endTime - startTime) / 1e3;
			const throughput = byteCount * iterations / duration;
			const throughputMbs = byteCount / 1048576 * iterations / duration;
			console.info("benchmark: result", {
				byteCount,
				iterations,
				duration,
				throughput,
				throughputMbs
			});
			endTimeoutId = setTimeout(() => {
				dispatch("ended");
			}, 0);
			return true;
		},
		stop() {
			clearTimeout(endTimeoutId);
			clock.stop();
		},
		getTiming: () => clock.getTiming()
	};
}
function getBuffer(bufferTime, dispatch, setTime, baseStreamTime, minFrameTime, logger) {
	const execute = executeEvent(dispatch);
	if (bufferTime === 0) {
		logger.debug("using no buffer");
		return nullBuffer(execute);
	} else {
		bufferTime = bufferTime ?? {};
		let getBufferTime;
		if (typeof bufferTime === "number") {
			logger.debug(`using fixed time buffer (${bufferTime} ms)`);
			getBufferTime = (_latency) => bufferTime;
		} else if (typeof bufferTime === "function") {
			logger.debug("using custom dynamic buffer");
			getBufferTime = bufferTime({ logger });
		} else {
			logger.debug("using adaptive buffer", bufferTime);
			getBufferTime = adaptiveBufferTimeProvider({ logger }, bufferTime);
		}
		return buffer(getBufferTime, execute, setTime, logger, baseStreamTime ?? 0, minFrameTime);
	}
}
function nullBuffer(execute) {
	return {
		pushEvent(event) {
			execute(event[1], event[2]);
		},
		pushText(text) {
			execute("o", text);
		},
		stop() {}
	};
}
function executeEvent(dispatch) {
	return function(code, data) {
		if (code === "o") dispatch("output", data);
		else if (code === "i") dispatch("input", { data });
		else if (code === "r") dispatch("resize", data);
		else if (code === "m") dispatch("marker", data);
	};
}
function buffer(getBufferTime, execute, setTime, logger, baseStreamTime, minFrameTime = 1 / 60) {
	const outputBatchWindow = minFrameTime * 1e3;
	let epoch = performance.now() - baseStreamTime;
	let bufferTime = getBufferTime(0);
	let queue = [];
	let onPush;
	let prevElapsedStreamTime = -outputBatchWindow;
	let stop = false;
	function elapsedWallTime() {
		return performance.now() - epoch;
	}
	function push(item) {
		queue.push(item);
		if (onPush !== void 0) {
			onPush(popAll());
			onPush = void 0;
		}
	}
	function popAll() {
		if (queue.length > 0) {
			const items = queue;
			queue = [];
			return items;
		} else return new Promise((resolve) => {
			onPush = resolve;
		});
	}
	async function run() {
		while (!stop) {
			const events = await popAll();
			if (stop) return;
			let nextEventIndex = 0;
			while (nextEventIndex < events.length) nextEventIndex = await executeNextEventChunk(events, nextEventIndex);
		}
	}
	queueMicrotask(run);
	async function executeNextEventChunk(events, nextEventIndex) {
		const event = events[nextEventIndex];
		const elapsedStreamTime = event[3];
		if (elapsedStreamTime - prevElapsedStreamTime >= outputBatchWindow) {
			const delay = elapsedStreamTime - elapsedWallTime();
			if (delay > 0) {
				await sleep(delay);
				if (stop) return events.length;
			}
			setTime(event[0]);
			prevElapsedStreamTime = elapsedStreamTime;
		}
		if (event[1] === "o") return executeOutputGroup(events, nextEventIndex);
		execute(event[1], event[2]);
		return nextEventIndex + 1;
	}
	function executeOutputGroup(events, nextEventIndex) {
		const firstEvent = events[nextEventIndex];
		const batchDeadline = firstEvent[0] + outputBatchWindow;
		const output = [];
		let event = firstEvent;
		while (event !== void 0 && event[1] === "o" && event[0] < batchDeadline) {
			output.push(event[2]);
			event = events[++nextEventIndex];
		}
		execute("o", output);
		return nextEventIndex;
	}
	return {
		pushEvent(event) {
			let latency = elapsedWallTime() - event[0];
			if (latency < 0) {
				logger.debug(`correcting epoch by ${latency} ms`);
				epoch += latency;
				latency = 0;
			}
			bufferTime = getBufferTime(latency);
			push([
				event[0],
				event[1],
				event[2],
				event[0] + bufferTime
			]);
		},
		pushText(text) {
			const time = elapsedWallTime();
			push([
				time,
				"o",
				text,
				time + bufferTime
			]);
		},
		stop() {
			stop = true;
			if (onPush !== void 0) {
				onPush([]);
				onPush = void 0;
			}
		}
	};
}
function sleep(t) {
	return new Promise((resolve) => {
		setTimeout(resolve, t);
	});
}
function adaptiveBufferTimeProvider({ logger } = {}, { minBufferTime = 50, bufferLevelStep = 100, maxBufferLevel = 50, transitionDuration = 500, peakHalfLifeUp = 100, peakHalfLifeDown = 1e4, floorHalfLifeUp = 5e3, floorHalfLifeDown = 100, idealHalfLifeUp = 1e3, idealHalfLifeDown = 5e3, safetyMultiplier = 1.2, minImprovementDuration = 3e3 } = {}) {
	function levelToMs(level) {
		return level === 0 ? minBufferTime : bufferLevelStep * level;
	}
	let bufferLevel = 1;
	let bufferTime = levelToMs(bufferLevel);
	let lastUpdateTime = performance.now();
	let smoothedPeakLatency = null;
	let smoothedFloorLatency = null;
	let smoothedIdealBufferTime = null;
	let stableSince = null;
	let targetBufferTime = null;
	let transitionRate = null;
	return function(latency) {
		const now = performance.now();
		const dt = Math.max(0, now - lastUpdateTime);
		lastUpdateTime = now;
		if (smoothedPeakLatency === null) smoothedPeakLatency = latency;
		else if (latency > smoothedPeakLatency) {
			const alphaUp = 1 - Math.pow(2, -dt / peakHalfLifeUp);
			smoothedPeakLatency += alphaUp * (latency - smoothedPeakLatency);
		} else {
			const alphaDown = 1 - Math.pow(2, -dt / peakHalfLifeDown);
			smoothedPeakLatency += alphaDown * (latency - smoothedPeakLatency);
		}
		smoothedPeakLatency = Math.max(smoothedPeakLatency, 0);
		if (smoothedFloorLatency === null) smoothedFloorLatency = latency;
		else if (latency > smoothedFloorLatency) {
			const alphaUp = 1 - Math.pow(2, -dt / floorHalfLifeUp);
			smoothedFloorLatency += alphaUp * (latency - smoothedFloorLatency);
		} else {
			const alphaDown = 1 - Math.pow(2, -dt / floorHalfLifeDown);
			smoothedFloorLatency += alphaDown * (latency - smoothedFloorLatency);
		}
		smoothedFloorLatency = Math.max(smoothedFloorLatency, 0);
		const jitter = smoothedPeakLatency - smoothedFloorLatency;
		const idealBufferTime = safetyMultiplier * (smoothedPeakLatency + jitter);
		if (smoothedIdealBufferTime === null) smoothedIdealBufferTime = idealBufferTime;
		else if (idealBufferTime > smoothedIdealBufferTime) {
			const alphaUp = 1 - Math.pow(2, -dt / idealHalfLifeUp);
			smoothedIdealBufferTime += +alphaUp * (idealBufferTime - smoothedIdealBufferTime);
		} else {
			const alphaDown = 1 - Math.pow(2, -dt / idealHalfLifeDown);
			smoothedIdealBufferTime += +alphaDown * (idealBufferTime - smoothedIdealBufferTime);
		}
		let newBufferLevel;
		if (smoothedIdealBufferTime <= minBufferTime) newBufferLevel = 0;
		else newBufferLevel = clamp(Math.ceil(smoothedIdealBufferTime / bufferLevelStep), 1, maxBufferLevel);
		if (latency > bufferTime) logger.debug("buffer underrun", {
			latency,
			bufferTime
		});
		if (newBufferLevel > bufferLevel) {
			if (latency > bufferTime) bufferLevel = Math.min(newBufferLevel, bufferLevel + 3);
			else bufferLevel += 1;
			targetBufferTime = levelToMs(bufferLevel);
			transitionRate = (targetBufferTime - bufferTime) / transitionDuration;
			stableSince = null;
			logger.debug("raising buffer", {
				latency,
				bufferTime,
				targetBufferTime
			});
		} else if (newBufferLevel < bufferLevel) {
			if (stableSince == null) stableSince = now;
			if (now - stableSince >= minImprovementDuration) {
				bufferLevel -= 1;
				targetBufferTime = levelToMs(bufferLevel);
				transitionRate = (targetBufferTime - bufferTime) / transitionDuration;
				stableSince = now;
				logger.debug("lowering buffer", {
					latency,
					bufferTime,
					targetBufferTime
				});
			}
		} else stableSince = null;
		if (targetBufferTime !== null) {
			bufferTime += transitionRate * dt;
			if (transitionRate >= 0 && bufferTime > targetBufferTime || transitionRate < 0 && bufferTime < targetBufferTime) {
				bufferTime = targetBufferTime;
				targetBufferTime = null;
			}
		}
		return bufferTime;
	};
}
function clamp(x, lo, hi) {
	return Math.min(hi, Math.max(lo, x));
}
var ONE_MS_IN_USEC = 1e3;
var ONE_SEC_IN_USEC = 1e6;
function alisHandler(logger) {
	const outputDecoder = new TextDecoder();
	const inputDecoder = new TextDecoder();
	let handler = parseMagicString;
	let lastEventTime;
	let markerIndex = 0;
	function parseMagicString(buffer) {
		if (new TextDecoder().decode(buffer) === "ALiS") handler = parseFirstFrame;
		else throw new Error("not an ALiS v1 live stream");
	}
	function parseFirstFrame(buffer) {
		const view = new BinaryReader(new DataView(buffer));
		const type = view.getUint8();
		if (type !== 1) throw new Error(`expected reset (0x01) frame, got ${type}`);
		return parseResetFrame(view, buffer);
	}
	function parseResetFrame(view, buffer) {
		view.decodeVarUint();
		let time = view.decodeVarUint();
		lastEventTime = time;
		time = time / ONE_MS_IN_USEC;
		markerIndex = 0;
		const cols = view.decodeVarUint();
		const rows = view.decodeVarUint();
		const themeFormat = view.getUint8();
		let theme;
		if (themeFormat === 8) {
			const len = 30;
			theme = parseTheme(new Uint8Array(buffer, view.offset, len));
			view.forward(len);
		} else if (themeFormat === 16) {
			const len = 54;
			theme = parseTheme(new Uint8Array(buffer, view.offset, len));
			view.forward(len);
		} else if (themeFormat !== 0) throw new Error(`alis: invalid theme format (${themeFormat})`);
		const initLen = view.decodeVarUint();
		let init;
		if (initLen > 0) init = outputDecoder.decode(new Uint8Array(buffer, view.offset, initLen));
		handler = parseFrame;
		return {
			time,
			term: {
				size: {
					cols,
					rows
				},
				theme,
				init
			}
		};
	}
	function parseFrame(buffer) {
		const view = new BinaryReader(new DataView(buffer));
		const type = view.getUint8();
		if (type === 1) return parseResetFrame(view, buffer);
		else if (type === 111) return parseOutputFrame(view, buffer);
		else if (type === 105) return parseInputFrame(view, buffer);
		else if (type === 114) return parseResizeFrame(view);
		else if (type === 109) return parseMarkerFrame(view, buffer);
		else if (type === 120) return parseExitFrame(view);
		else if (type === 4) {
			handler = parseFirstFrame;
			return false;
		} else logger.debug(`alis: unknown frame type: ${type}`);
	}
	function parseOutputFrame(view, buffer) {
		view.decodeVarUint();
		const relTime = view.decodeVarUint();
		lastEventTime += relTime;
		const len = view.decodeVarUint();
		const text = outputDecoder.decode(new Uint8Array(buffer, view.offset, len));
		return [
			lastEventTime / ONE_MS_IN_USEC,
			"o",
			text
		];
	}
	function parseInputFrame(view, buffer) {
		view.decodeVarUint();
		const relTime = view.decodeVarUint();
		lastEventTime += relTime;
		const len = view.decodeVarUint();
		const text = inputDecoder.decode(new Uint8Array(buffer, view.offset, len));
		return [
			lastEventTime / ONE_MS_IN_USEC,
			"i",
			text
		];
	}
	function parseResizeFrame(view) {
		view.decodeVarUint();
		const relTime = view.decodeVarUint();
		lastEventTime += relTime;
		const cols = view.decodeVarUint();
		const rows = view.decodeVarUint();
		return [
			lastEventTime / ONE_MS_IN_USEC,
			"r",
			{
				cols,
				rows
			}
		];
	}
	function parseMarkerFrame(view, buffer) {
		view.decodeVarUint();
		const relTime = view.decodeVarUint();
		lastEventTime += relTime;
		const len = view.decodeVarUint();
		const decoder = new TextDecoder();
		const index = markerIndex++;
		return [
			lastEventTime / ONE_MS_IN_USEC,
			"m",
			{
				index,
				time: lastEventTime / ONE_SEC_IN_USEC,
				label: decoder.decode(new Uint8Array(buffer, view.offset, len))
			}
		];
	}
	function parseExitFrame(view) {
		view.decodeVarUint();
		const relTime = view.decodeVarUint();
		lastEventTime += relTime;
		const status = view.decodeVarUint();
		return [
			lastEventTime / ONE_MS_IN_USEC,
			"x",
			{ status }
		];
	}
	return function(buffer) {
		return handler(buffer);
	};
}
function parseTheme(arr) {
	const colorCount = arr.length / 3;
	const foreground = hexColor(arr[0], arr[1], arr[2]);
	const background = hexColor(arr[3], arr[4], arr[5]);
	const palette = [];
	for (let i = 2; i < colorCount; i++) palette.push(hexColor(arr[i * 3], arr[i * 3 + 1], arr[i * 3 + 2]));
	return normalizeTheme({
		foreground,
		background,
		palette
	});
}
function hexColor(r, g, b) {
	return `#${byteToHex(r)}${byteToHex(g)}${byteToHex(b)}`;
}
function byteToHex(value) {
	return value.toString(16).padStart(2, "0");
}
var BinaryReader = class {
	constructor(inner, offset = 0) {
		this.inner = inner;
		this.offset = offset;
	}
	forward(delta) {
		this.offset += delta;
	}
	getUint8() {
		const value = this.inner.getUint8(this.offset);
		this.offset += 1;
		return value;
	}
	decodeVarUint() {
		let number = BigInt(0);
		let shift = BigInt(0);
		let byte = this.getUint8();
		while (byte > 127) {
			byte &= 127;
			number += BigInt(byte) << shift;
			shift += BigInt(7);
			byte = this.getUint8();
		}
		number = number + (BigInt(byte) << shift);
		return Number(number);
	}
};
function ascicastV2Handler() {
	let parse = parseHeader;
	function parseHeader(buffer) {
		const header = JSON.parse(buffer);
		if (header.version !== 2) throw new Error("not an asciicast v2 stream");
		parse = parseEvent;
		return {
			time: 0,
			term: { size: {
				cols: header.width,
				rows: header.height
			} }
		};
	}
	function parseEvent(buffer) {
		const event = JSON.parse(buffer);
		const time = event[0] * 1e3;
		if (event[1] === "r") {
			const [cols, rows] = event[2].split("x");
			return [
				time,
				"r",
				{
					cols: parseInt(cols, 10),
					rows: parseInt(rows, 10)
				}
			];
		} else return [
			time,
			event[1],
			event[2]
		];
	}
	return function(buffer) {
		return parse(buffer);
	};
}
function ascicastV3Handler() {
	let parse = parseHeader;
	let currentTime = 0;
	function parseHeader(buffer) {
		const header = JSON.parse(buffer);
		if (header.version !== 3) throw new Error("not an asciicast v3 stream");
		parse = parseEvent;
		const term = { size: {
			cols: header.term.cols,
			rows: header.term.rows
		} };
		if (header.term.theme) {
			const palette = typeof header.term.theme.palette === "string" ? header.term.theme.palette.split(":") : void 0;
			const theme = normalizeTheme({
				foreground: header.term.theme.fg,
				background: header.term.theme.bg,
				palette
			});
			if (theme) term.theme = theme;
		}
		return {
			time: 0,
			term
		};
	}
	function parseEvent(buffer) {
		const [interval, eventType, data] = JSON.parse(buffer);
		currentTime += interval * 1e3;
		if (eventType === "r") {
			const [cols, rows] = data.split("x");
			return [
				currentTime,
				"r",
				{
					cols: parseInt(cols, 10),
					rows: parseInt(rows, 10)
				}
			];
		} else return [
			currentTime,
			eventType,
			data
		];
	}
	return function(buffer) {
		return parse(buffer);
	};
}
function rawHandler() {
	const outputDecoder = new TextDecoder();
	let parse = parseSize;
	function parseSize(buffer) {
		const text = outputDecoder.decode(buffer, { stream: true });
		const [cols, rows] = sizeFromResizeSeq(text) ?? sizeFromScriptStartMessage(text) ?? [80, 24];
		parse = parseOutput;
		return {
			time: 0,
			term: {
				size: {
					cols,
					rows
				},
				init: text
			}
		};
	}
	function parseOutput(buffer) {
		return outputDecoder.decode(buffer, { stream: true });
	}
	return function(buffer) {
		return parse(buffer);
	};
}
function sizeFromResizeSeq(text) {
	const match = text.match(/\x1b\[8;(\d+);(\d+)t/);
	if (match !== null) return [parseInt(match[2], 10), parseInt(match[1], 10)];
}
function sizeFromScriptStartMessage(text) {
	const match = text.match(/\[.*COLUMNS="(\d{1,3})" LINES="(\d{1,3})".*\]/);
	if (match !== null) return [parseInt(match[1], 10), parseInt(match[2], 10)];
}
var RECONNECT_DELAY_BASE = 500;
var RECONNECT_DELAY_CAP = 1e4;
function exponentialDelay(attempt) {
	const base = Math.min(RECONNECT_DELAY_BASE * Math.pow(2, attempt), RECONNECT_DELAY_CAP);
	return Math.random() * base;
}
function websocket({ url, bufferTime, reconnectDelay = exponentialDelay, minFrameTime }, { dispatch, logger }, { audioUrl }) {
	logger = new PrefixedLogger(logger, "websocket: ");
	const clock = new Clock((timing) => dispatch("timing", timing));
	let socket;
	let buf;
	let reconnectAttempt = 0;
	let successfulConnectionTimeout;
	let reconnectTimeout;
	let stop = false;
	let wasOnline = false;
	let gotExitEvent = false;
	let gotEotEvent = false;
	let initTimeout;
	let audioElement;
	function connect() {
		if (stop) return;
		socket = new WebSocket(url, [
			"v1.alis",
			"v2.asciicast",
			"v3.asciicast",
			"raw"
		]);
		socket.binaryType = "arraybuffer";
		let proto;
		socket.onopen = () => {
			proto = socket.protocol || "raw";
			logger.info("opened");
			logger.info(`activating ${proto} protocol handler`);
			if (proto === "v1.alis") socket.onmessage = onMessage(alisHandler(logger));
			else if (proto === "v2.asciicast") socket.onmessage = onMessage(ascicastV2Handler());
			else if (proto === "v3.asciicast") socket.onmessage = onMessage(ascicastV3Handler());
			else if (proto === "raw") socket.onmessage = onMessage(rawHandler());
			successfulConnectionTimeout = setTimeout(() => {
				reconnectAttempt = 0;
			}, 1e3);
		};
		socket.onclose = (event) => {
			clearTimeout(initTimeout);
			clearTimeout(successfulConnectionTimeout);
			if (stop) return;
			stopBuffer();
			let ended = false;
			let endedMessage = "Stream ended";
			if (proto === "v1.alis") {
				if (gotEotEvent || event.code >= 4e3 && event.code <= 4100) {
					ended = true;
					endedMessage = event.reason || endedMessage;
				}
			} else if (gotExitEvent || event.code === 1e3 || event.code === 1005) ended = true;
			if (ended) {
				logger.info("closed");
				dispatch("ended", { message: endedMessage });
			} else if (event.code === 1002) {
				logger.debug(`close reason: ${event.reason}`);
				dispatch("ended", { message: "Err: Player not compatible with the server" });
			} else {
				const delay = reconnectDelay(reconnectAttempt++);
				logger.info(`unexpected close, reconnecting in ${delay}...`);
				dispatch("loading");
				reconnectTimeout = setTimeout(connect, delay);
			}
		};
		wasOnline = false;
	}
	function onMessage(handler) {
		initTimeout = setTimeout(onStreamEnd, 5e3);
		return function(event) {
			try {
				const result = handler(event.data);
				if (buf) {
					if (Array.isArray(result)) {
						buf.pushEvent(result);
						if (result[1] === "x") gotExitEvent = true;
					} else if (typeof result === "string") buf.pushText(result);
					else if (typeof result === "object" && !Array.isArray(result)) onStreamReset(result);
					else if (result === false) {
						onStreamEnd();
						gotEotEvent = true;
					} else if (result !== void 0) throw new Error(`unexpected value from protocol handler: ${result}`);
				} else if (typeof result === "object" && !Array.isArray(result)) {
					onStreamReset(result);
					clearTimeout(initTimeout);
				} else if (result === void 0) {
					clearTimeout(initTimeout);
					initTimeout = setTimeout(onStreamEnd, 1e3);
				} else {
					clearTimeout(initTimeout);
					throw new Error(`unexpected value from protocol handler: ${result}`);
				}
			} catch (e) {
				socket.close();
				throw e;
			}
		};
	}
	function onStreamReset({ time, term }) {
		const { size, init, theme } = term;
		const { cols, rows } = size;
		logger.info(`stream reset (${cols}x${rows} @${time})`);
		stopBuffer();
		buf = getBuffer(bufferTime, dispatch, (t) => clock.setTime(t / 1e3, 1), time, minFrameTime, logger);
		dispatch("reset", {
			size: {
				cols,
				rows
			},
			init,
			theme: theme ?? null
		});
		wasOnline = true;
		gotExitEvent = false;
		gotEotEvent = false;
		clock.setTime((time ?? 0) / 1e3, 1);
		dispatch("playing");
	}
	function onStreamEnd() {
		stopBuffer();
		if (wasOnline) {
			logger.info("stream ended");
			dispatch("offline", { message: "Stream ended" });
		} else {
			logger.info("stream offline");
			dispatch("offline", { message: "Stream offline" });
		}
	}
	function stopBuffer() {
		if (buf) buf.stop();
		buf = null;
		clock.stop();
	}
	function startAudio() {
		if (!audioUrl) return;
		audioElement = new Audio();
		audioElement.preload = "auto";
		audioElement.crossOrigin = "anonymous";
		audioElement.src = audioUrl;
		audioElement.play();
	}
	function stopAudio() {
		if (!audioElement) return;
		audioElement.pause();
	}
	function mute() {
		if (audioElement) {
			audioElement.muted = true;
			return true;
		}
	}
	function unmute() {
		if (audioElement) {
			audioElement.muted = false;
			return true;
		}
	}
	return {
		init: () => {
			dispatch("metadata", { hasAudio: !!audioUrl });
		},
		play: () => {
			if (socket) return true;
			dispatch("play");
			connect();
			startAudio();
			return true;
		},
		stop: () => {
			stop = true;
			clearTimeout(initTimeout);
			clearTimeout(successfulConnectionTimeout);
			clearTimeout(reconnectTimeout);
			stopBuffer();
			if (socket !== void 0) socket.close();
			stopAudio();
		},
		mute,
		unmute,
		getTiming: () => clock.getTiming()
	};
}
function eventsource({ url, bufferTime, minFrameTime }, { dispatch, logger }) {
	logger = new PrefixedLogger(logger, "eventsource: ");
	const clock = new Clock((timing) => dispatch("timing", timing));
	let es;
	let buf;
	function initBuffer(baseStreamTime) {
		stopBuffer();
		clock.stop();
		buf = getBuffer(bufferTime, dispatch, (t) => clock.setTime(t / 1e3), baseStreamTime, minFrameTime, logger);
	}
	function stopBuffer() {
		if (buf !== void 0) buf.stop();
		buf = void 0;
	}
	return {
		play: () => {
			if (es) return true;
			dispatch("play");
			es = new EventSource(url);
			es.addEventListener("open", () => {
				logger.info("opened");
				initBuffer();
			});
			es.addEventListener("error", (e) => {
				logger.info("errored");
				logger.debug({ e });
				clock.stop();
				dispatch("loading");
			});
			es.addEventListener("message", (event) => {
				const e = JSON.parse(event.data);
				if (Array.isArray(e)) buf.pushEvent([
					e[0] * 1e3,
					e[1],
					e[2]
				]);
				else if (e.cols !== void 0 || e.width !== void 0) {
					const cols = e.cols ?? e.width;
					const rows = e.rows ?? e.height;
					const time = typeof e.time === "number" ? e.time * 1e3 : void 0;
					logger.debug(`vt reset (${cols}x${rows})`);
					initBuffer(time);
					dispatch("reset", {
						size: {
							cols,
							rows
						},
						init: e.init ?? void 0
					});
					clock.setTime((time ?? 0) / 1e3, 1);
					dispatch("playing");
				} else if (e.state === "offline") {
					logger.info("stream offline");
					clock.stop();
					dispatch("offline", { message: "Stream offline" });
				}
			});
			es.addEventListener("done", () => {
				logger.info("closed");
				es.close();
				clock.stop();
				dispatch("ended", { message: "Stream ended" });
			});
			return true;
		},
		stop: () => {
			stopBuffer();
			clock.stop();
			if (es !== void 0) es.close();
		},
		getTiming: () => clock.getTiming()
	};
}
async function parse$1(responses, { encoding }) {
	const textDecoder = new TextDecoder(encoding);
	let cols;
	let rows;
	let timing = (await responses[0].text()).split("\n").filter((line) => line.length > 0).map((line) => line.split(" "));
	if (timing[0].length < 3) timing = timing.map((entry) => [
		"O",
		entry[0],
		entry[1]
	]);
	const buffer = await responses[1].arrayBuffer();
	const array = new Uint8Array(buffer);
	const dataOffset = array.findIndex((byte) => byte == 10) + 1;
	const sizeMatch = textDecoder.decode(array.subarray(0, dataOffset)).match(/COLUMNS="(\d+)" LINES="(\d+)"/);
	if (sizeMatch !== null) {
		cols = parseInt(sizeMatch[1], 10);
		rows = parseInt(sizeMatch[2], 10);
	}
	const stdout = {
		array,
		cursor: dataOffset
	};
	let stdin = stdout;
	if (responses[2] !== void 0) {
		const buffer = await responses[2].arrayBuffer();
		stdin = {
			array: new Uint8Array(buffer),
			cursor: dataOffset
		};
	}
	const events = [];
	let time = 0;
	for (const entry of timing) {
		time += parseFloat(entry[1]) * 1e3;
		if (entry[0] === "O") {
			const count = parseInt(entry[2], 10);
			const bytes = stdout.array.subarray(stdout.cursor, stdout.cursor + count);
			const text = textDecoder.decode(bytes);
			events.push([
				time,
				"o",
				text
			]);
			stdout.cursor += count;
		} else if (entry[0] === "I") {
			const count = parseInt(entry[2], 10);
			const bytes = stdin.array.subarray(stdin.cursor, stdin.cursor + count);
			const text = textDecoder.decode(bytes);
			events.push([
				time,
				"i",
				text
			]);
			stdin.cursor += count;
		} else if (entry[0] === "S" && entry[2] === "SIGWINCH") {
			const cols = parseInt(entry[4].slice(5), 10);
			const rows = parseInt(entry[3].slice(5), 10);
			events.push([
				time,
				"r",
				`${cols}x${rows}`
			]);
		} else if (entry[0] === "H" && entry[2] === "COLUMNS") cols = parseInt(entry[3], 10);
		else if (entry[0] === "H" && entry[2] === "LINES") rows = parseInt(entry[3], 10);
	}
	cols = cols ?? 80;
	rows = rows ?? 24;
	return {
		cols,
		rows,
		events
	};
}
async function parse(response, { encoding }) {
	const textDecoder = new TextDecoder(encoding);
	const buffer = await response.arrayBuffer();
	const array = new Uint8Array(buffer);
	const firstFrame = parseFrame(array);
	const baseTime = firstFrame.time;
	const sizeMatch = textDecoder.decode(firstFrame.data).match(/\x1b\[8;(\d+);(\d+)t/);
	const events = [];
	let cols = 80;
	let rows = 24;
	if (sizeMatch !== null) {
		cols = parseInt(sizeMatch[2], 10);
		rows = parseInt(sizeMatch[1], 10);
	}
	let cursor = 0;
	let frame = parseFrame(array);
	while (frame !== void 0) {
		const time = (frame.time - baseTime) * 1e3;
		const text = textDecoder.decode(frame.data);
		events.push([
			time,
			"o",
			text
		]);
		cursor += frame.len;
		frame = parseFrame(array.subarray(cursor));
	}
	return {
		cols,
		rows,
		events
	};
}
function parseFrame(array) {
	if (array.length < 13) return;
	const time = parseTimestamp(array.subarray(0, 8));
	const len = parseNumber(array.subarray(8, 12));
	return {
		time,
		data: array.subarray(12, 12 + len),
		len: len + 12
	};
}
function parseNumber(array) {
	return array[0] + array[1] * 256 + array[2] * 256 * 256 + array[3] * 256 * 256 * 256;
}
function parseTimestamp(array) {
	return parseNumber(array.subarray(0, 4)) + parseNumber(array.subarray(4, 8)) / 1e6;
}
var Core = class {
	constructor(src, opts) {
		this.logger = opts.logger;
		this.driverFactory = getDriver(src);
		this.driver = null;
		this.cols = opts.cols;
		this.rows = opts.rows;
		this.speed = opts.speed;
		this.loop = opts.loop;
		this.autoPlay = opts.autoPlay;
		this.idleTimeLimit = opts.idleTimeLimit;
		this.preload = opts.preload;
		this.startAt = parseNpt(opts.startAt);
		this.poster = this._parsePoster(opts.poster);
		this.markers = opts.markers;
		this.pauseOnMarkers = opts.pauseOnMarkers;
		this.audioUrl = opts.audioUrl;
		this.initPromise = null;
		this.commandQueue = Promise.resolve();
		this.startupPromise = new Promise((resolve) => {
			this.resolveStartup = resolve;
		});
		this.eventHandlers = /* @__PURE__ */ new Map([
			["ended", []],
			["error", []],
			["input", []],
			["loading", []],
			["marker", []],
			["metadata", []],
			["muted", []],
			["offline", []],
			["output", []],
			["pause", []],
			["play", []],
			["playing", []],
			["reset", []],
			["resize", []],
			["ready", []],
			["seeked", []],
			["timing", []]
		]);
	}
	init() {
		if (this.initPromise === null) this.initPromise = this._init();
		return this.initPromise;
	}
	terminalReady() {
		this.resolveStartup();
	}
	async _init() {
		await this.startupPromise;
		this.driver = this.driverFactory({
			dispatch: this._dispatchEvent.bind(this),
			logger: this.logger
		}, {
			cols: this.cols,
			rows: this.rows,
			speed: this.speed,
			idleTimeLimit: this.idleTimeLimit,
			startAt: this.startAt,
			preload: this.preload,
			loop: this.loop,
			poster: this.autoPlay ? void 0 : this.poster,
			markers: this.markers,
			pauseOnMarkers: this.pauseOnMarkers,
			audioUrl: this.audioUrl
		});
		const config = {
			isPausable: !!this.driver.pause,
			isSeekable: !!this.driver.seek
		};
		this._installDriverDefaults();
		if (this.driver.init) await this.driver.init();
		if (this.autoPlay) await this.driver.play();
		this._dispatchEvent("ready", config);
	}
	_installDriverDefaults() {
		if (this.driver.stop === void 0) this.driver.stop = () => {};
		if (this.driver.pause === void 0) this.driver.pause = () => {};
		if (this.driver.seek === void 0) this.driver.seek = (_where) => false;
		if (this.driver.step === void 0) this.driver.step = (_n) => {};
		if (this.driver.mute === void 0) this.driver.mute = () => {};
		if (this.driver.unmute === void 0) this.driver.unmute = () => {};
		if (this.driver.getDuration === void 0) this.driver.getDuration = () => {};
	}
	_enqueue(command) {
		const run = async () => {
			await this.init();
			return command.call(this);
		};
		const result = this.commandQueue.then(run, run);
		this.commandQueue = result.catch(() => {});
		return result;
	}
	play() {
		return this._enqueue(function() {
			return this.driver.play();
		});
	}
	pause() {
		return this._enqueue(function() {
			return this.driver.pause();
		});
	}
	seek(where) {
		return this._enqueue(function() {
			return this.driver.seek(where);
		});
	}
	step(n) {
		return this._enqueue(function() {
			return this.driver.step(n);
		});
	}
	stop() {
		return this._enqueue(function() {
			return this.driver.stop();
		});
	}
	mute() {
		return this._enqueue(function() {
			return this.driver.mute();
		});
	}
	unmute() {
		return this._enqueue(function() {
			return this.driver.unmute();
		});
	}
	getCurrentTime() {
		if (!this.driver) return 0;
		return this.driver.getTiming().time ?? void 0;
	}
	requestTiming() {
		if (this.driver) this._dispatchEvent("timing", this.driver.getTiming());
	}
	getDuration() {
		if (!this.driver) return;
		return this.driver.getDuration();
	}
	addEventListener(eventName, handler) {
		this.eventHandlers.get(eventName).push(handler);
	}
	removeEventListener(eventName, handler) {
		const handlers = this.eventHandlers.get(eventName);
		if (!handlers) return;
		const idx = handlers.indexOf(handler);
		if (idx !== -1) handlers.splice(idx, 1);
	}
	_dispatchEvent(eventName, data = {}) {
		for (const handler of [...this.eventHandlers.get(eventName)]) try {
			handler(data);
		} catch (error) {
			this.logger.error(`event handler for "${eventName}" failed`, error);
			if (typeof globalThis.reportError === "function") globalThis.reportError(error);
			else setTimeout(() => {
				throw error;
			}, 0);
		}
	}
	_parsePoster(poster) {
		if (typeof poster !== "string") return;
		if (poster.substring(0, 16) == "data:text/plain,") return {
			type: "text",
			value: poster.substring(16)
		};
		else if (poster.substring(0, 4) == "npt:") return {
			type: "npt",
			value: parseNpt(poster.substring(4))
		};
	}
};
var DRIVERS = /* @__PURE__ */ new Map([
	["benchmark", benchmark],
	["clock", clock],
	["eventsource", eventsource],
	["random", random],
	["recording", recording],
	["websocket", websocket]
]);
var PARSERS = /* @__PURE__ */ new Map([
	["asciicast", parse$2],
	["typescript", parse$1],
	["ttyrec", parse]
]);
function getDriver(src) {
	if (typeof src === "function") return src;
	if (typeof src === "string") {
		if (src.substring(0, 5) == "ws://" || src.substring(0, 6) == "wss://") src = {
			driver: "websocket",
			url: src
		};
		else if (src.substring(0, 6) == "clock:") src = { driver: "clock" };
		else if (src.substring(0, 7) == "random:") src = { driver: "random" };
		else if (src.substring(0, 10) == "benchmark:") src = {
			driver: "benchmark",
			url: src.substring(10)
		};
		else src = {
			driver: "recording",
			url: src
		};
	}
	if (src.driver === void 0) src.driver = "recording";
	if (src.driver == "recording") {
		if (src.format !== "segmented" && src.parser === void 0) src.parser = "asciicast";
		if (typeof src.parser === "string") {
			if (PARSERS.has(src.parser)) src.parser = PARSERS.get(src.parser);
			else throw new Error(`unknown parser: ${src.parser}`);
		}
	}
	if (DRIVERS.has(src.driver)) {
		const driver = DRIVERS.get(src.driver);
		return (callbacks, opts) => driver(src, callbacks, opts);
	} else throw new Error(`unsupported driver: ${JSON.stringify(src)}`);
}
// ../../node_modules/.pnpm/asciinema-player@3.18.0/node_modules/asciinema-player/dist/opts-flwsQGx_.js
var equalFn = (a, b) => a === b;
var $TRACK = Symbol("solid-track");
var signalOptions = { equals: equalFn };
var runEffects = runQueue;
var STALE = 1;
var PENDING = 2;
var UNOWNED = {
	owned: null,
	cleanups: null,
	context: null,
	owner: null
};
var Owner = null;
var Listener = null;
var Updates = null;
var Effects = null;
var ExecCount = 0;
function createRoot(fn, detachedOwner) {
	const listener = Listener, owner = Owner, unowned = fn.length === 0, current = detachedOwner === void 0 ? owner : detachedOwner, root = unowned ? UNOWNED : {
		owned: null,
		cleanups: null,
		context: current ? current.context : null,
		owner: current
	}, updateFn = unowned ? fn : () => fn(createDisposer(root));
	Owner = root;
	Listener = null;
	try {
		return runUpdates(updateFn, true);
	} finally {
		Listener = listener;
		Owner = owner;
	}
}
function createDisposer(root) {
	return () => untrack(() => cleanNode(root));
}
function createSignal(value, options) {
	options = options ? Object.assign({}, signalOptions, options) : signalOptions;
	const s = {
		value,
		observers: null,
		observerSlots: null,
		comparator: options.equals || void 0
	};
	const setter = (value) => {
		if (typeof value === "function") value = value(s.value);
		return writeSignal(s, value);
	};
	return [readSignal.bind(s), setter];
}
function createComputed(fn, value, options) {
	updateComputation(createComputation(fn, value, true, STALE));
}
function createRenderEffect(fn, value, options) {
	updateComputation(createComputation(fn, value, false, STALE));
}
function createEffect(fn, value, options) {
	runEffects = runUserEffects;
	const c = createComputation(fn, value, false, STALE);
	c.user = true;
	Effects ? Effects.push(c) : updateComputation(c);
}
function createMemo(fn, value, options) {
	options = options ? Object.assign({}, signalOptions, options) : signalOptions;
	const c = createComputation(fn, value, true, 0);
	c.observers = null;
	c.observerSlots = null;
	c.comparator = options.equals || void 0;
	updateComputation(c);
	return readSignal.bind(c);
}
function batch(fn) {
	return runUpdates(fn, false);
}
function untrack(fn) {
	if (Listener === null) return fn();
	const listener = Listener;
	Listener = null;
	try {
		return fn();
	} finally {
		Listener = listener;
	}
}
function onMount(fn) {
	createEffect(() => untrack(fn));
}
function onCleanup(fn) {
	if (Owner === null);
	else if (Owner.cleanups === null) Owner.cleanups = [fn];
	else Owner.cleanups.push(fn);
	return fn;
}
function children(fn) {
	const children = createMemo(fn);
	const memo = createMemo(() => resolveChildren(children()));
	memo.toArray = () => {
		const c = memo();
		return Array.isArray(c) ? c : c != null ? [c] : [];
	};
	return memo;
}
function readSignal() {
	if (this.sources && this.state) {
		if (this.state === STALE) updateComputation(this);
		else {
			const updates = Updates;
			Updates = null;
			runUpdates(() => lookUpstream(this), false);
			Updates = updates;
		}
	}
	if (Listener) {
		const observers = this.observers;
		if (!observers || observers[observers.length - 1] !== Listener) {
			const sSlot = observers ? observers.length : 0;
			if (!Listener.sources) {
				Listener.sources = [this];
				Listener.sourceSlots = [sSlot];
			} else {
				Listener.sources.push(this);
				Listener.sourceSlots.push(sSlot);
			}
			if (!observers) {
				this.observers = [Listener];
				this.observerSlots = [Listener.sources.length - 1];
			} else {
				observers.push(Listener);
				this.observerSlots.push(Listener.sources.length - 1);
			}
		}
	}
	return this.value;
}
function writeSignal(node, value, isComp) {
	let current = node.value;
	if (!node.comparator || !node.comparator(current, value)) {
		node.value = value;
		if (node.observers && node.observers.length) runUpdates(() => {
			for (let i = 0; i < node.observers.length; i += 1) {
				const o = node.observers[i];
				if (!o.state) {
					if (o.pure) Updates.push(o);
					else Effects.push(o);
					if (o.observers) markDownstream(o);
				}
				o.state = STALE;
			}
			if (Updates.length > 1e6) {
				Updates = [];
				throw new Error();
			}
		}, false);
	}
	return value;
}
function updateComputation(node) {
	if (!node.fn) return;
	cleanNode(node);
	const time = ExecCount;
	runComputation(node, node.value, time);
}
function runComputation(node, value, time) {
	let nextValue;
	const owner = Owner, listener = Listener;
	Listener = Owner = node;
	try {
		nextValue = node.fn(value);
	} catch (err) {
		if (node.pure) {
			node.state = STALE;
			node.owned && node.owned.forEach(cleanNode);
			node.owned = null;
		}
		node.updatedAt = time + 1;
		return handleError(err);
	} finally {
		Listener = listener;
		Owner = owner;
	}
	if (!node.updatedAt || node.updatedAt <= time) {
		if (node.updatedAt != null && "observers" in node) writeSignal(node, nextValue);
		else node.value = nextValue;
		node.updatedAt = time;
	}
}
function createComputation(fn, init, pure, state = STALE, options) {
	const c = {
		fn,
		state,
		updatedAt: null,
		owned: null,
		sources: null,
		sourceSlots: null,
		cleanups: null,
		value: init,
		owner: Owner,
		context: Owner ? Owner.context : null,
		pure
	};
	if (Owner === null);
	else if (Owner !== UNOWNED) {
		if (!Owner.owned) Owner.owned = [c];
		else Owner.owned.push(c);
	}
	return c;
}
function runTop(node) {
	if (node.state === 0) return;
	if (node.state === PENDING) return lookUpstream(node);
	if (node.suspense && untrack(node.suspense.inFallback)) return node.suspense.effects.push(node);
	const ancestors = [node];
	while ((node = node.owner) && (!node.updatedAt || node.updatedAt < ExecCount)) if (node.state) ancestors.push(node);
	for (let i = ancestors.length - 1; i >= 0; i--) {
		node = ancestors[i];
		if (node.state === STALE) updateComputation(node);
		else if (node.state === PENDING) {
			const updates = Updates;
			Updates = null;
			runUpdates(() => lookUpstream(node, ancestors[0]), false);
			Updates = updates;
		}
	}
}
function runUpdates(fn, init) {
	if (Updates) return fn();
	let wait = false;
	if (!init) Updates = [];
	if (Effects) wait = true;
	else Effects = [];
	ExecCount++;
	try {
		const res = fn();
		completeUpdates(wait);
		return res;
	} catch (err) {
		if (!wait) Effects = null;
		Updates = null;
		handleError(err);
	}
}
function completeUpdates(wait) {
	if (Updates) {
		runQueue(Updates);
		Updates = null;
	}
	if (wait) return;
	const e = Effects;
	Effects = null;
	if (e.length) runUpdates(() => runEffects(e), false);
}
function runQueue(queue) {
	for (let i = 0; i < queue.length; i++) runTop(queue[i]);
}
function runUserEffects(queue) {
	let i, userLength = 0;
	for (i = 0; i < queue.length; i++) {
		const e = queue[i];
		if (!e.user) runTop(e);
		else queue[userLength++] = e;
	}
	for (i = 0; i < userLength; i++) runTop(queue[i]);
}
function lookUpstream(node, ignore) {
	node.state = 0;
	for (let i = 0; i < node.sources.length; i += 1) {
		const source = node.sources[i];
		if (source.sources) {
			const state = source.state;
			if (state === STALE) {
				if (source !== ignore && (!source.updatedAt || source.updatedAt < ExecCount)) runTop(source);
			} else if (state === PENDING) lookUpstream(source, ignore);
		}
	}
}
function markDownstream(node) {
	for (let i = 0; i < node.observers.length; i += 1) {
		const o = node.observers[i];
		if (!o.state) {
			o.state = PENDING;
			if (o.pure) Updates.push(o);
			else Effects.push(o);
			o.observers && markDownstream(o);
		}
	}
}
function cleanNode(node) {
	let i;
	if (node.sources) while (node.sources.length) {
		const source = node.sources.pop(), index = node.sourceSlots.pop(), obs = source.observers;
		if (obs && obs.length) {
			const n = obs.pop(), s = source.observerSlots.pop();
			if (index < obs.length) {
				n.sourceSlots[s] = index;
				obs[index] = n;
				source.observerSlots[index] = s;
			}
		}
	}
	if (node.tOwned) {
		for (i = node.tOwned.length - 1; i >= 0; i--) cleanNode(node.tOwned[i]);
		delete node.tOwned;
	}
	if (node.owned) {
		for (i = node.owned.length - 1; i >= 0; i--) cleanNode(node.owned[i]);
		node.owned = null;
	}
	if (node.cleanups) {
		for (i = node.cleanups.length - 1; i >= 0; i--) node.cleanups[i]();
		node.cleanups = null;
	}
	node.state = 0;
}
function castError(err) {
	if (err instanceof Error) return err;
	return new Error(typeof err === "string" ? err : "Unknown error", { cause: err });
}
function handleError(err, owner = Owner) {
	throw castError(err);
}
function resolveChildren(children) {
	if (typeof children === "function" && !children.length) return resolveChildren(children());
	if (Array.isArray(children)) {
		const results = [];
		for (let i = 0; i < children.length; i++) {
			const result = resolveChildren(children[i]);
			if (Array.isArray(result)) {
				if (result.length < 32768) results.push.apply(results, result);
				else for (let j = 0; j < result.length; j++) results.push(result[j]);
			} else results.push(result);
		}
		return results;
	}
	return children;
}
var FALLBACK = Symbol("fallback");
function dispose(d) {
	for (let i = 0; i < d.length; i++) d[i]();
}
function mapArray(list, mapFn, options = {}) {
	let items = [], mapped = [], disposers = [], len = 0, indexes = mapFn.length > 1 ? [] : null;
	onCleanup(() => dispose(disposers));
	return () => {
		let newItems = list() || [], newLen = newItems.length, i, j;
		newItems[$TRACK];
		return untrack(() => {
			let newIndices, newIndicesNext, temp, tempdisposers, tempIndexes, start, end, newEnd, item;
			if (newLen === 0) {
				if (len !== 0) {
					dispose(disposers);
					disposers = [];
					items = [];
					mapped = [];
					len = 0;
					indexes && (indexes = []);
				}
				if (options.fallback) {
					items = [FALLBACK];
					mapped[0] = createRoot((disposer) => {
						disposers[0] = disposer;
						return options.fallback();
					});
					len = 1;
				}
			} else if (len === 0) {
				mapped = new Array(newLen);
				for (j = 0; j < newLen; j++) {
					items[j] = newItems[j];
					mapped[j] = createRoot(mapper);
				}
				len = newLen;
			} else {
				temp = new Array(newLen);
				tempdisposers = new Array(newLen);
				indexes && (tempIndexes = new Array(newLen));
				for (start = 0, end = Math.min(len, newLen); start < end && items[start] === newItems[start]; start++);
				for (end = len - 1, newEnd = newLen - 1; end >= start && newEnd >= start && items[end] === newItems[newEnd]; end--, newEnd--) {
					temp[newEnd] = mapped[end];
					tempdisposers[newEnd] = disposers[end];
					indexes && (tempIndexes[newEnd] = indexes[end]);
				}
				newIndices = /* @__PURE__ */ new Map();
				newIndicesNext = new Array(newEnd + 1);
				for (j = newEnd; j >= start; j--) {
					item = newItems[j];
					i = newIndices.get(item);
					newIndicesNext[j] = i === void 0 ? -1 : i;
					newIndices.set(item, j);
				}
				for (i = start; i <= end; i++) {
					item = items[i];
					j = newIndices.get(item);
					if (j !== void 0 && j !== -1) {
						temp[j] = mapped[i];
						tempdisposers[j] = disposers[i];
						indexes && (tempIndexes[j] = indexes[i]);
						j = newIndicesNext[j];
						newIndices.set(item, j);
					} else disposers[i]();
				}
				for (j = start; j < newLen; j++) if (j in temp) {
					mapped[j] = temp[j];
					disposers[j] = tempdisposers[j];
					if (indexes) {
						indexes[j] = tempIndexes[j];
						indexes[j](j);
					}
				} else mapped[j] = createRoot(mapper);
				mapped = mapped.slice(0, len = newLen);
				items = newItems.slice(0);
			}
			return mapped;
		});
		function mapper(disposer) {
			disposers[j] = disposer;
			if (indexes) {
				const [s, set] = createSignal(j);
				indexes[j] = set;
				return mapFn(newItems[j], s);
			}
			return mapFn(newItems[j]);
		}
	};
}
function createComponent(Comp, props) {
	return untrack(() => Comp(props || {}));
}
var narrowedError = (name) => `Stale read from <${name}>.`;
function For(props) {
	const fallback = "fallback" in props && { fallback: () => props.fallback };
	return createMemo(mapArray(() => props.each, props.children, fallback || void 0));
}
function Show(props) {
	const keyed = props.keyed;
	const conditionValue = createMemo(() => props.when, void 0, void 0);
	const condition = keyed ? conditionValue : createMemo(conditionValue, void 0, { equals: (a, b) => !a === !b });
	return createMemo(() => {
		const c = condition();
		if (c) {
			const child = props.children;
			return typeof child === "function" && child.length > 0 ? untrack(() => child(keyed ? c : () => {
				if (!untrack(condition)) throw narrowedError("Show");
				return conditionValue();
			})) : child;
		}
		return props.fallback;
	}, void 0, void 0);
}
function Switch(props) {
	const chs = children(() => props.children);
	const switchFunc = createMemo(() => {
		const ch = chs();
		const mps = Array.isArray(ch) ? ch : [ch];
		let func = () => void 0;
		for (let i = 0; i < mps.length; i++) {
			const index = i;
			const mp = mps[i];
			const prevFunc = func;
			const conditionValue = createMemo(() => prevFunc() ? void 0 : mp.when, void 0, void 0);
			const condition = mp.keyed ? conditionValue : createMemo(conditionValue, void 0, { equals: (a, b) => !a === !b });
			func = () => prevFunc() || (condition() ? [
				index,
				conditionValue,
				mp
			] : void 0);
		}
		return func;
	});
	return createMemo(() => {
		const sel = switchFunc()();
		if (!sel) return props.fallback;
		const [index, conditionValue, mp] = sel;
		const child = mp.children;
		return typeof child === "function" && child.length > 0 ? untrack(() => child(mp.keyed ? conditionValue() : () => {
			if (untrack(switchFunc)()?.[0] !== index) throw narrowedError("Match");
			return conditionValue();
		})) : child;
	}, void 0, void 0);
}
function Match(props) {
	return props;
}
function reconcileArrays(parentNode, a, b) {
	let bLength = b.length, aEnd = a.length, bEnd = bLength, aStart = 0, bStart = 0, after = a[aEnd - 1].nextSibling, map = null;
	while (aStart < aEnd || bStart < bEnd) {
		if (a[aStart] === b[bStart]) {
			aStart++;
			bStart++;
			continue;
		}
		while (a[aEnd - 1] === b[bEnd - 1]) {
			aEnd--;
			bEnd--;
		}
		if (aEnd === aStart) {
			const node = bEnd < bLength ? bStart ? b[bStart - 1].nextSibling : b[bEnd - bStart] : after;
			while (bStart < bEnd) parentNode.insertBefore(b[bStart++], node);
		} else if (bEnd === bStart) while (aStart < aEnd) {
			if (!map || !map.has(a[aStart])) a[aStart].remove();
			aStart++;
		}
		else if (a[aStart] === b[bEnd - 1] && b[bStart] === a[aEnd - 1]) {
			const node = a[--aEnd].nextSibling;
			parentNode.insertBefore(b[bStart++], a[aStart++].nextSibling);
			parentNode.insertBefore(b[--bEnd], node);
			a[aEnd] = b[bEnd];
		} else {
			if (!map) {
				map = /* @__PURE__ */ new Map();
				let i = bStart;
				while (i < bEnd) map.set(b[i], i++);
			}
			const index = map.get(a[aStart]);
			if (index != null) {
				if (bStart < index && index < bEnd) {
					let i = aStart, sequence = 1, t;
					while (++i < aEnd && i < bEnd) {
						if ((t = map.get(a[i])) == null || t !== index + sequence) break;
						sequence++;
					}
					if (sequence > index - bStart) {
						const node = a[aStart];
						while (bStart < index) parentNode.insertBefore(b[bStart++], node);
					} else parentNode.replaceChild(b[bStart++], a[aStart++]);
				} else aStart++;
			} else a[aStart++].remove();
		}
	}
}
var $$EVENTS = "_$DX_DELEGATE";
function render(code, element, init, options = {}) {
	let disposer;
	createRoot((dispose) => {
		disposer = dispose;
		element === document ? code() : insert(element, code(), element.firstChild ? null : void 0, init);
	}, options.owner);
	return () => {
		disposer();
		element.textContent = "";
	};
}
function template(html, isImportNode, isSVG, isMathML) {
	let node;
	const create = () => {
		const t = document.createElement("template");
		t.innerHTML = html;
		return t.content.firstChild;
	};
	const fn = () => (node || (node = create())).cloneNode(true);
	fn.cloneNode = fn;
	return fn;
}
function delegateEvents(eventNames, document = window.document) {
	const e = document[$$EVENTS] || (document[$$EVENTS] = /* @__PURE__ */ new Set());
	for (let i = 0, l = eventNames.length; i < l; i++) {
		const name = eventNames[i];
		if (!e.has(name)) {
			e.add(name);
			document.addEventListener(name, eventHandler);
		}
	}
}
function setAttribute(node, name, value) {
	if (value == null) node.removeAttribute(name);
	else node.setAttribute(name, value);
}
function className(node, value) {
	if (value == null) node.removeAttribute("class");
	else node.className = value;
}
function style(node, value, prev) {
	if (!value) return prev ? setAttribute(node, "style") : value;
	const nodeStyle = node.style;
	if (typeof value === "string") return nodeStyle.cssText = value;
	typeof prev === "string" && (nodeStyle.cssText = prev = void 0);
	prev || (prev = {});
	value || (value = {});
	let v, s;
	for (s in prev) {
		value[s] ?? nodeStyle.removeProperty(s);
		delete prev[s];
	}
	for (s in value) {
		v = value[s];
		if (v !== prev[s]) {
			nodeStyle.setProperty(s, v);
			prev[s] = v;
		}
	}
	return prev;
}
function setStyleProperty(node, name, value) {
	value != null ? node.style.setProperty(name, value) : node.style.removeProperty(name);
}
function use(fn, element, arg) {
	return untrack(() => fn(element, arg));
}
function insert(parent, accessor, marker, initial) {
	if (marker !== void 0 && !initial) initial = [];
	if (typeof accessor !== "function") return insertExpression(parent, accessor, initial, marker);
	createRenderEffect((current) => insertExpression(parent, accessor(), current, marker), initial);
}
function eventHandler(e) {
	let node = e.target;
	const key = `$$${e.type}`;
	const oriTarget = e.target;
	const oriCurrentTarget = e.currentTarget;
	const retarget = (value) => Object.defineProperty(e, "target", {
		configurable: true,
		value
	});
	const handleNode = () => {
		const handler = node[key];
		if (handler && !node.disabled) {
			const data = node[`${key}Data`];
			data !== void 0 ? handler.call(node, data, e) : handler.call(node, e);
			if (e.cancelBubble) return;
		}
		node.host && typeof node.host !== "string" && !node.host._$host && node.contains(e.target) && retarget(node.host);
		return true;
	};
	const walkUpTree = () => {
		while (handleNode() && (node = node._$host || node.parentNode || node.host));
	};
	Object.defineProperty(e, "currentTarget", {
		configurable: true,
		get() {
			return node || document;
		}
	});
	try {
		if (e.composedPath) {
			const path = e.composedPath();
			retarget(path[0]);
			for (let i = 0; i < path.length - 2; i++) {
				node = path[i];
				if (!handleNode()) break;
				if (node._$host) {
					node = node._$host;
					walkUpTree();
					break;
				}
				if (node.parentNode === oriCurrentTarget) break;
			}
		} else walkUpTree();
		retarget(oriTarget);
	} finally {
		e = node = null;
	}
}
function insertExpression(parent, value, current, marker, unwrapArray) {
	while (typeof current === "function") current = current();
	if (value === current) return current;
	const t = typeof value, multi = marker !== void 0;
	parent = multi && current[0] && current[0].parentNode || parent;
	if (t === "string" || t === "number") {
		if (t === "number") {
			value = value.toString();
			if (value === current) return current;
		}
		if (multi) {
			let node = current[0];
			if (node && node.nodeType === 3) node.data !== value && (node.data = value);
			else node = document.createTextNode(value);
			current = cleanChildren(parent, current, marker, node);
		} else if (current !== "" && typeof current === "string") current = parent.firstChild.data = value;
		else current = parent.textContent = value;
	} else if (value == null || t === "boolean") current = cleanChildren(parent, current, marker);
	else if (t === "function") {
		createRenderEffect(() => {
			let v = value();
			while (typeof v === "function") v = v();
			current = insertExpression(parent, v, current, marker);
		});
		return () => current;
	} else if (Array.isArray(value)) {
		const array = [];
		const currentArray = current && Array.isArray(current);
		if (normalizeIncomingArray(array, value, current, unwrapArray)) {
			createRenderEffect(() => current = insertExpression(parent, array, current, marker, true));
			return () => current;
		}
		if (array.length === 0) {
			current = cleanChildren(parent, current, marker);
			if (multi) return current;
		} else if (currentArray) {
			if (current.length === 0) appendNodes(parent, array, marker);
			else reconcileArrays(parent, current, array);
		} else {
			current && cleanChildren(parent);
			appendNodes(parent, array);
		}
		current = array;
	} else if (value.nodeType) {
		if (Array.isArray(current)) {
			if (multi) return current = cleanChildren(parent, current, marker, value);
			cleanChildren(parent, current, null, value);
		} else if (current == null || current === "" || !parent.firstChild) parent.appendChild(value);
		else parent.replaceChild(value, parent.firstChild);
		current = value;
	}
	return current;
}
function normalizeIncomingArray(normalized, array, current, unwrap) {
	let dynamic = false;
	for (let i = 0, len = array.length; i < len; i++) {
		let item = array[i], prev = current && current[normalized.length], t;
		if (item == null || item === true || item === false);
		else if ((t = typeof item) === "object" && item.nodeType) normalized.push(item);
		else if (Array.isArray(item)) dynamic = normalizeIncomingArray(normalized, item, prev) || dynamic;
		else if (t === "function") {
			if (unwrap) {
				while (typeof item === "function") item = item();
				dynamic = normalizeIncomingArray(normalized, Array.isArray(item) ? item : [item], Array.isArray(prev) ? prev : [prev]) || dynamic;
			} else {
				normalized.push(item);
				dynamic = true;
			}
		} else {
			const value = String(item);
			if (prev && prev.nodeType === 3 && prev.data === value) normalized.push(prev);
			else normalized.push(document.createTextNode(value));
		}
	}
	return dynamic;
}
function appendNodes(parent, array, marker = null) {
	for (let i = 0, len = array.length; i < len; i++) parent.insertBefore(array[i], marker);
}
function cleanChildren(parent, current, marker, replacement) {
	if (marker === void 0) return parent.textContent = "";
	const node = replacement || document.createTextNode("");
	if (current.length) {
		let inserted = false;
		for (let i = current.length - 1; i >= 0; i--) {
			const el = current[i];
			if (node !== el) {
				const isParent = el.parentNode === parent;
				if (!inserted && !i) isParent ? parent.replaceChild(node, el) : parent.insertBefore(node, marker);
				else isParent && el.remove();
			} else inserted = true;
		}
	} else parent.insertBefore(node, marker);
	return [node];
}
var Slide = (props) => {
	const resolved = children(() => props.children);
	const [el, setEl] = createSignal(untrack(resolved));
	let cancel;
	const transition = (element, phase, done) => {
		const classes = [
			`slide-${phase}`,
			`slide-${phase}-active`,
			`slide-${phase}-to`
		];
		let raf;
		const cleanup = () => {
			cancelAnimationFrame(raf);
			element.removeEventListener("transitionend", onEnd);
			element.classList.remove(...classes);
			cancel = void 0;
		};
		const onEnd = (e) => {
			if (e.target === element) {
				cleanup();
				done?.();
			}
		};
		cancel = cleanup;
		element.classList.add(classes[0], classes[1]);
		element.addEventListener("transitionend", onEnd);
		raf = requestAnimationFrame(() => {
			raf = requestAnimationFrame(() => {
				element.classList.remove(classes[0]);
				element.classList.add(classes[2]);
			});
		});
	};
	createComputed((prev) => {
		const next = resolved();
		if (next !== prev) {
			cancel?.();
			if (next) {
				setEl(next);
				transition(next, "enter");
			} else transition(untrack(el), "exit", () => setEl(void 0));
		}
		return next;
	}, untrack(resolved));
	return el;
};
var wasm;
function addHeapObject(obj) {
	if (heap_next === heap.length) heap.push(heap.length + 1);
	const idx = heap_next;
	heap_next = heap[idx];
	heap[idx] = obj;
	return idx;
}
function debugString(val) {
	const type = typeof val;
	if (type == "number" || type == "boolean" || val == null) return `${val}`;
	if (type == "string") return `"${val}"`;
	if (type == "symbol") {
		const description = val.description;
		if (description == null) return "Symbol";
		else return `Symbol(${description})`;
	}
	if (type == "function") {
		const name = val.name;
		if (typeof name == "string" && name.length > 0) return `Function(${name})`;
		else return "Function";
	}
	if (Array.isArray(val)) {
		const length = val.length;
		let debug = "[";
		if (length > 0) debug += debugString(val[0]);
		for (let i = 1; i < length; i++) debug += ", " + debugString(val[i]);
		debug += "]";
		return debug;
	}
	const builtInMatches = /\[object ([^\]]+)\]/.exec(toString.call(val));
	let className;
	if (builtInMatches && builtInMatches.length > 1) className = builtInMatches[1];
	else return toString.call(val);
	if (className == "Object") try {
		return "Object(" + JSON.stringify(val) + ")";
	} catch (_) {
		return "Object";
	}
	if (val instanceof Error) return `${val.name}: ${val.message}\n${val.stack}`;
	return className;
}
function dropObject(idx) {
	if (idx < 132) return;
	heap[idx] = heap_next;
	heap_next = idx;
}
function getArrayU32FromWasm0(ptr, len) {
	ptr = ptr >>> 0;
	return getUint32ArrayMemory0().subarray(ptr / 4, ptr / 4 + len);
}
var cachedDataViewMemory0 = null;
function getDataViewMemory0() {
	if (cachedDataViewMemory0 === null || cachedDataViewMemory0.buffer.detached === true || cachedDataViewMemory0.buffer.detached === void 0 && cachedDataViewMemory0.buffer !== wasm.memory.buffer) cachedDataViewMemory0 = new DataView(wasm.memory.buffer);
	return cachedDataViewMemory0;
}
function getStringFromWasm0(ptr, len) {
	ptr = ptr >>> 0;
	return decodeText(ptr, len);
}
var cachedUint32ArrayMemory0 = null;
function getUint32ArrayMemory0() {
	if (cachedUint32ArrayMemory0 === null || cachedUint32ArrayMemory0.byteLength === 0) cachedUint32ArrayMemory0 = new Uint32Array(wasm.memory.buffer);
	return cachedUint32ArrayMemory0;
}
var cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
	if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
	return cachedUint8ArrayMemory0;
}
function getObject(idx) {
	return heap[idx];
}
var heap = new Array(128).fill(void 0);
heap.push(void 0, null, true, false);
var heap_next = heap.length;
function passStringToWasm0(arg, malloc, realloc) {
	if (realloc === void 0) {
		const buf = cachedTextEncoder.encode(arg);
		const ptr = malloc(buf.length, 1) >>> 0;
		getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
		WASM_VECTOR_LEN = buf.length;
		return ptr;
	}
	let len = arg.length;
	let ptr = malloc(len, 1) >>> 0;
	const mem = getUint8ArrayMemory0();
	let offset = 0;
	for (; offset < len; offset++) {
		const code = arg.charCodeAt(offset);
		if (code > 127) break;
		mem[ptr + offset] = code;
	}
	if (offset !== len) {
		if (offset !== 0) arg = arg.slice(offset);
		ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
		const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
		const ret = cachedTextEncoder.encodeInto(arg, view);
		offset += ret.written;
		ptr = realloc(ptr, len, offset, 1) >>> 0;
	}
	WASM_VECTOR_LEN = offset;
	return ptr;
}
function takeObject(idx) {
	const ret = getObject(idx);
	dropObject(idx);
	return ret;
}
var cachedTextDecoder = new TextDecoder("utf-8", {
	ignoreBOM: true,
	fatal: true
});
cachedTextDecoder.decode();
var MAX_SAFARI_DECODE_BYTES = 2146435072;
var numBytesDecoded = 0;
function decodeText(ptr, len) {
	numBytesDecoded += len;
	if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
		cachedTextDecoder = new TextDecoder("utf-8", {
			ignoreBOM: true,
			fatal: true
		});
		cachedTextDecoder.decode();
		numBytesDecoded = len;
	}
	return cachedTextDecoder.decode(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}
var cachedTextEncoder = new TextEncoder();
if (!("encodeInto" in cachedTextEncoder)) cachedTextEncoder.encodeInto = function(arg, view) {
	const buf = cachedTextEncoder.encode(arg);
	view.set(buf);
	return {
		read: arg.length,
		written: buf.length
	};
};
var WASM_VECTOR_LEN = 0;
var VtFinalization = typeof FinalizationRegistry === "undefined" ? {
	register: () => {},
	unregister: () => {}
} : new FinalizationRegistry((ptr) => wasm.__wbg_vt_free(ptr >>> 0, 1));
var Vt$1 = class Vt {
	static __wrap(ptr) {
		ptr = ptr >>> 0;
		const obj = Object.create(Vt.prototype);
		obj.__wbg_ptr = ptr;
		VtFinalization.register(obj, obj.__wbg_ptr, obj);
		return obj;
	}
	__destroy_into_raw() {
		const ptr = this.__wbg_ptr;
		this.__wbg_ptr = 0;
		VtFinalization.unregister(this);
		return ptr;
	}
	free() {
		const ptr = this.__destroy_into_raw();
		wasm.__wbg_vt_free(ptr, 0);
	}
	/**
	* @param {string} s
	* @returns {any}
	*/
	feed(s) {
		const ptr0 = passStringToWasm0(s, wasm.__wbindgen_export, wasm.__wbindgen_export2);
		const len0 = WASM_VECTOR_LEN;
		return takeObject(wasm.vt_feed(this.__wbg_ptr, ptr0, len0));
	}
	/**
	* @param {number} cols
	* @param {number} rows
	* @returns {any}
	*/
	resize(cols, rows) {
		return takeObject(wasm.vt_resize(this.__wbg_ptr, cols, rows));
	}
	/**
	* @returns {Uint32Array}
	*/
	getSize() {
		try {
			const retptr = wasm.__wbindgen_add_to_stack_pointer(-16);
			wasm.vt_getSize(retptr, this.__wbg_ptr);
			var r0 = getDataViewMemory0().getInt32(retptr + 0, true);
			var r1 = getDataViewMemory0().getInt32(retptr + 4, true);
			var v1 = getArrayU32FromWasm0(r0, r1).slice();
			wasm.__wbindgen_export3(r0, r1 * 4, 4);
			return v1;
		} finally {
			wasm.__wbindgen_add_to_stack_pointer(16);
		}
	}
	/**
	* @param {number} row
	* @param {boolean} cursor_on
	* @returns {any}
	*/
	getLine(row, cursor_on) {
		return takeObject(wasm.vt_getLine(this.__wbg_ptr, row, cursor_on));
	}
	/**
	* @returns {any}
	*/
	getCursor() {
		return takeObject(wasm.vt_getCursor(this.__wbg_ptr));
	}
};
if (Symbol.dispose) Vt$1.prototype[Symbol.dispose] = Vt$1.prototype.free;
/**
* @param {number} cols
* @param {number} rows
* @param {number} scrollback_limit
* @param {boolean} bold_is_bright
* @returns {Vt}
*/
function create$1(cols, rows, scrollback_limit, bold_is_bright) {
	try {
		const retptr = wasm.__wbindgen_add_to_stack_pointer(-16);
		wasm.create(retptr, cols, rows, scrollback_limit, bold_is_bright);
		var r0 = getDataViewMemory0().getInt32(retptr + 0, true);
		var r1 = getDataViewMemory0().getInt32(retptr + 4, true);
		if (getDataViewMemory0().getInt32(retptr + 8, true)) throw takeObject(r1);
		return Vt$1.__wrap(r0);
	} finally {
		wasm.__wbindgen_add_to_stack_pointer(16);
	}
}
var EXPECTED_RESPONSE_TYPES = /* @__PURE__ */ new Set([
	"basic",
	"cors",
	"default"
]);
async function __wbg_load(module, imports) {
	if (typeof Response === "function" && module instanceof Response) {
		if (typeof WebAssembly.instantiateStreaming === "function") try {
			return await WebAssembly.instantiateStreaming(module, imports);
		} catch (e) {
			if (module.ok && EXPECTED_RESPONSE_TYPES.has(module.type) && module.headers.get("Content-Type") !== "application/wasm") console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);
			else throw e;
		}
		const bytes = await module.arrayBuffer();
		return await WebAssembly.instantiate(bytes, imports);
	} else {
		const instance = await WebAssembly.instantiate(module, imports);
		if (instance instanceof WebAssembly.Instance) return {
			instance,
			module
		};
		else return instance;
	}
}
function __wbg_get_imports() {
	const imports = {};
	imports.wbg = {};
	imports.wbg.__wbg_Error_52673b7de5a0ca89 = function(arg0, arg1) {
		return addHeapObject(Error(getStringFromWasm0(arg0, arg1)));
	};
	imports.wbg.__wbg___wbindgen_debug_string_adfb662ae34724b6 = function(arg0, arg1) {
		const ptr1 = passStringToWasm0(debugString(getObject(arg1)), wasm.__wbindgen_export, wasm.__wbindgen_export2);
		const len1 = WASM_VECTOR_LEN;
		getDataViewMemory0().setInt32(arg0 + 4, len1, true);
		getDataViewMemory0().setInt32(arg0 + 0, ptr1, true);
	};
	imports.wbg.__wbg___wbindgen_throw_dd24417ed36fc46e = function(arg0, arg1) {
		throw new Error(getStringFromWasm0(arg0, arg1));
	};
	imports.wbg.__wbg_new_13317ed16189158e = function() {
		return addHeapObject(new Array());
	};
	imports.wbg.__wbg_new_4ceb6a766bf78b04 = function() {
		return addHeapObject(/* @__PURE__ */ new Object());
	};
	imports.wbg.__wbg_set_3f1d0b984ed272ed = function(arg0, arg1, arg2) {
		getObject(arg0)[takeObject(arg1)] = takeObject(arg2);
	};
	imports.wbg.__wbg_set_8b6a9a61e98a8881 = function(arg0, arg1, arg2) {
		getObject(arg0)[arg1 >>> 0] = takeObject(arg2);
	};
	imports.wbg.__wbindgen_cast_2241b6af4c4b2941 = function(arg0, arg1) {
		return addHeapObject(getStringFromWasm0(arg0, arg1));
	};
	imports.wbg.__wbindgen_cast_4625c577ab2ec9ee = function(arg0) {
		return addHeapObject(BigInt.asUintN(64, arg0));
	};
	imports.wbg.__wbindgen_cast_d6cd19b81560fd6e = function(arg0) {
		return addHeapObject(arg0);
	};
	imports.wbg.__wbindgen_object_clone_ref = function(arg0) {
		return addHeapObject(getObject(arg0));
	};
	imports.wbg.__wbindgen_object_drop_ref = function(arg0) {
		takeObject(arg0);
	};
	return imports;
}
function __wbg_finalize_init(instance, module) {
	wasm = instance.exports;
	__wbg_init.__wbindgen_wasm_module = module;
	cachedDataViewMemory0 = null;
	cachedUint32ArrayMemory0 = null;
	cachedUint8ArrayMemory0 = null;
	return wasm;
}
function initSync(module) {
	if (wasm !== void 0) return wasm;
	if (typeof module !== "undefined") {
		if (Object.getPrototypeOf(module) === Object.prototype) ({module} = module);
		else console.warn("using deprecated parameters for `initSync()`; pass a single object instead");
	}
	const imports = __wbg_get_imports();
	if (!(module instanceof WebAssembly.Module)) module = new WebAssembly.Module(module);
	return __wbg_finalize_init(new WebAssembly.Instance(module, imports), module);
}
async function __wbg_init(module_or_path) {
	if (wasm !== void 0) return wasm;
	if (typeof module_or_path !== "undefined") {
		if (Object.getPrototypeOf(module_or_path) === Object.prototype) ({module_or_path} = module_or_path);
		else console.warn("using deprecated parameters for the initialization function; pass a single object instead");
	}
	const imports = __wbg_get_imports();
	if (typeof module_or_path === "string" || typeof Request === "function" && module_or_path instanceof Request || typeof URL === "function" && module_or_path instanceof URL) module_or_path = fetch(module_or_path);
	const { instance, module } = await __wbg_load(await module_or_path, imports);
	return __wbg_finalize_init(instance, module);
}
var exports$1 = /*#__PURE__*/ Object.freeze({
	__proto__: null,
	Vt: Vt$1,
	create: create$1,
	default: __wbg_init,
	initSync
});
var base64codes = [
	62,
	0,
	0,
	0,
	63,
	52,
	53,
	54,
	55,
	56,
	57,
	58,
	59,
	60,
	61,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
	1,
	2,
	3,
	4,
	5,
	6,
	7,
	8,
	9,
	10,
	11,
	12,
	13,
	14,
	15,
	16,
	17,
	18,
	19,
	20,
	21,
	22,
	23,
	24,
	25,
	0,
	0,
	0,
	0,
	0,
	0,
	26,
	27,
	28,
	29,
	30,
	31,
	32,
	33,
	34,
	35,
	36,
	37,
	38,
	39,
	40,
	41,
	42,
	43,
	44,
	45,
	46,
	47,
	48,
	49,
	50,
	51
];
function getBase64Code(charCode) {
	return base64codes[charCode - 43];
}
function base64Decode(str) {
	let missingOctets = str.endsWith("==") ? 2 : str.endsWith("=") ? 1 : 0;
	let n = str.length;
	let result = new Uint8Array(3 * (n / 4));
	let buffer;
	for (let i = 0, j = 0; i < n; i += 4, j += 3) {
		buffer = getBase64Code(str.charCodeAt(i)) << 18 | getBase64Code(str.charCodeAt(i + 1)) << 12 | getBase64Code(str.charCodeAt(i + 2)) << 6 | getBase64Code(str.charCodeAt(i + 3));
		result[j] = buffer >> 16;
		result[j + 1] = buffer >> 8 & 255;
		result[j + 2] = buffer & 255;
	}
	return result.subarray(0, result.length - missingOctets);
}
var vtWasmModule = base64Decode("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EIUBIgNFDQAgAyAESw0AIAIgBCADayIENgKoAQsgAiAbNgLkAiACQQA2AtgCIAJBADYC0AIgAiACQcABajYC4AIDfyACQdACahCGASIDBH8gAyAEEK0BDAEFIAIoAqgBCwshBAsgBCAFTQRAIAggAikDwAE3AgAgCEEIaiASKQMANwIAIAJBADYC+AIgAkIANwLwAiACQoCAgIAgNwLoAiACIAY2AtQCIAJB4ABqIQMgBiEEA0ACQAJAAkAgAyAERg0AIAIgA0EIajYC0AIgAkEIaiAIEJIBIAItAAwiBEECaw4CAgABCyACQUBrIgMgAkGgAWogChBAIAMgAigCpAEgAigCqAEQrgEgAi0AuAFFBEAgAkEAOgBYIAMgDRBYCyACQaABahDXAUGAgICAeCEDDAQLIAIoAgghBSADIARBAXE6AAQgAyAFIApqNgIACyACKALQAiEDIAIoAtQCIQQMAAsACyACKAKkASAEIAVBvN3AABDCAS0ADkECRgRAIBZBCGogAigCRCACKAJIIApBAWtBzN3AABDCASIDQQxqLwEAOwEAIBYgAykCBDcCACACQQA6AN4CIAJBIDYC0AIgAkFAayACQdACakHc3cAAEJMBIAIoAkghCiAFQQFrIQULIAJB0AJqIAJBoAFqIAUQN0EAIQMDQCADQRBGBEACQCACQUBrIgMgAkGgAWogChBAIAIoAqgBIgQgBUkNACADIAIoAqQBIAUQrgEgAigCoAEhAyACKAKkASIMIAIoAqgBIgQgBRC3ASAVIAIpA8ABNwAAIBVBCGogEikDADcAACACQdgBaiAIKAIANgIAIAIgAikC0AI3A9ABIAItALgBIQ8gERDTASAEIAQgBWsiBSAEIAVJGyEODAMLBQJAIAJBwAFqIANqIgRBBGoiDi0AACIPQQJGDQAgBCgCACIMIAVJBEAgAkHgAGogA2oiBCAKIAxqNgIAIA5BAjoAACAEQQRqIA86AAAMAQsgBCAMIAVrNgIACyADQQhqIQMMAQsLIAUgBEHs3cAAEOoBAAsgARDcASABIA42AgggASAMNgIEIAEgAzYCACABIA86ABggEyACKQPQATcCACATQQhqIAJB2AFqKAIANgIAIAcgAikDiAI3AAAgB0EIaiACQYgCaiIDQQhqKQMANwAAIAdBD2ogA0EPaigAADYAACACKAJI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AyADKQLcAzcAvwMgDCADKQC8AzcAACAMQQhqIANBvANqIgBBCGopAAA3AAAgDEEPaiAAQQ9qKAAANgAAIANBKToAoAMMNQsgA0HwAmogECAFKAKcBEGI5cAAEKABIAMoAvQCIQQgAygC8AIhAEEAIQYDQCAGQRRHBEAgA0HcA2ogBmpBADoAACAGQQVqIQYMAQsLIBEgAykB3AM3AQAgEUEIaiADQdwDaiIBQQhqKQEANwEAIBFBEGogAUEQaigBADYBACADQQA7AbwDA0ACfwJAAkACQAJAAkAgBARAIANB6AJqIAAQlwEgAygC6AIhBwJAAkACQAJAAkACQCADKALsAkEBaw4GAAQDBAECBAsCQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkAgBy8BACICDh4AAQIDBAUOBg4HDg4ODg4ODg4ODg4ICAkKCw4MDg0OCyADQdgBakEBIAAgBEHQ5cAAEK8BIANBADoA1wMgAygC3AEhBCADKALYAQwZCyADQeABakEBIAAgBEHg5cAAEK8BIANBAToA1wMgAygC5AEhBCADKALgAQwYCyADQegBakEBIAAgBEHw5cAAEK8BIANBAjoA1wMgAygC7AEhBCADKALoAQwXCyADQfABakEBIAAgBEGA5sAAEK8BIANBAzoA1wMgAygC9AEhBCADKALwAQwWCyADQfgBakEBIAAgBEGQ5sAAEK8BIANBBDoA1wMgAygC/AEhBCADKAL4AQwVCyADQYACakEBIAAgBEGg5sAAEK8BIANBBToA1wMgAygChAIhBCADKAKAAgwUCyADQYgCakEBIAAgBEGw5sAAEK8BIANBBjoA1wMgAygCjAIhBCADKAKIAgwTCyADQZACakEBIAAgBEHA5sAAEK8BIANBBzoA1wMgAygClAIhBCADKAKQAgwSCyADQZgCakEBIAAgBEHQ5sAAEK8BIANBCDoA1wMgAygCnAIhBCADKAKYAgwRCyADQaACakEBIAAgBEHg5sAAEK8BIANBCToA1wMgAygCpAIhBCADKAKgAgwQCyADQagCakEBIAAgBEHw5sAAEK8BIANBCjoA1wMgAygCrAIhBCADKAKoAgwPCyADQbACakEBIAAgBEGA58AAEK8BIANBCzoA1wMgAygCtAIhBCADKAKwAgwOCyADQbgCakEBIAAgBEGQ58AAEK8BIANBDDoA1wMgAygCvAIhBCADKAK4AgwNCyADQcACakEBIAAgBEGg58AAEK8BIANBDToA1wMgAygCxAIhBCADKALAAgwMCwJAAkAgAkEeayIBQf//A3FBCE8EQCACQSZrDgIBCQILIANBOGpBASAAIARBwOnAABCvASADIAE6ANkDIANBDjsA1wMgAygCPCEEIAMoAjgMDQsCQCAEQQFHBEAgA0HIAWogAEEQahCXASADKALIASIBDQELIANBmAFqQQEgACAEQbDnwAAQrwEgAygCnAEhBCADKAKYASEADA4LAkACQAJAIAMoAswBQQFHDQAgAS8BAEECaw4EAQAAAgALIANBoAFqQQEgACAEQYDowAAQrwEgAygCpAEhBCADKAKgASEADA8LIARBBU8EQCAALQAkIQYgAC8BNCECIAAvAUQhASADQbABakEFIAAgBEHA58AAEK8BIANBDjoA1wMgAyAGIAJBCHRBgP4DcSABQRB0cnJBCHRBAXI2ANgDIAMoArQBIQQgAygCsAEMDgsgA0GoAWpBAiAAIARB0OfAABCvASADKAKsASEEIAMoAqgBIQAMDgsgBEEDTwRAIAAtACQhASADQcABakEDIAAgBEHg58AAEK8BIAMgAToA2QMgA0EOOwDXAyADKALEASEEIAMoAsABDA0LIANBuAFqQQIgACAEQfDnwAAQrwEgAygCvAEhBCADKAK4ASEADA0LAkACQCACQfj/A3FBKEcEQCACQTBrDgIBCgILIANBQGtBASAAIARBsOnAABCvASADIAJBKGs6ANkDIANBEDsA1wMgAygCRCEEIAMoAkAMDQsCQCAEQQFHBEAgA0GIAWogAEEQahCXASADKAKIASIBDQELIANB2ABqQQEgACAEQaDowAAQrwEgAygCXCEEIAMoAlghAAwOCwJAAkACQCADKAKMAUEBRw0AIAEvAQBBAmsOBAEAAAIACyADQeAAakEBIAAgBEHw6MAAEK8BIAMoAmQhBCADKAJgIQAMDwsgBEEFTwRAIAAtACQhBiAALwFEIQIgAC8BNCEBIANB8ABqQQUgACAEQbDowAAQrwEgA0EQOgDXAyADIAYgAUEIdEGA/gNxIAJBEHRyckEIdEEBcjYA2AMgAygCdCEEIAMoAnAMDgsgA0HoAGpBAiAAIARBwOjAABCvASADKAJsIQQg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IABB+OzAADYCCCAAQgE3AhQgACAAQS9qrUKAgICA4ACENwMgIAAgAEEgajYCECAAQQhqQciKwQAQvAEAC9wDAQp/IwBBQGoiAyQAA0AgBEEIRkUEQCADQTBqIARqQQE7AQAgBEECaiEEDAELCyADIAMpAzA3ARYgA0EAOwEUIANBFGoiBEEEaiEKIANBM2ohByAEQQJyIQsgBEEBciEIA0ACQAJAAkAgASACRwRAIAEvAQQiBEEZSw0BQQEgBHRBwoGAEHFFDQEMAgsgACADKQIUNwIAIABBCGogA0EcaikCADcCACADQUBrJAAPCyAEQZcIa0EDSQ0AIARBL0cNAUGXCCEECyADLQAURQRAIAMtABUiBUEETwRAIANBCGpBCEECQQJB9OHAABBPQQAhBSADQQA2AiwgAyADKAIMIgk2AiggAyADKAIIIgY2AiQgBkEDTQRAIANBJGpBAEEEQQJBAhCaASADKAIoIQkgAygCLCEFCyADQSRqIgZBCGoiDCAFQQRqNgIAIAkgBUEBdGogAykBFjcBACAGIARBhOLAABCoASAHQQhqIAwoAgA2AAAgByADKQIkNwAAIANBFGoQ0gEgCCADKQAwNwAAIAhBB2ogA0E3aikAADcAACADQQE6ABQMAgsgCyAFQQF0aiAEOwEAIAMgBUEBajoAFQwBCyAKIARBlOLAABCoAQsgAUEQaiEBDAALAAvGAwEKfyMAQUBqIgMkAANAIARBCEZFBEAgA0EwaiAEakEEOwEAIARBAmohBAwBCwsgAyADKQMwNwEWIANBADsBFCADQRRqIgRBBGohCiADQTNqIQcgBEECciELIARBAXIhCANAAkACQCABIAJHBEBBBEEUQQMgAS8BBCIEQRRGGyAEQQRGGyIEQQNHDQEMAgsgACADKQIUNwIAIABBCGogA0EcaikCADcCACADQUBrJAAPCyADLQAURQRAIAMtABUiBUEETwRAIANBCGpBCEECQQJBtOHAABBPQQAhBSADQQA2AiwgAyADKAIMIgk2AiggAyADKAIIIgY2AiQgBkEDTQRAIANBJGpBAEEEQQJBAhCaASADKAIoIQkgAygCLCEFCyADQSRqIgZBCGoiDCAFQQRqNgIAIAkgBUEBdGogAykBFjcBACAGIARBxOHAABCoASAHQQhqIAwoAgA2AAAgByADKQIkNwAAIANBFGoQ0gEgCCADKQAwNwAAIAhBB2ogA0E3aikAADcAACADQQE6ABQMAgsgCyAFQQF0aiAEOwEAIAMgBUEBajoAFQwBCyAKIARB1OHAABCoAQsgAUEQaiEBDAALAAuxAwEKfyMAQRBrIgYkACAAKAIsIQMCQCAAKAI8IgFFDQAgACgCNCICIAFqIQEgBiADKAIAIANBCGooAgAgAiABIAEQTCAGKAIMIAYoAgghBCAAIAIgBigCBCAGKAIAIgVrIgFqNgI0IAMoAgQiCCAEQRxsaiECIAggBUEcbGohBQNAIAEEQCABQQFrIQEgBRDXASAFQRxqIQUMAQsLIABBADYCPCAEayEBA0AgAUUNASABQQFrIQEgAhDXASACQRxqIQIMAAsACyAAKAI4IgcgAygCDCICayEFIAAoAjAhCAJAIAJFDQAgAiAHRg0AAn8gAiAFTwRAIAMoAggiASACaiIJIAMoAgAiBEEAIAQgCU0bayEJIAIgCGogAWoiASAEQQAgASAETxtrIQogBQwBCyAIIAMoAggiCmoiASADKAIAIgRBACABIARPG2shCSACCyEBIAQgA0EEaigCACAKIAkgARAhCwJAIAdFBEAgA0EANgIIDAELIAIgBU8NACADIAMoAgggCGoiASADKAIAIgJBACABIAJPG2s2AggLIAMgBzYCDCAAENwBIAZBEGokAAuUAwEFfwJAIAJBEEkEQCAAIQMMAQsCQEEAIABrQQNxIgUgAGoiBCAATQ0AIAVBAWsgACEDIAUEQCAFIQYDQCADIAE6AAAgA0EBaiEDIAZBAWsiBg0ACwtBB0kNAANAIAMgAToAACADQQdqIAE6AAAgA0EGaiABOgAAIANBBWogAToAACADQQRqIAE6AAAgA0EDaiABOgAAIANBAmogAToAACADQQFqIAE6AAAgBCADQQhqIgNHDQALCyAEIAIgBWsiAkF8cWoiAyAESwRAIAFB/wFxQYGChAhsIQUDQCAEIAU2AgAgBEEEaiIEIANJDQALCyACQQNxIQILAkAgAiADaiIFIANNDQAgAkEBayACQQdxIgQEQANAIAMgAToAACADQQFqIQMgBEEBayIEDQALC0EHSQ0AA0AgAyABOgAAIANBB2ogAToAACADQQZqIAE6AAAgA0EFaiABOgAAIANBBGogAToAACADQQNqIAE6AAAg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AwJ/IAJBFGoiBCgCBARAIAQoAggiAUUEQEH4ycEALQAAGkEBIAMQGQwCCyAEKAIAIAFBASADEDwMAQtB+MnBAC0AABpBASADEBkLIQEgBSADNgIIIAUgAUEBIAEbNgIEIAUgAUU2AgAgAigCCEEBRgRAIAIoAhAaIAIoAgxBqInBABDnAQALIAIoAgwhASAAIAM2AgAgACABNgIEIAJBIGokAAvBAQEFfyMAQRBrIgIkAEEBIQQCQCABKAIcIgNBi4bAAEEFIAEoAiAiBigCDCIFEQMADQACQCABLQAUQQRxRQRAIANBou7AAEEBIAURAwANAiAAIAMgBhBTRQ0BDAILIANBo+7AAEECIAURAwANASACIAY2AgQgAiADNgIAIAJBAToADyACIAJBD2o2AgggACACQYTuwAAQUw0BIAJBoO7AAEECEB4NAQsgA0GWycEAQQEgBREDACEECyACQRBqJAAgBAunAQECfyMAQSBrIgIkACACIAAoAlw2AgwgAkEAOgAcIAIgACgCVCIDNgIQIAIgAyAAKAJYQQJ0ajYCFCACIAJBDGo2AhggAAJ/AkACQANAIAFBAWsiAQRAIAJBEGoQaw0BDAILCyACQRBqEGsiAQ0BCyAAKAKQASIDQQFrIgAMAQsgACgCkAEiA0EBayEAIAEoAgALIgEgACABIANJGzYCXCACQSBqJAALmAEBBn8jAEEQayICJAAgAiAAKAIAIAAoAgggACgCDBBqIAIoAgQgAigCACIDayEBIAIoAgwgACgCBCIGIAIoAggiBUEcbGohACAGIANBHGxqIQMDQCABBEAgAUEBayEBIAMQ1wEgA0EcaiEDDAELCyAFayEBA0AgAQRAIAFBAWshASAAENcBIABBHGohAAwBCwsgAkEQaiQAC58BAAJAAkAgAyAETQRAIAQgBUsNASADIARGBEAgAEIANwIAIABBCGpCADcCAA8LIAAgAiADaiICIAFBACABIAJNG2siAjYCACAEIANrIgMgASACayIESw0CIABCADcCCCAAIAIgA2o2AgQPCyADIARB+NPAABDrAQALIAQgBUH408AAEOoBAAsgAEEANgIIIAAgATYCBCAAIAMgBGs2AgwLnAEBBX8jAEEQayIDJAACf0EAIAEoAlwiBCABKAKQAU8NABogAUEkQQAgAS0AuAEbaiEFIAFBrgFqIQYgASgCYCEHIAEtALkBRQRAIANBCGogBSAEIAcgAiAGEC0gAygCDCECIAMoAggMAQsgAyAFIAQgByACIAYQQSADKAIEIQIgAygCAAshASAAIAI2AgQgACABNgIAIANBEGokAAvbAQEEfwJAAkAgASgCACIDQX9GDQAgAygCAEUNAEEBIQIgASgCBCIBIAAoAgAiBCgCAEkNACADIAMoAgQiAkEBajYCBCACQQBIDQEgASAEKAIAayEEIAAoAgQiACgCCCICIAAoAgAiBUYEQCMAQRBrIgEkACABQQhqIAAgBUEBQQRBCBA4IAEoAggiBUGBgICAeEcEQCABKAIMGiAFQezewAAQ5wEACyABQRBqJAALIAAgAkEBajYCCCAAKAIEIAJBA3RqIgAgBDYCBCAAIAM2AgBBACECCyACDwsAC4cBAgJ/AX4jAEEQayIFJAAgAiADakEBa0EAIAJrca0gAa1+IgenIQMCQCAHQiCIpw0AIANBgICAgHggAmtLDQACQCADRQRAQQAhAQwBCyAFQQhqIAIgAxC+ASACIQYgBSgCCCICRQ0BCyAAIAI2AgQgACABNgIAIAVBEGokAA8LIAYgBBDnAQALiwEBB38jAEEQayEEA0AgA0EQRkUEQEECIQcCQCABIANqIgVBBGoiCC0AACIGQQJGDQAgBSgCACIFIAJJDQAgCEECOgAAIAUgAmshCSAGIQcLIAMgBGoiBiAJNgIAIAZBBGogBzoAACADQQhqIQMMAQsLIAAgBCkCADcCACAAQQhqIARBCGopAgA3AgALfQEEfyAAKAIIIgQgASAAKAIMIgJrSwRAIAIgASAEayICayEDIAIgA0sgACgCACIFIAFrIANPcUUEQCAAKAIEIgMgBSACayIBQRxsaiADIARBHGxqIAJBHGwQExogACABNgIIDwsgACgCBCIAIAFBHGxqIAAgA0EcbBAXGgsLAwAAC6MBAQF/IwBBQGoiAyQAIANBCGogACgCABACIAMoAgghACADIAMoAgw2AgQgAyAANgIAIANBAjYCMCADQQI2AhggA0GYycEANgIUIANCATcCICADIAMoAgQiADYCPCADIAMoAgA2AjggAyAANgI0IAMgA0E0ajYCLCADIANBLGo2AhwgASACIANBFGoQHCADKAI0IAMoAjhBAUEBEHggA0FAayQAC3oBAn8C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CCEFIAEgBRDkAQsgBEEQaiQAC1gBAn8gASgCACIEIAAoAgAiAGohA0EAIQECQCAAIAIoAgQiAE0gACADSXENACAAIANPBEAgAiAAIARrNgIECyACKAIAIgBBf0YNACAAKAIAQQBHIQELIAELWQEEfyAAKAIAIQECQCAAKAIIIgJFBEAgACgCDCEADAELIAEoAgQiBCAAKAIEIgMgAmtBA3RqIAQgA0EDdGogACgCDCIAIANrQQN0EBMaCyABIAAgAms2AggLWwECfyABEOABIAFBCGsiAygCAEEBaiECIAMgAjYCAAJAIAIEQCABKAIAIgJBf0YNASAAIAM2AgggACABNgIEIAAgAUEEajYCACABIAJBAWo2AgAPCwALEPABAAtJAQF/AkAgACgCAEEgRw0AIAAtAA4NACAALQAEQQJHDQAgAC0ACEECRw0AIAAtAAwNACAALQANIgBBD3ENACAAQRBxRSEBCyABC1sBAX8jAEEwayIDJAAgAyABNgIMIAMgADYCCCADQQE2AhQgA0HQ7MAANgIQIANCATcCHCADIANBCGqtQoCAgICAAYQ3AyggAyADQShqNgIYIANBEGogAhC8AQALTgEEfwJAAkACQCAALQAAIgRBA2sOAgABAgsgAC0AASEDDAELIAAtAAJBEHQhASAALQADQRh0IQIgAC0AASEDCyABIAJyIANBCHRyIARyC1QBAX8gACgCYCICIAAoAqgBRwRAIAAoApQBQQFrIAJLBEAgACACQQFqNgJgIAAgACgCkAFBAWsiASAAKAJcIgAgACABSxs2AlwLDwsgAEEBIAEQdAtMAQJ/IAJBAnQhAhAAIQQDQCACBEAgBCADIAEoAgBBABDOARABIAJBBGshAiADQQFqIQMgAUEEaiEBDAELCyAAIAQ2AgQgAEEANgIAC1MBAn8CQCABKAIAIgNBf0YNACADKAIARQ0AQQEhAiABKAIEIgEgACgCACgCAEkNAEEAIQIgASAAKAIEKAIAIgFJDQAgASAAKAIIKAIARyECCyACC1ABAn8gACgCDCIDIAFqIQQgAyAETQRAIAQgACgCACICSwRAIAEgAiADa0sEQCAAIAMgAUEEQRwQmgELIAAgAhBRCw8LQfDLwABBESACEH0AC1EBAn8gACAAKAKQAUEBayICIAAoAlwiAyACIANJGzYCXCAAIAEgACgCYCIBaiICIAAoApQBQQFrIAAoAqgBIgAgACABSRsiACAAIAJLGzYCYAtTAQJ/IAEQ4AEgAUEIayICKAIAQQFqIQMgAiADNgIAAkAgAwRAIAEoAgANASAAIAI2AgggACABNgIEIAFBfzYCACAAIAFBBGo2AgAPCwALEPABAAtMAQJ/IAFBBHQhAiAAQRBrIQMgAUH/////AHEhAEEAIQEDQAJAIAIEfyACIANqEHwNASABBSAACw8LIAJBEGshAiABQQFqIQEMAAsAC0sBBH8gACgCECEBIAAoAhQhAwJAA0BBACECIAFFDQEgASADRg0BIAAgAUEIaiICNgIQIAEtAAQgAiEBQQJGDQALIAFBCGshAgsgAgtJAQN/AkAgACgCXCICRQ0AIAAgAkEBayIDNgJcIAAgARBeIANFDQANACAAIAJBAms2AlwgACABEF4aCyAAIAAoApABQQFrNgJcC1UBAn8gACgCBCICIAAoAgAiATYCACABBEAgASACNgIEC0G4ycEAKAIAIAAoAggiAEECdGooAgBFBEBBsMnBAEGwycEAKQMAQgEgAEE/ca2GhTcDAAsLUAEBfwJAIAEoAgQiAiAAKAIAKAIASwRAIAEgACgCBCgCACACaiICNgIEIAIgACgCCCgCAE8NAQsgASgCACIAQX9GDQAgACgCAEEARw8LQQALQwEDfwJAIAJFDQADQCAALQAAIgQgAS0AACIFRgRAIABBAWohACABQQFqIQEgAkEBayICDQEMAgsLIAQgBWshAwsgAwtLAQN/IAEoAgAgASgCBCECIABBDGogASgCCCIBEMEBIAAoAhAgACgCFCIEQQN0aiACIAFBA3QQFxogACABIARqNgIUIAJBBEEIEHMLSgECfyAAIAAoApABQQFrIgIgACgCXCIDIAIgA0kbNgJcIAAgACgCpAEiAkEAIAAoAmAiACACTxsiAiAAIAFrIgAgACACSBs2AmALUAEBfwJAAn8gAS0AAEUEQCABLQABIgJBBU8NAiABQQJqDAELIAEoAgwhAiABKAIICyEBIAAgAjYCBCAAIAE2AgAPCyACQQRBpOHAABDqAQALUAEBfwJAAn8gAS0AAEUEQCABLQABIgJBBU8NAiABQQJqDAELIAEoAgwhAiABKAIICyEBIAAgAjYCBCAAIAE2AgAPCyACQQRB5OHAABDq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Cy0BAX8gASAAKAIATwR/IAAoAgQhAiAALQAIRQRAIAEgAk0PCyABIAJJBUEACwtwAQN/IAAoAgAiBCAAKAIIIgVGBEAjAEEQayIDJAAgA0EIaiAAIARBAUECQQgQPSADKAIIIgRBgYCAgHhHBEAgAygCDBogBCACEOcBAAsgA0EQaiQACyAAIAVBAWo2AgggACgCBCAFQQN0aiABNwEAC3ABA38gACgCACIEIAAoAggiBUYEQCMAQRBrIgMkACADQQhqIAAgBEEBQQJBAhA4IAMoAggiBEGBgICAeEcEQCADKAIMGiAEIAIQ5wEACyADQRBqJAALIAAgBUEBajYCCCAAKAIEIAVBAXRqIAE7AQALNAAgACAAKAJcIAFqIgE2AlwCQCABIAAoApABRw0AIAAtALsBQQFGDQAgACABQQFrNgJcCws3AQF/IwBBIGsiASQAIAFBADYCGCABQQE2AgwgAUGc8MAANgIIIAFCBDcCECABQQhqIAAQvAEACysAIAIgA0kEQCADIAIgBBDpAQALIAAgAiADazYCBCAAIAEgA0EEdGo2AgALJQAgAEGBAk8EQCAAQR4gAGciAGt2IABBAXRrQTxqDwsgAEEEdgsvAAJAIAFFDQAgAC0ABEEBcQ0AIAAoAgAgAUcNACAAQQE6AAQgACABQQFrNgIACwsvAQF/IAAgAhDAASAAKAIEIAAoAggiA0EEdGogASACQQR0EBcaIAAgAiADajYCCAsrACABIANLBEAgASADIAQQ6QEACyAAIAMgAWs2AgQgACACIAFBBHRqNgIACy8AAkACQCADaUEBRw0AQYCAgIB4IANrIAFJDQAgACABIAMgAhA8IgANAQsACyAACyoAIAAgACgCXCABaiIBIAAoApABIgBBAWsgACABSxtBACABQQBOGzYCXAsyAQF/IAAoAgghAiABIAAoAgBBAmotAAAQzgEhASAAKAIEIAIgARABIAAgAkEBajYCCAstACABIAJJBEBBvNDAAEEhQeDQwAAQnAEACyABIAJrIgEgACABQRxsaiACEBULKAAgASADSwRAQQlBCCAEEOkBAAsgACADIAFrNgIEIAAgASACajYCAAstACACIAAoAhxJBEAgACACQQFrQaDXwAAQtgFBADoAGAsgACABIAIgAyAEECALLAAgAEEIaiAAKAIUIAFqIAAoAhxrEJ0BIgBFBEBB3MvAAEEUIAIQfQALIAALKwAgASACSQRAQZTPwABBI0Gs0MAAEJwBAAsgAiAAIAJBBHRqIAEgAmsQGAsoACABIANLBEAgASADIAQQ6QEACyAAIAMgAWs2AgQgACABIAJqNgIACysAIAEgAkkEQEGUz8AAQSNBrNDAABCcAQALIAIgACACQRxsaiABIAJrEBULKgEBfwJAIABBf0YNACAAIAAoAgQiAUEBazYCBCABQQFHDQAgAEEIEGILCysAIABBCGogACgCFCACaiAAKAIcayADEJsBIgAoAgQgACgCCCABIAMQwgEL7AECAn8BfiMAQRBrIgIkACACQQE7AQwgAiABNgIIIAIgADYCBCMAQRBrIgEkACACQQRqIgApAgAhBCABIAA2AgwgASAENwIEIwBBEGsiACQAIAFBBGoiASgCACICKAIMIQMCQAJAAkACQCACKAIEDgIAAQILIAMNAUEBIQJBACEDDAILIAMNACACKAIAIgIoAgQhAyACKAIAIQIMAQsgAEGAgICAeDYCACAAIAE2AgwgASgCCCIBLQAJGiAAQRcgAS0ACBBtAAsgACADNgIEIAAgAjYCACABKAIIIgEtAAkaIABBGCABLQAIEG0ACyIAA0AgAQRAIAAoAgAQugEgAUEBayEBIABBCGohAAwBCwsLJgAgAgRAQfjJwQAtAAAaIAEgAhAZIQELIAAgAjYCBCAAIAE2AgALLgEBfyABIAJBgNbAABC2AUEBOgAYIAEoAhghAyAAIAEgAkGQ1sAAELYBIAMQNwskAQF/IAEgACgCACAAKAIIIgJrSwRAIAAgAiABQQRBEBCaAQsLJAEBfyABIAAoAgAgACgCCCICa0sEQCAAIAIgAUEEQQgQmgELCxsAIAEgAk0EQCACIAEgAxBvAAsgACACQQR0agswAQF/IAAoAgAgACgCBEEEQRAQcyAAKAIQIgEgACgCFBC9ASAAKAIMIAFBBEEIEHMLAwAACyIAIAAtALgBQQFGBEAgAEEAOgC4ASABQQAgACgClAEQbgsLGQEBfyABIANGBH8gACACIAEQigEFQQELRQsDAAALAwAACwMAAAsDAAALAwAACxoAQfjJwQAtAAAaQQQgABAZIgAEQCAADwsACwMAAAsWACABQQFxRQRAIAC4EAkPCyAArRAKC0QBAX8gACAAKAIA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AFUAAABWAAAAVwAAAFgAAABZAAAAWgAAAFsAAABcAAAAXQAAAF4AAABfAAAAZiYAAJIlAAAJJAAADCQAAA0kAAAKJAAAsAAAALEAAAAkJAAACyQAABglAAAQJQAADCUAABQlAAA8JQAAuiMAALsjAAAAJQAAvCMAAL0jAAAcJQAAJCUAADQlAAAsJQAAAiUAAGQiAABlIgAAwAMAAGAiAACjAAAAxSIAAH8AAAAZAAAADAAAAAQAAAAaAAAAGwAAABwAQYCFwAALkAEBAAAAHQAAAGEgRGlzcGxheSBpbXBsZW1lbnRhdGlvbiByZXR1cm5lZCBhbiBlcnJvciB1bmV4cGVjdGVkbHkAOEQQAHAAAADfCgAADgAAAB4AAAAEAAAABAAAAB8AAABjYWxsZWQgYFJlc3VsdDo6dW53cmFwKClgIG9uIGFuIGBFcnJgIHZhbHVlRXJyb3IAQY+PwAALAXgAQbCPwAALEP////////////////////8AQdaPwAALEgEAAAAAACAAAAAAAAAAAgAAAgBBkJDAAAsg//////////////////////////////////////////8AQfSQwAALCBAAAAAAAAABAEGQvsAACwL/BwBBpL7AAAsHDwD////1/wBB0L7AAAsW////////////////////////////AwBB8L7AAAsd/////////////////////////////////////w8AQc+/wAALGPz//////////////////////////////wBB8L/AAAs+//////////////////////////////////////////////////////////////////////////////////8AQdzAwAALOP////////////////////////////////////////////////////////////////////////9/AEGwwcAAC9EB/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////wMAQZDDwAALJ///////////////////////////////////////////////////DwBBkMbAAAvDQ3NyYy9saWIucnMAAAEADwDwGg8AAAAAAOIlAADlJQAAAAAAALDgAAC/4AAAAAAAADz7AQBp+wEAAAAAAGr7AQBs+wEAAAAAAIAlAACfJQAAAAAAAAD7AQA7+wEAAAAAAGF0dGVtcHRlZCB0byB0YWtlIG93bmVyc2hpcCBvZiBSdXN0IHZhbHVlIHdoaWxlIGl0IHdhcyBib3Jyb3dlZGJndGV4dGNvZGVwb2ludHNyYXN0ZXJfc3ltYm9sc3ZlY3Rvcl9zeW1ib2xzABAjEAAKAAAAaQAAABMAAAAQIxAACgAAAGoAAAAVAAAAECMQAAoAAABrAAAAGQAAABAjEAAKAAAAbAAAABkAAAAQIxAACgAAAG0AAAAVAAAAECMQAAoAAAB2AAAALQAAABAjEAAKAAAAfAAAAC0AAAAQIxAACgAAAKAAAAAOAAAAECMQAAoAAAAKAQAAGwAAABAjEAAKAAAADgEAAB0AAAAQIxAACgAAACUBAAAtAAAAECMQAAoAAAC7AAAAIwAAABAjEAAKAAAAxQAAACMAAAAQIxAACgAAANoAAAAlAAAAECMQAAoAAADSAAAAJQAAABAjEAAKAAAA/wAAACkAAAAQIxAACgAAAOYAAAAlAAAAECMQAAoAAADqAAAAFgAAABAjEAAKAAAABQEAAB0AAAAQIxAACgAAACwBAAAvAAAA8CUQABEAAAApIHNob3VsZCBiZSA8IGxlbiAoaXMgaW5zZXJ0aW9uIGluZGV4IChpcyApIHNob3VsZCBiZSA8PSBsZW4gKGlzIAAAADolEAAUAAAATiUQABcAAACWZBAAAQAAAHJlbW92YWwgaW5kZXggKGlzIAAAgCUQABIAAAAkJRAAFgAAAJZkEAABAAAAYGF0YCBzcGxpdCBpbmRleCAoaXMgAAAArCUQABUAAABOJRAAFwAAAJZkEAABAAAAT3V0IG9mIGJvdW5kcyBhY2Nlc3NjYXBhY2l0eSBvdmVyZmxvdy9ob21lL3J1bm5lci8uY2FyZ28vcmVnaXN0cnkvc3JjL2luZGV4LmNyYXRlcy5pby0xOTQ5Y2Y4YzZiNWI1NTdmL3VuaWNvZGUtd2lkdGgtMC4yLjIvc3JjL3RhYmxlcy5ycwEmEABjAAAAuAAAABUAAAABJhAAYwAAAL4AAAAZAAAAL25peC9zdG9yZS80MWptNGI5emZ2a3FqbG0xbmtwZDZhemtxaGZqMmFrNS1ydXN0LWRlZmF1bHQtMS44Ni4wL2xpYi9ydXN0bGliL3NyYy9ydXN0L2xpYnJhcnkvY29yZS9zcmMvc3RyL21vZC5yc4QmEABwAAAAOAMAABUAAAAvbml4L3N0b3JlLzQxam00Yjl6ZnZrcWpsbTFua3BkNmF6a3FoZmoyYWs1LXJ1c3QtZGVmYXVsdC0xLjg2LjAvbGliL3J1c3RsaWIvc3JjL3J1c3QvbGlicmFyeS9jb3JlL3NyYy9pdGVyL3RyYWl0cy9pdGVyYXRvci5ycwAAAAQnEAB9AAAAswcAAAkAAABhc3NlcnRpb24gZmFpbGVkOiBtaWQgPD0gc2VsZi5sZW4oKS9uaXgvc3RvcmUvNDFqbTRiOXpmdmtxamxtMW5rcGQ2YXprcWhmajJhazUtcnVzdC1kZWZhdWx0LTEuODYuMC9saWIvcnVzdGxpYi9zcmMvcnVzdC9saWJyYXJ5L2NvcmUvc3JjL3NsaWNlL21vZC5ycwAAALcnEAByAAAArA0AAAkAAABhc3NlcnRpb24gZmFpbGVkOiBrIDw9IHNlbGYubGVuKCkAAAC3JxAAcgAAANkNAAAJAAAAtycQAHIAAAA5CgAAIgAAAC9uaXgvc3RvcmUvNDFqbTRiOXpmdmtxamxtMW5rcGQ2YXprcWhmajJhazUtcnVzdC1kZWZhdWx0LTEuODYuMC9saWIvcnVzdGxpYi9zcmMvcnVzdC9saWJyYXJ5L2FsbG9jL3NyYy9zbGljZS5ycwCAKBAAbwAAAKIAAAAZAAAAL25peC9zdG9yZS80MWptNGI5emZ2a3FqbG0xbmtwZDZhemtxaGZqMmFrNS1ydXN0LWRlZmF1bHQtMS44Ni4wL2xpYi9ydXN0bGliL3NyYy9ydXN0L2xpYnJhcnkvY29yZS9zcmMvc3RyL3BhdHRlcm4ucnMvbml4L3N0b3JlLzQxam00Yjl6ZnZrcWpsbTFua3BkNmF6a3FoZmoyYWs1LXJ1c3QtZGVmYXVsdC0xLjg2LjAvbGliL3J1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CAgICAgIAEGBjcEAC98KAQICAgIDAgIEAgUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0CAh4CAgICAgICHyAhIiMCJCUmJygpAioCAgICKywCAgICLS4CAgIvMDEyMwICAgICAjQCAjU2NwI4OTo7PD0+Pzk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTlAAgJBQgICQ0RFRkdIAkk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTlKAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICOTk5OUsCAgICAkxNTk8CAgJQAlFSAgICAgICAgICAgICAlNUAgJVAlYCAldYWVpbXF1eX2BhYmMCZGVmZwJoAmlqa2xtAm5vcHECcnMCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAnQCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAnUCAgICAgICAgICAgICAgICAgJ2dwICAngCAgJ5ejk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OXt8fQICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgJ+OTl/OTmAAgICAgICAgICAgICAgICAgICAoECAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgKCAgICg4SFAoYCAgICAgICAgICAgICh4gCAgICAgICAgICiYp3AgKLAgICjAKNAo4CAgKPkAICAgICAgICAgICAgKRkgKTlAKVlpeYmZqbnAKdAgKen6ChAgICAgICAgICAjk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OaIdHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHQICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKMCAgICpKUCBAIFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdAgIeAgICAgICAh8gISIjAiQlJicoKQIqAgICAqanqKmqq6wurTmur7CxsrMCAgICAgK0AgI1NjcCODk6Ozw9PrU5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTlLAgICAgK2TU63iYp3AgKLAgICjAKNAo4CAgKPkAICAgICAgICAgICAgKRkri5lAKVlpeYmZqbnAKdAgKen6ChAgICAgICAgICAlVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQBB/JfBAAspVVVVVRUAUFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQEAQa+YwQALxAEQQRBVVVVVVVdVVVVVVVVVVVVRVVUAAEBU9d1VVVVVVVVVVRUAAAAAAFVVVVX8XVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBQAUABQEUFVVVVVVVVUVUVVVVVVVVVUAAAAAAABAVVVVVVVVVVVV1VdVVVVVVVVVVVVVVQUAAFRVVVVVVVVVVVVVVVVVFQAAVVVRVVVVVVUFEAAAAQFQVVVVVVVVVVVVVQFVVVVVVf////9/VVVVUBUAAFVVVVVVVVVVVVUFAEGAmsEAC5gEQFVVVVVVVVVVVVVVVVVFVAEAVFEBAFVVBVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVEAVRVUVUVVVUFVVVVVVVVRUFVVVVVVVVVVVVVVVVVVVRBFRRQUVVVVVVVVVVQUVVVQVVVVVVVVVVVVVVVVVVVVAEQVFFVVVVVBVVVVVVVBQBRVVVVVVVVVVVVVVVVVVUEAVRVUVUBVVUFVVVVVVVVVUVVVVVVVVVVVVVVVVVVVUVUVVVRVRVVVVVVVVVVVVVVVFRVVVVVVVVVVVVVVVVVBFQFBFBVQVVVBVVVVVVVVVVRVVVVVVVVVVVVVVVVVVUURAUEUFVBVVUFVVVVVVVVVVBVVVVVVVVVVVVVVVVVFUQBVFVBVRVVVQVVVVVVVVVVUVVVVVVVVVVVVVVVVVVVVVVVRRUFRFUVVVVVVVVVVVVVVVVVVVVVVVVVVVVRAEBVVRUAQFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVEAAFRVVQBAVVVVVVVVVVVVVVVVVVVVVVVVUFVVVVVVVRFRVVVVVVVVVVVVVVVVVQEAAEAABFUBAAABAAAAAAAAAABUVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAQQAQUFVVVVVVVVQBVRVVVUBVFVVRUFVUVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqoAQcCewQAL7AFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQFVVVVVVVVVVVVVVVUFUFVVVVVVVQVUVVVVVVVVBVVVVVVVVVUFVVVVf//99//911931tXXVRAAUFVFAQAAVVdRVVVVVVVVVVVVVRUAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAFVRVRVUBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVxUUVVVVVVVVVVVVVVVVVVVFAEBEAQBUFQAAFFVVVVVVVVVVVVVVVQBBt6DBAAuZAVAAAABVVVVVVQBVVVVVVVVVVVVVVVUAAFAFVFVVVVVVVVVVFQAAVVVVUFVVVVVVVVUFUABQVVVVVVVVVVVVVVVVVUVQEQBVVVVVVVVVVVVVVVVVVQAABVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAAAAAQAVFFVVFBVVVVVVVVVVVVVVVVVVVVVVQBB4KHBAAvzB1VVFQBVVVVVVVUFQFVVVVVVVVVVVVVVVQAAAABVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAAAAAAAAAAFRVVVVVVVVVVVX1VVVVaVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV/VfXVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX1VVVVVVV9VVVVVVVWqqlVVVVX///9VVVVVVVVVVVVV1VVVparVVVVVXVX1VVVVVX1VX1V1VVdVVVVVdVX1XXVdVV31VVVVVVVVVVdVVVVVVVVVVXfV31VVVVVVVVVVVVVVVVVVVf1VVVVVVVVXVVXVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVdVXVVVVVVVVVVVVVVVVV11VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVBVVVVVVVVVVVVVVVVVVVX9////////////////X1XVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAAAAAAAAAAqqqqqqqqmqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpVVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqlpVVVVVVVWqqqqqqqqqqqqqqqqqqgoAqqqqaqmqqqqqqqqqqqqqqqqqqqqqqqqqqmqBqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqlWpqqqqqqqqqqqqqqmqqqqqqqqqqqqqqqqoqqqqqqqqqqqqaqqqqqqqqqqqqqqqqqqqqqqqqqqqqlpVlaqqqqqqqqqqqqqqaqqqqqqqqqqqqqpVVaqqqqqqqqqqqqqqqqqqqlaqqqqqqqqqqqqqqqqqalVVVVVVVVVVVVVVVVVfVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFUAAAFBVVVVVVVVVBVVVVVVVVVVVVVVVVVVVVVVVVVVVUFVVVUVFFVVVVVVVVUFVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVAAAAAFBVRRVVVVVVVVVVVVUFAFBVVVVVVRUAABBVVVWqqqqqqqqqVkBVVVVVVVVVVVVVVRUFUFBUVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVQFAQUFVVRVVVVRVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVUEFFQFUVVVVVVVVVVVVVVQVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVFFVVVVVqqqqqqqqqqqqVVVVAAAAAABAFQBB36nBAAvhDVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQwAAPCqqlpVAAAAAKqqqqqqqqqqaqqqqqpqqlVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRWpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpWVVVVVVVVVVVVVVVVVVUFVFVVVVVVVVVVVVVVVVVVVapqVVUAAFRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBUBVAUFVAFVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVUBUFVVVVVVVVVVVVVVVVVVFVRVVVVVVVVVVVVVVVVVVVVVVVUFAFVVVVVVVVVVVVVVVVVVVVVVBQAAVFVVVVVVVVVVVVVVBVBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVQAAAEBVVVVVVVVVVVVVFFRVFVBVVVVVVVVVVVVVVRVAQVVFVVVVVVVVVVVVVVVVVVVVQFVVVVVVVVVVFQABAFRVVVVVVVVVVVVVVVVVVRVVVVVQVVVVVVVVVVVVVVVVBQBABFUBFFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVAAVUVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVFQBAVVVVVVVQVVVVVVVVVVVVVVVVVRVEVFVVUVUVVVVVBQBUAFRVVVVVVVVVVVVVVVVVVVVVFABEEVAFQFVVVUFVVVVVVVVVVVVVVVVVVVVVVVVVVVUAAAVEVVVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVUUAEQRBFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFQVQVRBUVVVVVVVVUFVVVVVVVVVVVVVVVVVVVVVVVVVVFQBAEVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVEAAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVURBRAAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVAABBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVRUAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAFVVRVVVVVVVVVAQBAVVVVVVVVVVVVFQAUQFUVVVUBQAFVVVVVVVVVVVVVAAAAAEBQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQREVVVVVVVVVVVVVVVVVVVVVVVVAEAAEFVVVVVVVVVVVVVVVVVVVVVVVVVVBQAAAAAABQAEQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQFARRAAAFVVVVVVVVVVVVVVVVVVVVVVVVARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVRVVUBVVVVVVVVVVVVVVVUFQFVAVVVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVAAAAUFVVVVVVVVVVVVVVVVVVVVVVBQAAUAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAVFVVVVVVVVVVVVVVVVVVAEBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV1VdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVVVVVVVVVVVVVVVVVVVVVFUBVVVVVVVVVVVVVVVVVVVVVVVVVqlRVVaBqVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqpaVVVVVVVVVVVVlaqqqqqqqqpqVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqmpVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVqqmqaaqqqqqqqqqqalVVVWVVVVVVVVVVallVVVWqVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqlVVVVVVVVVVQQBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQBBy7fBAAuVAVAAAAAAAEBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUBUAEAAAAAQAEAVVVVVVVVVQVQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBVRVVVVVVVVVVVVVVVVVVaqqqqqqqqqqqqqqqqqqqqqqqqqqqmpVVaqqqqqqalVVAEHtuMEACwJAFQBB+7jBAAuFB1RVUVVVVVRVVVVVFQABAAAAVVVVVVVVVVVVVVVVVVVVVVVVVVUAQAAAAAAUABAEQFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVVVVVVVVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFUVVBVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQBAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAEBVVVVVVVVVVVVVVVVVVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV1VVVVVVVVVVVVVVVVVVVVXX9/39VVVVVVVVVVVVVVVVVVVVVVVX1////////blVVVaqquqqqqqrq+r+/VaqqVlVfVVVVqlpVVVVVVVX//////////1dVVf3/3///////////////////////9///////VVVV/////////////3/V/1VVVf////9XV///////////////////////f/f/////////////////////////////////////////////////////////////1////////////////////19VVdV/////////VVVVVXVVVVVVVVV9VVVVV1VVVVVVVVVVVVVVVVVVVVVVVVVV1f///////////////////////////1VVVVVVVVVVVVVVVf//////////////////////X1VXf/1X/1VV1VdV//9XVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV////VVdVVVVVVVX//////////////3///9//////////////////////////////////////////////////////////////VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf///1f//3/1/////////////////39X/f///9f//3/V//9XVaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpaVVVVVVVVVVVZllVhqqVZqlVVVVVVlVVVVVVVVVWVVVUAQY7AwQALAQMAQZzAwQALiQlVVVVVVZVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRUAlmpaWmqqBUCmWZVlVVVVVVVVVVUAAAAAVVZVValWVVVVVVVVVVVVVlVVVVVVVVVVAAAAAAAAAABUVVVVlVlZVVVlVVVpVVVVVVVVVVVVVVWqqqpqqqqqVaqqWlVVVVlVqqqqVVVVVWVVVVpVVVVVpWVWVVVVlVVVVVVVVaaWmpZZWWWplqqqZlWqVVpZVVpWZVVVVWqqpaVaVVVVpapaVVVZWVVVWVVVVVVVlVVVVVVVVVVVVVVVVVVVVVVVVVVVZVX1VVVVaVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqlWqqqqqqqqqqqpWVVWqqqqqpVpVVZqqWlWlpVVaWqWWpVpVVVWlWlWVVVVVfVVpWaVVr1VmVVVVVaqqVVVmVf///1VVVZqaappVVVXVVVWlqtVVVaVdVfVVVVVVvVWvqrqqq6qqmlW6qvquuq5VXfVVVVVVVVVVV1VVVVVZVVVVd9XfVVVVVVVVVaWqqqqqqqqq/VVVVVVVVVdVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV1VdVVVVVVVVVVVVVVVVXrVpVVVVVVVVVVVWqqqqqqqqqaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqjMAAMCqqlpVAAAAAKqqqqqqqqqqaqqqqqpqqlVVVVVVVVVVVVVVVQVUVVVVVVVVVVVVVVVVVVVVqmpVVQAAVFmqqqpWqqqqqqqqqlqqqqqqqqqqqqqqqqqqqlpVqqqqqqqqqrr+/7+qqqqqVlVVVVVVVVVVVVVVVVX1////////L25peC9zdG9yZS80MWptNGI5emZ2a3FqbG0xbmtwZDZhemtxaGZqMmFrNS1ydXN0LWRlZmF1bHQtMS44Ni4wL2xpYi9ydXN0bGliL3NyYy9ydXN0L2xpYnJhcnkvYWxsb2Mvc3JjL3Jhd192ZWMucnMvaG9tZS9ydW5uZXIvLmNhcmdvL3JlZ2lzdHJ5L3NyYy9pbmRleC5jcmF0ZXMuaW8tMTk0OWNmOGM2YjViNTU3Zi93YXNtLWJpbmRnZW4tMC4yLjEwNi9zcmMvY29udmVydC9zbGljZXMucnMvaG9tZS9ydW5uZXIvLmNhcmdvL3JlZ2lzdHJ5L3NyYy9pbmRleC5jcmF0ZXMuaW8tMTk0OWNmOGM2YjViNTU3Zi93YXNtLWJpbmRnZW4tMC4yLjEwNi9zcmMvZXh0ZXJucmVmLnJznWMQAGcAAAB/AAAAEQAAAJ1jEABnAAAAjAAAABEAAABudWxsIHBvaW50ZXIgcGFzc2VkIHRvIHJ1c3RyZWN1cnNpdmUgdXNlIG9mIGFuIG9iamVjdCBkZXRlY3RlZCB3aGljaCB3b3VsZCBsZWFkIHRvIHVuc2FmZSBhbGlhc2luZyBpbiBydXN0SnNWYWx1ZSgpAI5kEAAIAAAAlmQQAAEAQajJwQALAQQASAlwcm9kdWNlcnMBDHByb2Nlc3NlZC1ieQIGd2FscnVzBjAuMjQuNAx3YXNtLWJpbmRnZW4TMC4yLjEwNiAoMTE4MzFmYjg5KQ==");
async function init(options) {
	await __wbg_init({
		module_or_path: await options.module,
		memory: options.memory
	});
	return exports$1;
}
var vt = init({ module: vtWasmModule });
var memory = vt.then((wasm) => wasm.default()).then((d) => d.memory);
var Vt = class Vt {
	static async build(cols, rows, boldIsBright, logger) {
		return new Vt(await vt, await memory, logger, cols, rows, boldIsBright);
	}
	constructor(wasm, memory, logger, cols, rows, boldIsBright) {
		this.wasm = wasm;
		this.memory = memory;
		this.logger = logger;
		this.cols = cols;
		this.rows = rows;
		this.boldIsBright = boldIsBright;
		this.vt = wasm.create(cols, rows, 100, boldIsBright);
	}
	feed(data) {
		return this.vt.feed(data);
	}
	reset(cols, rows, init = void 0) {
		this.logger.debug(`vt: reset (${cols}x${rows})`);
		this.vt = this.wasm.create(cols, rows, 100, this.boldIsBright);
		this.cols = cols;
		this.rows = rows;
		if (init !== void 0 && init !== "") this.vt.feed(init);
		return Array.from({ length: rows }, (_, i) => i);
	}
	resize(cols, rows) {
		if (cols === this.cols && rows === this.rows) return;
		this.logger.debug(`vt: resize (${cols}x${rows})`);
		const changedRows = this.vt.resize(cols, rows);
		this.cols = cols;
		this.rows = rows;
		return changedRows;
	}
	getLine(n, cursorOn) {
		return this.vt.getLine(n, cursorOn);
	}
	getDataView([ptr, len], size) {
		return new DataView(this.memory.buffer, ptr, len * size);
	}
	getUint32Array([ptr, len]) {
		return new Uint32Array(this.memory.buffer, ptr, len);
	}
	getCursor() {
		const cursor = this.vt.getCursor();
		if (cursor) return {
			col: cursor[0],
			row: cursor[1],
			visible: true
		};
		return {
			col: 0,
			row: 0,
			visible: false
		};
	}
};
var _tmpl$$f = /*#__PURE__*/ template(`<div class=ap-term><canvas></canvas><svg class=ap-term-symbols xmlns=http://www.w3.org/2000/svg preserveAspectRatio=none width=100% height=100% aria-hidden=true><defs></defs><g></g></svg><pre class=ap-term-text aria-live=off tabindex=0>`);
var SVG_NS = "http://www.w3.org/2000/svg";
var BLOCK_H_RES = 8;
var BLOCK_V_RES = 24;
var BOLD_MASK = 1;
var FAINT_MASK = 2;
var ITALIC_MASK = 4;
var UNDERLINE_MASK = 8;
var STRIKETHROUGH_MASK = 16;
var BLINK_MASK = 32;
var Terminal = (props) => {
	const core = props.core;
	const textRowPool = [];
	const vectorSymbolRowPool = [];
	const vectorSymbolUsePool = [];
	const vectorSymbolDefCache = /* @__PURE__ */ new Set();
	const colorsCache = /* @__PURE__ */ new Map();
	const attrClassCache = /* @__PURE__ */ new Map();
	const vtReady = Vt.build(props.cols, props.rows, props.boldIsBright, props.logger);
	let vt;
	const [size, setSize] = createSignal({
		cols: props.cols,
		rows: props.rows
	}, { equals: (newVal, oldVal) => newVal.cols === oldVal.cols && newVal.rows === oldVal.rows });
	const [theme, setTheme] = createSignal(buildTheme(FALLBACK_THEME, props.adaptivePalette));
	const lineHeight = () => props.lineHeight ?? 1.3333333333;
	const [blinkOn, setBlinkOn] = createSignal(true);
	const cursorOn = createMemo(() => {
		if (props.cursorMode === "hidden") return false;
		if (props.cursorMode === "steady") return true;
		return blinkOn() || cursorHold;
	});
	const style$1 = createMemo(() => {
		return {
			width: `${size().cols}ch`,
			height: `${lineHeight() * size().rows}em`,
			"font-size": `${(props.scale || 1) * 100}%`,
			"--term-line-height": `${lineHeight()}em`,
			"--term-cols": size().cols,
			"--term-rows": size().rows
		};
	});
	let cursor = {
		col: 0,
		row: 0,
		visible: false
	};
	let pendingChanges = {
		size: void 0,
		theme: void 0,
		rows: /* @__PURE__ */ new Set()
	};
	let el;
	let canvasEl;
	let canvasCtx;
	let textEl;
	let vectorSymbolsEl;
	let vectorSymbolDefsEl;
	let vectorSymbolRowsEl;
	let frameRequestId;
	let blinkIntervalId;
	let cssTheme;
	let cursorHold = false;
	onMount(() => {
		setupCanvas();
		setInitialTheme();
		adjustTextRowNodeCount(size().rows);
		adjustSymbolRowNodeCount(size().rows);
		vtReady.then((vt_) => {
			vt = vt_;
			core.addEventListener("reset", onVtReset);
			core.addEventListener("resize", onVtResize);
			core.addEventListener("output", onVtOutput);
			props.onReady?.();
		});
	});
	onCleanup(() => {
		core.removeEventListener("reset", onVtReset);
		core.removeEventListener("resize", onVtResize);
		core.removeEventListener("output", onVtOutput);
		clearInterval(blinkIntervalId);
		cancelAnimationFrame(frameRequestId);
	});
	createEffect(() => {
		if (props.blinking && blinkIntervalId === void 0) blinkIntervalId = setInterval(toggleBlink, 600);
		else {
			clearInterval(blinkIntervalId);
			blinkIntervalId = void 0;
			setBlinkOn(true);
		}
	});
	createEffect(() => {
		cursorOn();
		if (cursor.visible) {
			pendingChanges.rows.add(cursor.row);
			scheduleRender();
		}
	});
	function setupCanvas() {
		canvasCtx = canvasEl.getContext("2d");
		if (!canvasCtx) throw new Error("2D ctx not available");
		const { cols, rows } = size();
		canvasEl.width = cols * BLOCK_H_RES;
		canvasEl.height = rows * BLOCK_V_RES;
		canvasEl.style.imageRendering = "pixelated";
		canvasCtx.imageSmoothingEnabled = false;
	}
	function resizeCanvas({ cols, rows }) {
		canvasEl.width = cols * BLOCK_H_RES;
		canvasEl.height = rows * BLOCK_V_RES;
		canvasCtx.imageSmoothingEnabled = false;
	}
	function setInitialTheme() {
		cssTheme = getCssTheme(el);
		pendingChanges.theme = cssTheme;
	}
	function onVtReset({ size, theme, init }) {
		onVtUpdate({
			size,
			theme,
			changedRows: vt.reset(size.cols, size.rows, init)
		});
	}
	function onVtResize(size) {
		const changedRows = vt.resize(size.cols, size.rows);
		if (changedRows === void 0) return;
		onVtUpdate({
			size,
			changedRows
		});
	}
	function onVtOutput(data) {
		let changedRows;
		if (Array.isArray(data)) {
			changedRows = /* @__PURE__ */ new Set();
			for (const d of data) for (const row of vt.feed(d)) changedRows.add(row);
		} else changedRows = vt.feed(data);
		onVtUpdate({ changedRows });
	}
	function onVtUpdate({ size: newSize, theme, changedRows }) {
		let activity = false;
		if (changedRows !== void 0) for (const row of changedRows) {
			pendingChanges.rows.add(row);
			cursorHold = true;
			activity = true;
		}
		if (theme !== void 0 && props.preferEmbeddedTheme) {
			pendingChanges.theme = theme;
			for (let row = 0; row < size().rows; row++) pendingChanges.rows.add(row);
		}
		const newCursor = vt.getCursor();
		if (newCursor.visible != cursor.visible || newCursor.col != cursor.col || newCursor.row != cursor.row) {
			if (cursor.visible) pendingChanges.rows.add(cursor.row);
			if (newCursor.visible) pendingChanges.rows.add(newCursor.row);
			cursor = newCursor;
			cursorHold = true;
			activity = true;
		}
		if (newSize !== void 0) {
			pendingChanges.size = newSize;
			for (const row of pendingChanges.rows) if (row >= newSize.rows) pendingChanges.rows.delete(row);
		}
		if (activity && cursor.visible) pendingChanges.rows.add(cursor.row);
		scheduleRender();
	}
	function toggleBlink() {
		setBlinkOn((blink) => {
			if (!blink) cursorHold = false;
			return !blink;
		});
	}
	function scheduleRender() {
		if (frameRequestId === void 0) frameRequestId = requestAnimationFrame(render);
	}
	function render() {
		frameRequestId = void 0;
		const { size: newSize, theme: newTheme, rows } = pendingChanges;
		batch(function() {
			if (newSize !== void 0) {
				resizeCanvas(newSize);
				adjustTextRowNodeCount(newSize.rows);
				adjustSymbolRowNodeCount(newSize.rows);
				setSize(newSize);
			}
			if (newTheme !== void 0) {
				if (newTheme === null) setTheme(buildTheme(cssTheme, props.adaptivePalette));
				else setTheme(buildTheme(newTheme, props.adaptivePalette));
				colorsCache.clear();
			}
			const theme_ = theme();
			const cursorOn_ = cursorOn();
			for (const r of rows) renderRow(r, theme_, cursorOn_);
		});
		pendingChanges.size = void 0;
		pendingChanges.theme = void 0;
		pendingChanges.rows.clear();
		props.stats.renders += 1;
	}
	function renderRow(rowIndex, theme, cursorOn) {
		const line = vt.getLine(rowIndex, cursorOn);
		clearCanvasRow(rowIndex);
		renderRowBg(rowIndex, line.bg, theme);
		renderRowRasterSymbols(rowIndex, line.raster_symbols, theme);
		renderRowVectorSymbols(rowIndex, line.vector_symbols, theme);
		renderRowText(rowIndex, line.text, line.codepoints, theme);
	}
	function clearCanvasRow(rowIndex) {
		canvasCtx.clearRect(0, rowIndex * BLOCK_V_RES, size().cols * BLOCK_H_RES, BLOCK_V_RES);
	}
	function renderRowBg(rowIndex, spans, theme) {
		const view = vt.getDataView(spans, 8);
		const y = rowIndex * BLOCK_V_RES;
		let i = 0;
		while (i < view.byteLength) {
			const column = view.getUint16(i + 0, true);
			const width = view.getUint16(i + 2, true);
			const color = getColor(view, i + 4, theme);
			i += 8;
			canvasCtx.fillStyle = color;
			canvasCtx.fillRect(column * BLOCK_H_RES, y, width * BLOCK_H_RES, BLOCK_V_RES);
		}
	}
	function renderRowRasterSymbols(rowIndex, symbols, theme) {
		const view = vt.getDataView(symbols, 12);
		const y = rowIndex * BLOCK_V_RES;
		let i = 0;
		while (i < view.byteLength) {
			const column = view.getUint16(i + 0, true);
			const codepoint = view.getUint32(i + 4, true);
			const color = getColor(view, i + 8, theme) || theme.fg;
			i += 12;
			canvasCtx.fillStyle = color;
			drawBlockGlyph(canvasCtx, codepoint, column * BLOCK_H_RES, y);
		}
	}
	function renderRowVectorSymbols(rowIndex, symbols, theme) {
		const view = vt.getDataView(symbols, 16);
		const frag = document.createDocumentFragment();
		const symbolRow = vectorSymbolRowsEl.children[rowIndex];
		let i = 0;
		while (i < view.byteLength) {
			const column = view.getUint16(i + 0, true);
			const codepoint = view.getUint32(i + 4, true);
			const color = getColor(view, i + 8, theme);
			const attrs = view.getUint8(i + 12);
			i += 16;
			const el = createVectorSymbolNode(codepoint, column, color, (attrs & BLINK_MASK) !== 0);
			if (el) frag.appendChild(el);
		}
		recycleVectorSymbolUses(symbolRow);
		symbolRow.replaceChildren(frag);
	}
	function renderRowText(rowIndex, spans, codepoints, theme) {
		const spansView = vt.getDataView(spans, 12);
		const codepointsView = vt.getUint32Array(codepoints);
		const frag = document.createDocumentFragment();
		let i = 0;
		while (i < spansView.byteLength) {
			const column = spansView.getUint16(i + 0, true);
			const codepointsStart = spansView.getUint16(i + 2, true);
			const len = spansView.getUint16(i + 4, true);
			const color = getColor(spansView, i + 6, theme);
			const attrs = spansView.getUint8(i + 10);
			const text = String.fromCodePoint(...codepointsView.subarray(codepointsStart, codepointsStart + len));
			i += 12;
			const el = document.createElement("span");
			const style = el.style;
			style.setProperty("--offset", column);
			el.textContent = text;
			if (color) style.color = color;
			const cls = getAttrClass(attrs);
			if (cls !== null) el.className = cls;
			frag.appendChild(el);
		}
		textEl.children[rowIndex].replaceChildren(frag);
	}
	function getAttrClass(attrs) {
		let c = attrClassCache.get(attrs);
		if (c === void 0) {
			c = buildAttrClass(attrs);
			attrClassCache.set(attrs, c);
		}
		return c;
	}
	function buildAttrClass(attrs) {
		let cls = "";
		if ((attrs & BOLD_MASK) !== 0) cls += "ap-bold ";
		else if ((attrs & FAINT_MASK) !== 0) cls += "ap-faint ";
		if ((attrs & ITALIC_MASK) !== 0) cls += "ap-italic ";
		if ((attrs & UNDERLINE_MASK) !== 0) cls += "ap-underline ";
		if ((attrs & STRIKETHROUGH_MASK) !== 0) cls += "ap-strike ";
		if ((attrs & BLINK_MASK) !== 0) cls += "ap-blink ";
		return cls === "" ? null : cls;
	}
	function getColor(view, offset, theme) {
		const tag = view.getUint8(offset);
		if (tag === 0) return null;
		else if (tag === 1) return theme.fg;
		else if (tag === 2) return theme.bg;
		else if (tag === 3) return theme.palette[view.getUint8(offset + 1)];
		else if (tag === 4) {
			const key = view.getUint32(offset, true);
			let c = colorsCache.get(key);
			if (c === void 0) {
				const r = view.getUint8(offset + 1);
				const g = view.getUint8(offset + 2);
				const b = view.getUint8(offset + 3);
				c = "rgb(" + r + "," + g + "," + b + ")";
				colorsCache.set(key, c);
			}
			return c;
		} else throw new Error(`invalid color tag: ${tag}`);
	}
	function adjustTextRowNodeCount(rows) {
		let r = textEl.children.length;
		if (r < rows) {
			const frag = document.createDocumentFragment();
			while (r < rows) {
				const row = getNewRow();
				row.style.setProperty("--row", r);
				frag.appendChild(row);
				r += 1;
			}
			textEl.appendChild(frag);
		}
		while (textEl.children.length > rows) {
			const row = textEl.lastElementChild;
			textEl.removeChild(row);
			textRowPool.push(row);
		}
	}
	function adjustSymbolRowNodeCount(rows) {
		let r = vectorSymbolRowsEl.children.length;
		if (r < rows) {
			const frag = document.createDocumentFragment();
			while (r < rows) {
				const row = getNewSymbolRow();
				row.setAttribute("transform", `translate(0 ${r})`);
				frag.appendChild(row);
				r += 1;
			}
			vectorSymbolRowsEl.appendChild(frag);
		}
		while (vectorSymbolRowsEl.children.length > rows) {
			const row = vectorSymbolRowsEl.lastElementChild;
			vectorSymbolRowsEl.removeChild(row);
			vectorSymbolRowPool.push(row);
		}
	}
	function getNewRow() {
		let row = textRowPool.pop();
		if (row === void 0) {
			row = document.createElement("span");
			row.className = "ap-line";
		}
		return row;
	}
	function getNewSymbolRow() {
		let row = vectorSymbolRowPool.pop();
		if (row === void 0) {
			row = document.createElementNS(SVG_NS, "g");
			row.setAttribute("class", "ap-symbol-line");
		}
		return row;
	}
	function createVectorSymbolNode(codepoint, column, fg, blink) {
		if (!ensureVectorSymbolDef(codepoint)) return null;
		const isPowerline = POWERLINE_SYMBOLS.has(codepoint);
		const symbolX = isPowerline ? column - POWERLINE_SYMBOL_NUDGE : column;
		const symbolWidth = isPowerline ? 1 + POWERLINE_SYMBOL_NUDGE * 2 : 1;
		const node = getVectorSymbolUse();
		node.setAttribute("href", `#sym-${codepoint}`);
		node.setAttribute("x", symbolX);
		node.setAttribute("y", 0);
		node.setAttribute("width", symbolWidth);
		node.setAttribute("height", "1");
		if (fg) node.style.setProperty("color", fg);
		else node.style.removeProperty("color");
		if (blink) node.classList.add("ap-blink");
		else node.classList.remove("ap-blink");
		return node;
	}
	function recycleVectorSymbolUses(row) {
		while (row.firstChild) {
			const child = row.firstChild;
			row.removeChild(child);
			vectorSymbolUsePool.push(child);
		}
	}
	function getVectorSymbolUse() {
		let node = vectorSymbolUsePool.pop();
		if (node === void 0) node = document.createElementNS(SVG_NS, "use");
		return node;
	}
	function ensureVectorSymbolDef(codepoint) {
		const content = getVectorSymbolDef(codepoint);
		if (!content) return false;
		if (vectorSymbolDefCache.has(codepoint)) return true;
		const id = `sym-${codepoint}`;
		const symbol = document.createElementNS(SVG_NS, "symbol");
		symbol.setAttribute("id", id);
		symbol.setAttribute("viewBox", "0 0 1 1");
		symbol.setAttribute("preserveAspectRatio", "none");
		symbol.setAttribute("overflow", "visible");
		symbol.innerHTML = content;
		vectorSymbolDefsEl.appendChild(symbol);
		vectorSymbolDefCache.add(codepoint);
		return true;
	}
	return (() => {
		var _el$ = _tmpl$$f(), _el$2 = _el$.firstChild, _el$3 = _el$2.nextSibling, _el$4 = _el$3.firstChild, _el$5 = _el$4.nextSibling, _el$6 = _el$3.nextSibling;
		var _ref$ = el;
		typeof _ref$ === "function" ? use(_ref$, _el$) : el = _el$;
		var _ref$2 = canvasEl;
		typeof _ref$2 === "function" ? use(_ref$2, _el$2) : canvasEl = _el$2;
		var _ref$3 = vectorSymbolsEl;
		typeof _ref$3 === "function" ? use(_ref$3, _el$3) : vectorSymbolsEl = _el$3;
		var _ref$4 = vectorSymbolDefsEl;
		typeof _ref$4 === "function" ? use(_ref$4, _el$4) : vectorSymbolDefsEl = _el$4;
		var _ref$5 = vectorSymbolRowsEl;
		typeof _ref$5 === "function" ? use(_ref$5, _el$5) : vectorSymbolRowsEl = _el$5;
		var _ref$6 = textEl;
		typeof _ref$6 === "function" ? use(_ref$6, _el$6) : textEl = _el$6;
		createRenderEffect((_p$) => {
			var _v$ = style$1(), _v$2 = `0 0 ${size().cols} ${size().rows}`, _v$3 = !!blinkOn(), _v$4 = !!blinkOn();
			_p$.e = style(_el$, _v$, _p$.e);
			_v$2 !== _p$.t && setAttribute(_el$3, "viewBox", _p$.t = _v$2);
			_v$3 !== _p$.a && _el$3.classList.toggle("ap-blink", _p$.a = _v$3);
			_v$4 !== _p$.o && _el$6.classList.toggle("ap-blink", _p$.o = _v$4);
			return _p$;
		}, {
			e: void 0,
			t: void 0,
			a: void 0,
			o: void 0
		});
		return _el$;
	})();
};
function buildTheme(theme, adaptivePalette = false) {
	return {
		fg: theme.foreground,
		bg: theme.background,
		palette: adaptivePalette ? generate256Palette(theme.palette, theme.background, theme.foreground) : generateFixed256Palette(theme.palette)
	};
}
function getCssTheme(el) {
	const style = getComputedStyle(el);
	const foreground = normalizeHexColor(style.getPropertyValue("--term-color-foreground"), FALLBACK_THEME.foreground);
	const background = normalizeHexColor(style.getPropertyValue("--term-color-background"), FALLBACK_THEME.background);
	const palette = [];
	for (let i = 0; i < 16; i++) {
		const fallback = i >= 8 ? palette[i - 8] : FALLBACK_THEME.palette[i];
		palette[i] = normalizeHexColor(style.getPropertyValue(`--term-color-${i}`), fallback);
	}
	return {
		foreground,
		background,
		palette
	};
}
function generate256Palette(base16, bg, fg) {
	const bgLab = hexToOklab(bg);
	const fgLab = hexToOklab(fg);
	const c100 = hexToOklab(base16[1]);
	const c010 = hexToOklab(base16[2]);
	const c110 = hexToOklab(base16[3]);
	const c001 = hexToOklab(base16[4]);
	const c101 = hexToOklab(base16[5]);
	const c011 = hexToOklab(base16[6]);
	const palette = [...base16];
	for (let r = 0; r < 6; r += 1) {
		const tR = r / 5;
		const c0 = lerpOklab(tR, bgLab, c100);
		const c1 = lerpOklab(tR, c010, c110);
		const c2 = lerpOklab(tR, c001, c101);
		const c3 = lerpOklab(tR, c011, fgLab);
		for (let g = 0; g < 6; g += 1) {
			const tG = g / 5;
			const c4 = lerpOklab(tG, c0, c1);
			const c5 = lerpOklab(tG, c2, c3);
			for (let b = 0; b < 6; b += 1) {
				const c6 = lerpOklab(b / 5, c4, c5);
				palette.push(oklabToHex(c6));
			}
		}
	}
	for (let i = 0; i < 24; i += 1) {
		const t = (i + 1) / 25;
		palette.push(oklabToHex(lerpOklab(t, bgLab, fgLab)));
	}
	return palette;
}
function generateFixed256Palette(base16) {
	const palette = [...base16];
	const levels = [
		0,
		95,
		135,
		175,
		215,
		255
	];
	for (let r = 0; r < 6; r += 1) for (let g = 0; g < 6; g += 1) for (let b = 0; b < 6; b += 1) palette.push(rgbToHex(levels[r], levels[g], levels[b]));
	for (let i = 0; i < 24; i += 1) {
		const level = 8 + i * 10;
		palette.push(rgbToHex(level, level, level));
	}
	return palette;
}
function drawBlockGlyph(ctx, codepoint, x, y) {
	const unitX = BLOCK_H_RES / 8;
	const unitY = BLOCK_V_RES / 8;
	const halfX = BLOCK_H_RES / 2;
	const halfY = BLOCK_V_RES / 2;
	const sextantX = BLOCK_H_RES / 2;
	const sextantY = BLOCK_V_RES / 3;
	switch (codepoint) {
		case 9475:
			ctx.fillRect(x + 3, y, 2, BLOCK_V_RES);
			break;
		case 9593:
			ctx.fillRect(x + 3, y, 2, halfY);
			break;
		case 9595:
			ctx.fillRect(x + 3, y + halfY, 2, halfY);
			break;
		case 9600:
			ctx.fillRect(x, y, BLOCK_H_RES, halfY);
			break;
		case 9601:
			ctx.fillRect(x, y + 21, BLOCK_H_RES, unitY);
			break;
		case 9602:
			ctx.fillRect(x, y + 18, BLOCK_H_RES, 6);
			break;
		case 9603:
			ctx.fillRect(x, y + 15, BLOCK_H_RES, 9);
			break;
		case 9604:
			ctx.fillRect(x, y + halfY, BLOCK_H_RES, halfY);
			break;
		case 9605:
			ctx.fillRect(x, y + 9, BLOCK_H_RES, 15);
			break;
		case 9606:
			ctx.fillRect(x, y + 6, BLOCK_H_RES, 18);
			break;
		case 9607:
			ctx.fillRect(x, y + unitY, BLOCK_H_RES, 21);
			break;
		case 9608:
			ctx.fillRect(x, y, BLOCK_H_RES, BLOCK_V_RES);
			break;
		case 9632:
			ctx.fillRect(x, y + 6, BLOCK_H_RES, 12);
			break;
		case 9609:
			ctx.fillRect(x, y, 7, BLOCK_V_RES);
			break;
		case 9610:
			ctx.fillRect(x, y, 6, BLOCK_V_RES);
			break;
		case 9611:
			ctx.fillRect(x, y, 5, BLOCK_V_RES);
			break;
		case 9612:
			ctx.fillRect(x, y, halfX, BLOCK_V_RES);
			break;
		case 9613:
			ctx.fillRect(x, y, 3, BLOCK_V_RES);
			break;
		case 9614:
			ctx.fillRect(x, y, 2, BLOCK_V_RES);
			break;
		case 9615:
			ctx.fillRect(x, y, unitX, BLOCK_V_RES);
			break;
		case 9616:
			ctx.fillRect(x + halfX, y, halfX, BLOCK_V_RES);
			break;
		case 9617:
			ctx.save();
			ctx.globalAlpha = .25;
			ctx.fillRect(x, y, BLOCK_H_RES, BLOCK_V_RES);
			ctx.restore();
			break;
		case 9618:
			ctx.save();
			ctx.globalAlpha = .5;
			ctx.fillRect(x, y, BLOCK_H_RES, BLOCK_V_RES);
			ctx.restore();
			break;
		case 9619:
			ctx.save();
			ctx.globalAlpha = .75;
			ctx.fillRect(x, y, BLOCK_H_RES, BLOCK_V_RES);
			ctx.restore();
			break;
		case 9620:
			ctx.fillRect(x, y, BLOCK_H_RES, unitY);
			break;
		case 9621:
			ctx.fillRect(x + 7, y, unitX, BLOCK_V_RES);
			break;
		case 9622:
			ctx.fillRect(x, y + halfY, halfX, halfY);
			break;
		case 9623:
			ctx.fillRect(x + halfX, y + halfY, halfX, halfY);
			break;
		case 9624:
			ctx.fillRect(x, y, halfX, halfY);
			break;
		case 9625:
			ctx.fillRect(x, y, halfX, BLOCK_V_RES);
			ctx.fillRect(x + halfX, y + halfY, halfX, halfY);
			break;
		case 9626:
			ctx.fillRect(x, y, halfX, halfY);
			ctx.fillRect(x + halfX, y + halfY, halfX, halfY);
			break;
		case 9627:
			ctx.fillRect(x, y, BLOCK_H_RES, halfY);
			ctx.fillRect(x, y + halfY, halfX, halfY);
			break;
		case 9628:
			ctx.fillRect(x, y, BLOCK_H_RES, halfY);
			ctx.fillRect(x + halfX, y + halfY, halfX, halfY);
			break;
		case 9629:
			ctx.fillRect(x + halfX, y, halfX, halfY);
			break;
		case 9630:
			ctx.fillRect(x + halfX, y, halfX, halfY);
			ctx.fillRect(x, y + halfY, halfX, halfY);
			break;
		case 9631:
			ctx.fillRect(x + halfX, y, halfX, BLOCK_V_RES);
			ctx.fillRect(x, y + halfY, halfX, halfY);
			break;
		case 129792:
			ctx.fillRect(x, y, sextantX, sextantY);
			break;
		case 129793:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			break;
		case 129794:
			ctx.fillRect(x, y, 8, sextantY);
			break;
		case 129795:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			break;
		case 129796:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			break;
		case 129797:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			break;
		case 129798:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			break;
		case 129799:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129800:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129801:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129802:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129803:
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			break;
		case 129804:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			break;
		case 129805:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			break;
		case 129806:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			break;
		case 129807:
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129808:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129809:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129810:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129811:
			ctx.fillRect(x, y + sextantY, sextantX, 16);
			break;
		case 129812:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, 16);
			break;
		case 129813:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, 16);
			break;
		case 129814:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129815:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129816:
			ctx.fillRect(x + sextantX, y, sextantX, 16);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129817:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129818:
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129819:
			ctx.fillRect(x, y, sextantX, 24);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129820:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129821:
			ctx.fillRect(x, y, 8, 16);
			ctx.fillRect(x, y + 16, sextantX, sextantY);
			break;
		case 129822:
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129823:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129824:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129825:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129826:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129827:
			ctx.fillRect(x, y, sextantX, 16);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129828:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129829:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129830:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, 16);
			break;
		case 129831:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, 16);
			break;
		case 129832:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, 16);
			break;
		case 129833:
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129834:
			ctx.fillRect(x, y, sextantX, 16);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, 16);
			break;
		case 129835:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, 8, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129836:
			ctx.fillRect(x, y, 8, 16);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129837:
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129838:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129839:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129840:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129841:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129842:
			ctx.fillRect(x, y, sextantX, 16);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129843:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129844:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129845:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129846:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129847:
			ctx.fillRect(x + sextantX, y, sextantX, 16);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129848:
			ctx.fillRect(x, y, 8, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + 16, 8, sextantY);
			break;
		case 129849:
			ctx.fillRect(x, y + sextantY, 8, 16);
			break;
		case 129850:
			ctx.fillRect(x, y, sextantX, 24);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + 16, sextantX, sextantY);
			break;
		case 129851:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, 8, 16);
	}
}
var SYMBOL_STROKE = .05;
var CELL_RATIO = 9.0375 / 20;
function getVectorSymbolDef(codepoint) {
	const stroke = `stroke="currentColor" stroke-width="${SYMBOL_STROKE}" stroke-linejoin="miter" stroke-linecap="square"`;
	const strokeButt = `stroke="currentColor" stroke-width="${SYMBOL_STROKE}" stroke-linejoin="miter" stroke-linecap="butt"`;
	const stroked = (d) => `<path d="${d}" fill="none" ${stroke}/>`;
	const third = 1 / 3;
	const twoThirds = 2 / 3;
	switch (codepoint) {
		case 9698: return "<path d=\"M1,1 L1,0 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M1,1 L1,0 L0,1 Z");
		case 9699: return "<path d=\"M0,1 L0,0 L1,1 Z\" fill=\"currentColor\"/>" + stroked("M0,1 L0,0 L1,1 Z");
		case 9700: return "<path d=\"M0,0 L1,0 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L1,0 L0,1 Z");
		case 9701: return "<path d=\"M1,0 L1,1 L0,0 Z\" fill=\"currentColor\"/>" + stroked("M1,0 L1,1 L0,0 Z");
		case 9871: {
			const halfVerticalGap = .2 / 2;
			const toViewBoxY = (offset) => .5 + offset * CELL_RATIO;
			const leftX1 = .425;
			const rightX0 = .575;
			const rightX1 = 1.02;
			const topY0 = toViewBoxY(-.27);
			const topY1 = toViewBoxY(-.1);
			const bottomY0 = toViewBoxY(halfVerticalGap);
			const bottomY1 = toViewBoxY(.27);
			const rect = (x0, x1, y0, y1) => `M${x0},${y0} L${x1},${y0} L${x1},${y1} L${x0},${y1} Z`;
			return `<path d="${rect(0, leftX1, topY0, topY1)} ${rect(rightX0, rightX1, topY0, topY1)} ${rect(0, leftX1, bottomY0, bottomY1)} ${rect(rightX0, rightX1, bottomY0, bottomY1)}" fill="currentColor"/>`;
		}
		case 129852: return `<path d="M0,${twoThirds} L0,1 L0.5,1 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,1 L0.5,1 Z`);
		case 129853: return `<path d="M0,${twoThirds} L0,1 L1,1 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,1 L1,1 Z`);
		case 129854: return `<path d="M0,${third} L0.5,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,${third} L0.5,1 L0,1 Z`);
		case 129855: return `<path d="M0,${third} L1,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,${third} L1,1 L0,1 Z`);
		case 129856: return "<path d=\"M0,0 L0.5,1 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L0.5,1 L0,1 Z");
		case 129857: return `<path d="M0,${third} L0,1 L1,1 L1,0 L0.5,0 Z" fill="currentColor"/>` + stroked(`M0,${third} L0,1 L1,1 L1,0 L0.5,0 Z`);
		case 129858: return `<path d="M0,${third} L0,1 L1,1 L1,0 Z" fill="currentColor"/>` + stroked(`M0,${third} L0,1 L1,1 L1,0 Z`);
		case 129859: return `<path d="M0,${twoThirds} L0,1 L1,1 L1,0 L0.5,0 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,1 L1,1 L1,0 L0.5,0 Z`);
		case 129860: return `<path d="M0,${twoThirds} L0,1 L1,1 L1,0 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,1 L1,1 L1,0 Z`);
		case 129861: return "<path d=\"M0.5,0 L1,0 L1,1 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0.5,0 L1,0 L1,1 L0,1 Z");
		case 129862: return `<path d="M0,${twoThirds} L0,1 L1,1 L1,${third} Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,1 L1,1 L1,${third} Z`);
		case 129863: return `<path d="M0.5,1 L1,1 L1,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0.5,1 L1,1 L1,${twoThirds} Z`);
		case 129864: return `<path d="M0,1 L1,1 L1,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,1 L1,1 L1,${twoThirds} Z`);
		case 129865: return `<path d="M0.5,1 L1,1 L1,${third} Z" fill="currentColor"/>` + stroked(`M0.5,1 L1,1 L1,${third} Z`);
		case 129866: return `<path d="M0,1 L1,1 L1,${third} Z" fill="currentColor"/>` + stroked(`M0,1 L1,1 L1,${third} Z`);
		case 129867: return "<path d=\"M0.5,1 L1,0 L1,1 Z\" fill=\"currentColor\"/>" + stroked("M0.5,1 L1,0 L1,1 Z");
		case 129868: return `<path d="M0,0 L0.5,0 L1,${third} L1,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L0.5,0 L1,${third} L1,1 L0,1 Z`);
		case 129869: return `<path d="M0,0 L0,1 L1,1 L1,${third} Z" fill="currentColor"/>` + stroked(`M0,0 L0,1 L1,1 L1,${third} Z`);
		case 129870: return `<path d="M0,0 L0.5,0 L1,${twoThirds} L1,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L0.5,0 L1,${twoThirds} L1,1 L0,1 Z`);
		case 129871: return `<path d="M0,0 L1,${twoThirds} L1,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L1,${twoThirds} L1,1 L0,1 Z`);
		case 129872: return "<path d=\"M0,0 L0.5,0 L1,1 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L0.5,0 L1,1 L0,1 Z");
		case 129873: return `<path d="M0,${third} L1,${twoThirds} L1,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,${third} L1,${twoThirds} L1,1 L0,1 Z`);
		case 129874: return `<path d="M0,${twoThirds} L0,0 L1,0 L1,1 L0.5,1 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,0 L1,0 L1,1 L0.5,1 Z`);
		case 129875: return `<path d="M0,${twoThirds} L0,0 L1,0 L1,1 Z" fill="currentColor"/>` + stroked(`M0,${twoThirds} L0,0 L1,0 L1,1 Z`);
		case 129876: return `<path d="M0,${third} L0,0 L1,0 L1,1 L0.5,1 Z" fill="currentColor"/>` + stroked(`M0,${third} L0,0 L1,0 L1,1 L0.5,1 Z`);
		case 129877: return `<path d="M0,${third} L0,0 L1,0 L1,1 Z" fill="currentColor"/>` + stroked(`M0,${third} L0,0 L1,0 L1,1 Z`);
		case 129878: return "<path d=\"M0,0 L1,0 L1,1 L0.5,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L1,0 L1,1 L0.5,1 Z");
		case 129879: return `<path d="M0,${third} L0.5,0 L0,0 Z" fill="currentColor"/>` + stroked(`M0,${third} L0.5,0 L0,0 Z`);
		case 129880: return `<path d="M0,0 L1,0 L0,${third} Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L0,${third} Z`);
		case 129881: return `<path d="M0,0 L0.5,0 L0,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,0 L0.5,0 L0,${twoThirds} Z`);
		case 129882: return `<path d="M0,0 L1,0 L0,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L0,${twoThirds} Z`);
		case 129883: return "<path d=\"M0,0 L0.5,0 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L0.5,0 L0,1 Z");
		case 129884: return `<path d="M0,0 L1,0 L1,${third} L0,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${third} L0,${twoThirds} Z`);
		case 129885: return `<path d="M0,0 L1,0 L1,${twoThirds} L0.5,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${twoThirds} L0.5,1 L0,1 Z`);
		case 129886: return `<path d="M0,0 L1,0 L1,${twoThirds} L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${twoThirds} L0,1 Z`);
		case 129887: return `<path d="M0,0 L1,0 L1,${third} L0.5,1 L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${third} L0.5,1 L0,1 Z`);
		case 129888: return `<path d="M0,0 L1,0 L1,${third} L0,1 Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${third} L0,1 Z`);
		case 129889: return "<path d=\"M0,0 L1,0 L0.5,1 L0,1 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L1,0 L0.5,1 L0,1 Z");
		case 129890: return `<path d="M0.5,0 L1,0 L1,${third} Z" fill="currentColor"/>` + stroked(`M0.5,0 L1,0 L1,${third} Z`);
		case 129891: return `<path d="M0,0 L1,0 L1,${third} Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${third} Z`);
		case 129892: return `<path d="M0.5,0 L1,0 L1,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0.5,0 L1,0 L1,${twoThirds} Z`);
		case 129893: return `<path d="M0,0 L1,0 L1,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,0 L1,0 L1,${twoThirds} Z`);
		case 129894: return "<path d=\"M0.5,0 L1,0 L1,1 Z\" fill=\"currentColor\"/>" + stroked("M0.5,0 L1,0 L1,1 Z");
		case 129895: return `<path d="M0,${third} L0,0 L1,0 L1,${twoThirds} Z" fill="currentColor"/>` + stroked(`M0,${third} L0,0 L1,0 L1,${twoThirds} Z`);
		case 129896: return `<path fill-rule="evenodd" d="M0,0 L1,0 L1,1 L0,1 Z M0,0 L0,1 L0.5,0.5 Z" fill="currentColor"/><path d="M0,0 L1,0 M0,1 L1,1 M1,0 L1,1" fill="none" ${stroke}/><path d="M0,0 L0.5,0.5 M0,1 L0.5,0.5" fill="none" ${strokeButt}/>`;
		case 129897: return `<path fill-rule="evenodd" d="M0,0 L1,0 L1,1 L0,1 Z M0,0 L1,0 L0.5,0.5 Z" fill="currentColor"/><path d="M0,0 L0,1 M1,0 L1,1 M0,1 L1,1" fill="none" ${stroke}/><path d="M0,0 L0.5,0.5 M1,0 L0.5,0.5" fill="none" ${strokeButt}/>`;
		case 129898: return `<path fill-rule="evenodd" d="M0,0 L1,0 L1,1 L0,1 Z M1,0 L1,1 L0.5,0.5 Z" fill="currentColor"/><path d="M0,0 L1,0 M0,1 L1,1 M0,0 L0,1" fill="none" ${stroke}/><path d="M1,0 L0.5,0.5 M1,1 L0.5,0.5" fill="none" ${strokeButt}/>`;
		case 129899: return `<path fill-rule="evenodd" d="M0,0 L1,0 L1,1 L0,1 Z M0,1 L1,1 L0.5,0.5 Z" fill="currentColor"/><path d="M0,0 L1,0 M0,0 L0,1 M1,0 L1,1" fill="none" ${stroke}/><path d="M0,1 L0.5,0.5 M1,1 L0.5,0.5" fill="none" ${strokeButt}/>`;
		case 129900: return "<path d=\"M0,0 L0,1 L0.5,0.5 Z\" fill=\"currentColor\"/>" + stroked("M0,0 L0,1 L0.5,0.5 Z");
		case 57520: return "<path d=\"M0,0 L1,0.5 L0,1 Z\" fill=\"currentColor\"/>";
		case 57521: return "<path d=\"M0,0 L1,0.5 L0,1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\" stroke-linejoin=\"miter\"/>";
		case 57522: return "<path d=\"M1,0 L0,0.5 L1,1 Z\" fill=\"currentColor\"/>";
		case 57523: return "<path d=\"M1,0 L0,0.5 L1,1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\" stroke-linejoin=\"miter\"/>";
		case 57524: return "<path d=\"M0,0 A1,0.5 0 0 1 0,1 Z\" fill=\"currentColor\"/>";
		case 57525: return "<path d=\"M0,0 A1,0.5 0 0 1 0,1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\"/>";
		case 57526: return "<path d=\"M1,0 A1,0.5 0 0 0 1,1 Z\" fill=\"currentColor\"/>";
		case 57527: return "<path d=\"M1,0 A1,0.5 0 0 0 1,1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\"/>";
		case 57528: return "<path d=\"M0,1 L0,0 L1,1 Z\" fill=\"currentColor\"/>";
		case 57529:
		case 57535: return "<path d=\"M0,0 L1,1\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\"/>";
		case 57530: return "<path d=\"M1,1 L1,0 L0,1 Z\" fill=\"currentColor\"/>";
		case 57531:
		case 57533: return "<path d=\"M0,1 L1,0\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"0.07\"/>";
		case 57532: return "<path d=\"M0,0 L1,0 L0,1 Z\" fill=\"currentColor\"/>";
		case 57534: return "<path d=\"M1,0 L1,1 L0,0 Z\" fill=\"currentColor\"/>";
		default: return null;
	}
}
var POWERLINE_SYMBOLS = /* @__PURE__ */ new Set([
	57520,
	57521,
	57522,
	57523,
	57524,
	57525,
	57526,
	57527,
	57528,
	57529,
	57530,
	57531,
	57532,
	57533,
	57534,
	57535
]);
var POWERLINE_SYMBOL_NUDGE = .02;
var FALLBACK_THEME = {
	foreground: "#000000",
	background: "#000000",
	palette: [
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000",
		"#000000"
	]
};
var _tmpl$$e = /*#__PURE__*/ template(`<svg version=1.1 viewBox="0 0 12 12"class="ap-icon ap-icon-fullscreen-off"aria-hidden=true><path d="M7,5 L7,0 L9,2 L11,0 L12,1 L10,3 L12,5 Z"></path><path d="M5,7 L0,7 L2,9 L0,11 L1,12 L3,10 L5,12 Z">`);
var ExpandIcon = () => {
	return _tmpl$$e();
};
var _tmpl$$d = /*#__PURE__*/ template(`<svg version=1.1 viewBox="6 8 14 16"class=ap-icon aria-hidden=true><path d="M0.938 8.313h22.125c0.5 0 0.938 0.438 0.938 0.938v13.5c0 0.5-0.438 0.938-0.938 0.938h-22.125c-0.5 0-0.938-0.438-0.938-0.938v-13.5c0-0.5 0.438-0.938 0.938-0.938zM1.594 22.063h20.813v-12.156h-20.813v12.156zM3.844 11.188h1.906v1.938h-1.906v-1.938zM7.469 11.188h1.906v1.938h-1.906v-1.938zM11.031 11.188h1.938v1.938h-1.938v-1.938zM14.656 11.188h1.875v1.938h-1.875v-1.938zM18.25 11.188h1.906v1.938h-1.906v-1.938zM5.656 15.031h1.938v1.938h-1.938v-1.938zM9.281 16.969v-1.938h1.906v1.938h-1.906zM12.875 16.969v-1.938h1.906v1.938h-1.906zM18.406 16.969h-1.938v-1.938h1.938v1.938zM16.531 20.781h-9.063v-1.906h9.063v1.906z">`);
var KeyboardIcon = () => {
	return _tmpl$$d();
};
var _tmpl$$c = /*#__PURE__*/ template(`<svg version=1.1 viewBox="0 0 12 12"class=ap-icon aria-hidden=true><path d="M1,0 L4,0 L4,12 L1,12 Z"></path><path d="M8,0 L11,0 L11,12 L8,12 Z">`);
var PauseIcon = () => {
	return _tmpl$$c();
};
var _tmpl$$b = /*#__PURE__*/ template(`<svg version=1.1 viewBox="0 0 12 12"class=ap-icon aria-hidden=true><path d="M1,0 L11,6 L1,12 Z">`);
var PlayIcon = () => {
	return _tmpl$$b();
};
var _tmpl$$a = /*#__PURE__*/ template(`<svg version=1.1 viewBox="0 0 12 12"class="ap-icon ap-icon-fullscreen-on"aria-hidden=true><path d="M12,0 L7,0 L9,2 L7,4 L8,5 L10,3 L12,5 Z"></path><path d="M0,12 L0,7 L2,9 L4,7 L5,8 L3,10 L5,12 Z">`);
var ShrinkIcon = () => {
	return _tmpl$$a();
};
var _tmpl$$9 = /*#__PURE__*/ template(`<svg xmlns=http://www.w3.org/2000/svg viewBox="0 0 20 20"fill=currentColor aria-hidden=true><path d="M10.5 3.75a.75.75 0 0 0-1.264-.546L5.203 7H2.667a.75.75 0 0 0-.7.48A6.985 6.985 0 0 0 1.5 10c0 .887.165 1.737.468 2.52.111.29.39.48.7.48h2.535l4.033 3.796a.75.75 0 0 0 1.264-.546V3.75ZM16.45 5.05a.75.75 0 0 0-1.06 1.061 5.5 5.5 0 0 1 0 7.778.75.75 0 0 0 1.06 1.06 7 7 0 0 0 0-9.899Z"></path><path d="M14.329 7.172a.75.75 0 0 0-1.061 1.06 2.5 2.5 0 0 1 0 3.536.75.75 0 0 0 1.06 1.06 4 4 0 0 0 0-5.656Z">`);
var SpeakerOnIcon = () => {
	return _tmpl$$9();
};
var _tmpl$$8 = /*#__PURE__*/ template(`<svg xmlns=http://www.w3.org/2000/svg viewBox="0 0 20 20"fill=currentColor class=size-5 aria-hidden=true><path d="M10.047 3.062a.75.75 0 0 1 .453.688v12.5a.75.75 0 0 1-1.264.546L5.203 13H2.667a.75.75 0 0 1-.7-.48A6.985 6.985 0 0 1 1.5 10c0-.887.165-1.737.468-2.52a.75.75 0 0 1 .7-.48h2.535l4.033-3.796a.75.75 0 0 1 .811-.142ZM13.78 7.22a.75.75 0 1 0-1.06 1.06L14.44 10l-1.72 1.72a.75.75 0 0 0 1.06 1.06l1.72-1.72 1.72 1.72a.75.75 0 1 0 1.06-1.06L16.56 10l1.72-1.72a.75.75 0 0 0-1.06-1.06L15.5 8.94l-1.72-1.72Z">`);
var SpeakerOffIcon = () => {
	return _tmpl$$8();
};
var _tmpl$$7 = /*#__PURE__*/ template(`<span class="ap-gutter ap-gutter-empty">`);
var _tmpl$2$2 = /*#__PURE__*/ template(`<span class="ap-gutter ap-gutter-clip"><span class=ap-gutter-full>`);
var _tmpl$3$1 = /*#__PURE__*/ template(`<button class="ap-button ap-playback-button"type=button>`);
var _tmpl$4$1 = /*#__PURE__*/ template(`<span class=ap-bar>`);
var _tmpl$5$1 = /*#__PURE__*/ template(`<span class=ap-tooltip>Unmute (m)`);
var _tmpl$6$1 = /*#__PURE__*/ template(`<span class=ap-tooltip>Mute (m)`);
var _tmpl$7$1 = /*#__PURE__*/ template(`<button class="ap-button ap-speaker-button ap-tooltip-container"type=button aria-label="Mute / unmute">`);
var _tmpl$8$1 = /*#__PURE__*/ template(`<div class=ap-control-bar><span class=ap-timer><span class=ap-time-elapsed></span><span class=ap-time-remaining></span></span><span class=ap-progressbar></span><button class="ap-button ap-kbd-button ap-tooltip-container"type=button aria-label="Show keyboard shortcuts"><span class=ap-tooltip>Keyboard shortcuts (?)</span></button><button class="ap-button ap-fullscreen-button ap-tooltip-container"type=button aria-label="Toggle fullscreen mode"><span class=ap-tooltip>Fullscreen (f)`);
var _tmpl$9 = /*#__PURE__*/ template(`<span class="ap-marker-container ap-tooltip-container"><span class=ap-marker></span><span class=ap-tooltip>`);
function formatTime(seconds) {
	let s = Math.floor(seconds);
	const d = Math.floor(s / 86400);
	s %= 86400;
	const h = Math.floor(s / 3600);
	s %= 3600;
	const m = Math.floor(s / 60);
	s %= 60;
	if (d > 0) return `${zeroPad(d)}:${zeroPad(h)}:${zeroPad(m)}:${zeroPad(s)}`;
	else if (h > 0) return `${zeroPad(h)}:${zeroPad(m)}:${zeroPad(s)}`;
	else return `${zeroPad(m)}:${zeroPad(s)}`;
}
function zeroPad(n) {
	return n < 10 ? `0${n}` : n.toString();
}
function Gutter(props) {
	let fill;
	createEffect(() => {
		const duration = props.duration;
		if (!Number.isFinite(duration) || duration <= 0) return;
		const animation = fill.animate([{ transform: "translateX(-100%)" }, { transform: "translateX(0)" }], {
			duration: duration * 1e3,
			easing: "linear",
			fill: "both"
		});
		animation.pause();
		onCleanup(() => animation.cancel());
		createEffect(() => {
			const timing = props.timing;
			if (typeof timing?.time !== "number") return;
			if (timing.rate > 0) {
				animation.playbackRate = timing.rate;
				animation.startTime = timing.sampledAt - performance.timeOrigin - timing.time * 1e3 / timing.rate;
			} else {
				animation.pause();
				animation.currentTime = Math.max(0, Math.min(timing.time, duration)) * 1e3;
			}
		});
	});
	return [_tmpl$$7(), (() => {
		var _el$2 = _tmpl$2$2(), _el$3 = _el$2.firstChild;
		var _ref$ = fill;
		typeof _ref$ === "function" ? use(_ref$, _el$3) : fill = _el$3;
		return _el$2;
	})()];
}
var ControlBar = (props) => {
	const currentTime = () => typeof props.currentTime === "number" ? formatTime(props.currentTime) : "--:--";
	const remainingTime = () => typeof props.remainingTime === "number" ? "-" + formatTime(props.remainingTime) : currentTime();
	const markers = createMemo(() => typeof props.duration === "number" ? props.markers.filter((m) => m[0] < props.duration) : []);
	const markerPosition = (m) => `${m[0] / props.duration * 100}%`;
	const markerText = (m) => {
		if (m[1] === "") return formatTime(m[0]);
		else return `${formatTime(m[0])} - ${m[1]}`;
	};
	const isPastMarker = (m) => typeof props.currentTime === "number" ? m[0] <= props.currentTime : false;
	const calcPosition = (e) => {
		const barWidth = e.currentTarget.offsetWidth;
		const rect = e.currentTarget.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;
		return `${Math.max(0, mouseX / barWidth) * 100}%`;
	};
	const [mouseDown, setMouseDown] = createSignal(false);
	const throttledSeek = throttle((pos) => props.onSeekClick(pos), 50);
	const onMouseDown = (e) => {
		if (e._marker) return;
		if (e.altKey || e.shiftKey || e.metaKey || e.ctrlKey || e.button !== 0) return;
		setMouseDown(true);
		props.onSeekClick(calcPosition(e));
	};
	const onMove = (e) => {
		if (e.altKey || e.shiftKey || e.metaKey || e.ctrlKey) return;
		if (mouseDown()) throttledSeek(calcPosition(e));
	};
	const onDocumentMouseUp = () => {
		setMouseDown(false);
	};
	document.addEventListener("mouseup", onDocumentMouseUp);
	onCleanup(() => {
		document.removeEventListener("mouseup", onDocumentMouseUp);
	});
	return (() => {
		var _el$4 = _tmpl$8$1(), _el$6 = _el$4.firstChild, _el$7 = _el$6.firstChild, _el$8 = _el$7.nextSibling, _el$9 = _el$6.nextSibling, _el$12 = _el$9.nextSibling, _el$13 = _el$12.firstChild, _el$14 = _el$12.nextSibling, _el$15 = _el$14.firstChild;
		var _ref$2 = props.ref;
		typeof _ref$2 === "function" ? use(_ref$2, _el$4) : props.ref = _el$4;
		insert(_el$4, createComponent(Show, {
			get when() {
				return props.isPausable;
			},
			get children() {
				var _el$5 = _tmpl$3$1();
				_el$5.$$click = (e) => {
					e.preventDefault();
					props.onPlayClick(e);
				};
				insert(_el$5, createComponent(Switch, { get children() {
					return [createComponent(Match, {
						get when() {
							return props.isPlaying;
						},
						get children() {
							return createComponent(PauseIcon, {});
						}
					}), createComponent(Match, {
						when: true,
						get children() {
							return createComponent(PlayIcon, {});
						}
					})];
				} }));
				createRenderEffect(() => setAttribute(_el$5, "aria-label", props.isPlaying ? "Pause" : "Play"));
				return _el$5;
			}
		}), _el$6);
		insert(_el$7, currentTime);
		insert(_el$8, remainingTime);
		insert(_el$9, createComponent(Show, {
			get when() {
				return typeof props.duration === "number" || props.isSeekable;
			},
			get children() {
				var _el$0 = _tmpl$4$1();
				_el$0.$$mousemove = onMove;
				_el$0.$$mousedown = onMouseDown;
				insert(_el$0, createComponent(Gutter, {
					get duration() {
						return props.duration;
					},
					get timing() {
						return props.timing;
					}
				}), null);
				insert(_el$0, createComponent(For, {
					get each() {
						return markers();
					},
					children: (m, i) => (() => {
						var _el$16 = _tmpl$9(), _el$17 = _el$16.firstChild, _el$18 = _el$17.nextSibling;
						_el$16.$$mousedown = (e) => {
							e._marker = true;
						};
						_el$16.$$click = (e) => {
							e.preventDefault();
							props.onSeekClick({ marker: i() });
						};
						insert(_el$18, () => markerText(m));
						createRenderEffect((_p$) => {
							var _v$ = markerPosition(m), _v$2 = !!isPastMarker(m);
							_v$ !== _p$.e && setStyleProperty(_el$16, "left", _p$.e = _v$);
							_v$2 !== _p$.t && _el$17.classList.toggle("ap-marker-past", _p$.t = _v$2);
							return _p$;
						}, {
							e: void 0,
							t: void 0
						});
						return _el$16;
					})()
				}), null);
				return _el$0;
			}
		}));
		insert(_el$4, createComponent(Show, {
			get when() {
				return props.isMuted !== void 0;
			},
			get children() {
				var _el$1 = _tmpl$7$1();
				_el$1.$$click = (e) => {
					e.preventDefault();
					props.onMuteClick(e);
				};
				insert(_el$1, createComponent(Switch, { get children() {
					return [createComponent(Match, {
						get when() {
							return props.isMuted === true;
						},
						get children() {
							return [createComponent(SpeakerOffIcon, {}), _tmpl$5$1()];
						}
					}), createComponent(Match, {
						get when() {
							return props.isMuted === false;
						},
						get children() {
							return [createComponent(SpeakerOnIcon, {}), _tmpl$6$1()];
						}
					})];
				} }));
				return _el$1;
			}
		}), _el$12);
		_el$12.$$click = (e) => {
			e.preventDefault();
			props.onHelpClick(e);
		};
		insert(_el$12, createComponent(KeyboardIcon, {}), _el$13);
		_el$14.$$click = (e) => {
			e.preventDefault();
			props.onFullscreenClick(e);
		};
		insert(_el$14, createComponent(ShrinkIcon, {}), _el$15);
		insert(_el$14, createComponent(ExpandIcon, {}), _el$15);
		createRenderEffect(() => _el$4.classList.toggle("ap-seekable", !!props.isSeekable));
		return _el$4;
	})();
};
delegateEvents([
	"click",
	"mousedown",
	"mousemove"
]);
var _tmpl$$6 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-error"><span>💥`);
var ErrorOverlay = () => {
	return _tmpl$$6();
};
var _tmpl$$5 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-loading"><span class=ap-loader>`);
var LoaderOverlay = () => {
	return _tmpl$$5();
};
var _tmpl$$4 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-info"><span>`);
var InfoOverlay = (props) => {
	return (() => {
		var _el$ = _tmpl$$4(), _el$2 = _el$.firstChild;
		insert(_el$2, () => props.message);
		createRenderEffect(() => _el$.classList.toggle("ap-was-playing", !!props.wasPlaying));
		return _el$;
	})();
};
var _tmpl$$3 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-start"><div class=ap-play-button><div><span><svg version=1.1 viewBox="0 0 1000.0 1000.0"class=ap-icon><defs><mask id=small-triangle-mask><rect width=100% height=100% fill=white></rect><polygon points="700.0 500.0, 400.00000000000006 326.7949192431122, 399.9999999999999 673.2050807568877"fill=black></polygon></mask></defs><polygon points="1000.0 500.0, 250.0000000000001 66.98729810778059, 249.99999999999977 933.0127018922192"mask=url(#small-triangle-mask) fill=white class=ap-play-btn-fill></polygon><polyline points="673.2050807568878 400.0, 326.7949192431123 600.0"stroke=white stroke-width=90 class=ap-play-btn-stroke>`);
var StartOverlay = (props) => {
	return (() => {
		var _el$ = _tmpl$$3();
		_el$.$$click = (e) => {
			e.preventDefault();
			props.onClick(e);
		};
		return _el$;
	})();
};
delegateEvents(["click"]);
var _tmpl$$2 = /*#__PURE__*/ template(`<li><kbd>space</kbd> - pause / resume`);
var _tmpl$2$1 = /*#__PURE__*/ template(`<li><kbd>←</kbd> / <kbd>→</kbd> - rewind / fast-forward by 5 seconds`);
var _tmpl$3 = /*#__PURE__*/ template(`<li><kbd>Shift</kbd> + <kbd>←</kbd> / <kbd>→</kbd> - rewind / fast-forward by 10%`);
var _tmpl$4 = /*#__PURE__*/ template(`<li><kbd>[</kbd> / <kbd>]</kbd> - jump to the previous / next marker`);
var _tmpl$5 = /*#__PURE__*/ template(`<li><kbd>0</kbd>, <kbd>1</kbd>, <kbd>2</kbd> ... <kbd>9</kbd> - jump to 0%, 10%, 20% ... 90%`);
var _tmpl$6 = /*#__PURE__*/ template(`<li><kbd>,</kbd> / <kbd>.</kbd> - step back / forward, a frame at a time (when paused)`);
var _tmpl$7 = /*#__PURE__*/ template(`<li><kbd>m</kbd> - mute / unmute audio`);
var _tmpl$8 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-help"><div><div><p>Keyboard shortcuts</p><ul><li><kbd>f</kbd> - toggle fullscreen mode</li><li><kbd>k</kbd> - toggle keystroke overlay</li><li><kbd>?</kbd> - show this help popup`);
var HelpOverlay = (props) => {
	return (() => {
		var _el$ = _tmpl$8(), _el$2 = _el$.firstChild, _el$5 = _el$2.firstChild.firstChild.nextSibling, _el$10 = _el$5.firstChild, _el$13 = _el$10.nextSibling.nextSibling;
		_el$.$$click = (e) => {
			e.preventDefault();
			props.onClose(e);
		};
		_el$2.$$click = (e) => {
			e.stopPropagation();
		};
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.isPausable;
			},
			get children() {
				return _tmpl$$2();
			}
		}), _el$10);
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.isSeekable;
			},
			get children() {
				return [
					_tmpl$2$1(),
					_tmpl$3(),
					_tmpl$4(),
					_tmpl$5(),
					_tmpl$6()
				];
			}
		}), _el$10);
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.hasAudio;
			},
			get children() {
				return _tmpl$7();
			}
		}), _el$13);
		return _el$;
	})();
};
delegateEvents(["click"]);
var _tmpl$$1 = /*#__PURE__*/ template(`<div><kbd>`);
var _tmpl$2 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-keystrokes">`);
var VISIBLE_MS = 2e3;
function KeystrokePill(props) {
	const [isFading, setIsFading] = createSignal(false);
	createEffect(() => {
		const { id } = props.keystroke;
		props.keystroke.rev();
		setIsFading(false);
		const fadeTimeoutId = setTimeout(function() {
			setIsFading(true);
		}, VISIBLE_MS);
		const expireTimeoutId = setTimeout(function() {
			props.onExpired(id);
		}, 2700);
		onCleanup(() => {
			clearTimeout(fadeTimeoutId);
			clearTimeout(expireTimeoutId);
		});
	});
	return (() => {
		var _el$ = _tmpl$$1(), _el$2 = _el$.firstChild;
		insert(_el$2, () => props.keystroke.label());
		createRenderEffect(() => className(_el$, isFading() ? "ap-keystroke-pill fading" : "ap-keystroke-pill"));
		return _el$;
	})();
}
var KeystrokesOverlay = (props) => {
	return (() => {
		var _el$3 = _tmpl$2();
		insert(_el$3, createComponent(For, {
			get each() {
				return props.keystrokes;
			},
			children: (keystroke) => createComponent(KeystrokePill, {
				keystroke,
				get onExpired() {
					return props.onExpired;
				}
			})
		}));
		createRenderEffect((_$p) => setStyleProperty(_el$3, "--ap-keystrokes-bottom", `${(props.bottomOffset ?? 0) + 12}px`));
		return _el$3;
	})();
};
var basicSeqs = {
	...Object.fromEntries(Array.from({ length: 26 }, (_, i) => {
		return [String.fromCharCode(i + 1), `C-${String.fromCharCode(97 + i)}`];
	})),
	"\b": "Back",
	"\r": "Ret",
	"	": "Tab",
	"\x1B": "Esc",
	"": "Back"
};
var singles = { " ": "Spc" };
var functionalKeys = {
	57358: "Caps",
	57359: "Scroll",
	57360: "Num",
	57361: "Print",
	57362: "Pause",
	57363: "Menu",
	57414: "Enter",
	57421: "PgUp",
	57422: "PgDn"
};
var arrowKeys = {
	up: "↑",
	down: "↓",
	left: "←",
	right: "→"
};
var csiFinalKeys = {
	A: arrowKeys.up,
	B: arrowKeys.down,
	C: arrowKeys.right,
	D: arrowKeys.left,
	F: "End",
	H: "Home",
	P: "F1",
	Q: "F2",
	R: "F3",
	S: "F4"
};
var csiTildeKeys = {
	2: "Ins",
	3: "Del",
	5: "PgUp",
	6: "PgDn",
	15: "F5",
	17: "F6",
	18: "F7",
	19: "F8",
	20: "F9",
	21: "F10",
	23: "F11",
	24: "F12"
};
function addModifierPrefix(key, modifier) {
	const mod = Number.parseInt(modifier.split(":")[0], 10);
	if (!Number.isFinite(mod) || mod <= 1) return key;
	const bits = mod - 1;
	const parts = [];
	if (bits & 4) parts.push("C");
	if (bits & 2) parts.push("A");
	if (bits & 1) parts.push("S");
	return parts.length === 0 ? key : `${parts.join("-")}-${key}`;
}
function codepointToKey(codepoint) {
	if (codepoint in functionalKeys) return functionalKeys[codepoint];
	const char = String.fromCodePoint(codepoint);
	if (char in basicSeqs) return basicSeqs[char];
	if (char in singles) return singles[char];
	return char;
}
function formatCsiSequence(seq) {
	const csiUAlt = seq.match(/^(\d+);;(\d+)u$/);
	if (csiUAlt !== null) return `A-${codepointToKey(Number.parseInt(csiUAlt[2], 10))}`;
	const csiU = seq.match(/^(\d+)(?:;([\d:]+))?u$/);
	if (csiU !== null) {
		const key = codepointToKey(Number.parseInt(csiU[1], 10));
		return csiU[2] === void 0 ? key : addModifierPrefix(key, csiU[2]);
	}
	const finalKey = seq.match(/^O?([A-Z])$/);
	if (finalKey !== null && finalKey[1] in csiFinalKeys) return csiFinalKeys[finalKey[1]];
	const tildeKey = seq.match(/^(\d+)~$/);
	if (tildeKey !== null && tildeKey[1] in csiTildeKeys) return csiTildeKeys[tildeKey[1]];
	const modifyOtherKeys = seq.match(/^27;([\d:]+);(\d+)~$/);
	if (modifyOtherKeys !== null) return addModifierPrefix(codepointToKey(Number.parseInt(modifyOtherKeys[2], 10)), modifyOtherKeys[1]);
	const modifiedFinal = seq.match(/^(?:1;)?([\d:]+)([A-Z])$/);
	if (modifiedFinal !== null && modifiedFinal[2] in csiFinalKeys) return addModifierPrefix(csiFinalKeys[modifiedFinal[2]], modifiedFinal[1]);
	const modifiedTilde = seq.match(/^(\d+);([\d:]+)~$/);
	if (modifiedTilde !== null && modifiedTilde[1] in csiTildeKeys) return addModifierPrefix(csiTildeKeys[modifiedTilde[1]], modifiedTilde[2]);
	return "";
}
function formatEscapeSequence(data) {
	const seq = data.slice(1);
	if (seq.length === 1) {
		if (seq in basicSeqs) return "A-" + basicSeqs[seq];
		return seq in singles ? "A-" + singles[seq] : "A-" + seq;
	}
	if (seq.startsWith("[")) return formatCsiSequence(seq.slice(1));
	if (seq.startsWith("O")) return formatCsiSequence(seq);
	return "";
}
function formatKeystroke(data) {
	if (data in basicSeqs) return {
		kind: "special",
		label: basicSeqs[data]
	};
	if (data.length === 1) {
		if (data in singles) return {
			kind: "special",
			label: singles[data]
		};
		return {
			kind: "text",
			label: data
		};
	}
	if (data.startsWith("\x1B")) {
		const key = formatEscapeSequence(data);
		if (key !== "") return {
			kind: "special",
			label: key
		};
	}
	return null;
}
var _tmpl$ = /*#__PURE__*/ template(`<div class=ap-wrapper tabindex=-1><div>`);
var CONTROL_BAR_HEIGHT = 32;
var Player = (props) => {
	const logger = props.logger;
	const core = props.core;
	const autoPlay = props.autoPlay;
	const charW = props.charW;
	const charH = props.charH;
	const bordersW = props.bordersW;
	const bordersH = props.bordersH;
	const themeOption = props.theme ?? "auto/asciinema";
	const preferEmbeddedTheme = themeOption.slice(0, 5) === "auto/";
	const themeName = preferEmbeddedTheme ? themeOption.slice(5) : themeOption;
	const [terminalSize, setTerminalSize] = createSignal({
		cols: props.cols,
		rows: props.rows
	}, { equals: (newVal, oldVal) => newVal.cols === oldVal.cols && newVal.rows === oldVal.rows });
	const [containerSize, setContainerSize] = createSignal({
		width: 0,
		height: 0
	}, { equals: (newVal, oldVal) => newVal.width === oldVal.width && newVal.height === oldVal.height });
	const [isPausable, setIsPausable] = createSignal(true);
	const [isSeekable, setIsSeekable] = createSignal(true);
	const [isFullscreen, setIsFullscreen] = createSignal(false);
	const [currentTime, setCurrentTime] = createSignal(null);
	const [timing, setTiming] = createSignal(null);
	const [isPlaying, setIsPlaying] = createSignal(false);
	const [isMuted, setIsMuted] = createSignal(void 0);
	const [wasPlaying, setWasPlaying] = createSignal(false);
	const [overlay, setOverlay] = createSignal(!autoPlay ? "start" : null);
	const [infoMessage, setInfoMessage] = createSignal(null);
	const [blinking, setBlinking] = createSignal(false);
	const [duration, setDuration] = createSignal(null);
	const [markers, setMarkers] = createSignal([]);
	const [userActive, setUserActive] = createSignal(false);
	const [isHelpVisible, setIsHelpVisible] = createSignal(false);
	const [originalTheme, setOriginalTheme] = createSignal(null);
	const terminalCols = createMemo(() => terminalSize().cols || 80);
	const terminalRows = createMemo(() => terminalSize().rows || 24);
	const controlBarHeight = () => props.controls === false ? 0 : CONTROL_BAR_HEIGHT;
	const remainingTime = () => typeof duration() === "number" && typeof currentTime() === "number" ? duration() - currentTime() : null;
	const [isKeystrokeOverlayEnabled, setKeystrokeOverlayEnabled] = createSignal(props.keystrokeOverlay !== false);
	const [keystrokes, setKeystrokes] = createSignal([]);
	const controlsVisible = () => props.controls === true || props.controls === "auto" && userActive();
	let nextKeystrokeId = 1;
	let userActivityTimeoutId;
	let timeUpdateIntervalId;
	let wrapperRef;
	let playerRef;
	let controlBarRef;
	let resizeObserver;
	const onCoreReady = ({ isPausable, isSeekable }) => {
		batch(() => {
			setIsPausable(isPausable);
			setIsSeekable(isSeekable);
		});
	};
	const onCoreMetadata = (meta) => {
		batch(() => {
			if (meta.duration !== void 0) setDuration(meta.duration);
			if (meta.markers !== void 0) setMarkers(meta.markers);
			if (meta.hasAudio !== void 0) setIsMuted(meta.hasAudio ? false : void 0);
		});
	};
	const onCoreReset = ({ size, theme }) => {
		batch(() => {
			setTerminalSize(size);
			if (theme !== void 0) setOriginalTheme(theme);
		});
	};
	const onCoreResize = (size) => {
		setTerminalSize(size);
	};
	const onCorePlay = () => {
		setOverlay(null);
	};
	const onCorePlaying = () => {
		batch(() => {
			setIsPlaying(true);
			setWasPlaying(true);
			setOverlay(null);
			setBlinking(true);
		});
	};
	const onCorePause = () => {
		batch(() => {
			setIsPlaying(false);
			setBlinking(false);
		});
	};
	const onCoreLoading = () => {
		batch(() => {
			setIsPlaying(false);
			setBlinking(false);
			setOverlay("loader");
			clearKeystrokes();
		});
	};
	const onCoreOffline = ({ message }) => {
		batch(() => {
			setIsPlaying(false);
			setBlinking(false);
			clearKeystrokes();
			if (message !== void 0) {
				setInfoMessage(message);
				setOverlay("info");
			}
		});
	};
	const onCoreMuted = (muted) => {
		setIsMuted(muted);
	};
	const stats = { terminal: { renders: 0 } };
	const onCoreEnded = ({ message }) => {
		batch(() => {
			setIsPlaying(false);
			setBlinking(false);
			if (message !== void 0) {
				setInfoMessage(message);
				setOverlay("info");
			}
		});
		logger.debug("stats", stats.terminal);
	};
	const onCoreError = () => {
		setBlinking(false);
		clearKeystrokes();
		setOverlay("error");
	};
	const onCoreInput = ({ data }) => {
		if (!isKeystrokeOverlayEnabled()) return;
		const keystroke = formatKeystroke(data);
		if (keystroke === null) return;
		const currentKeystrokes = keystrokes();
		const latestKeystroke = currentKeystrokes[currentKeystrokes.length - 1];
		if (latestKeystroke?.kind === "text" && keystroke.kind === "text") {
			latestKeystroke.append(keystroke.label);
			return;
		}
		if (latestKeystroke?.kind === "special" && keystroke.kind === "special" && latestKeystroke.key === keystroke.label) {
			latestKeystroke.increment();
			return;
		}
		setKeystrokes([...currentKeystrokes, createKeystroke(keystroke)].slice(-4));
	};
	const onCoreSeeked = () => {
		clearKeystrokes();
	};
	const onCoreTiming = (snapshot) => {
		clearInterval(timeUpdateIntervalId);
		batch(() => {
			setTiming(snapshot);
			updateTime();
		});
		if (snapshot.rate > 0) timeUpdateIntervalId = setInterval(updateTime, 100);
	};
	const onVisibilityChange = () => {
		if (document.visibilityState === "visible") core.requestTiming();
	};
	const clearKeystrokes = () => {
		setKeystrokes([]);
	};
	const removeKeystroke = (id) => {
		setKeystrokes((keystrokes) => keystrokes.filter((keystroke) => keystroke.id !== id));
	};
	const createKeystroke = ({ kind, label }) => {
		const [value, setValue] = createSignal(label);
		const [count, setCount] = createSignal(1);
		const [rev, setRev] = createSignal(0);
		return {
			id: nextKeystrokeId++,
			kind,
			key: label,
			label: () => count() === 1 ? value() : `${value()} × ${count()}`,
			rev,
			append: (label) => {
				setValue((value) => (value + label).slice(-10));
				setRev((rev) => rev + 1);
			},
			increment: () => {
				setCount((count) => count + 1);
				setRev((rev) => rev + 1);
			}
		};
	};
	core.addEventListener("ready", onCoreReady);
	core.addEventListener("metadata", onCoreMetadata);
	core.addEventListener("play", onCorePlay);
	core.addEventListener("playing", onCorePlaying);
	core.addEventListener("pause", onCorePause);
	core.addEventListener("loading", onCoreLoading);
	core.addEventListener("offline", onCoreOffline);
	core.addEventListener("muted", onCoreMuted);
	core.addEventListener("ended", onCoreEnded);
	core.addEventListener("error", onCoreError);
	core.addEventListener("input", onCoreInput);
	core.addEventListener("seeked", onCoreSeeked);
	core.addEventListener("reset", onCoreReset);
	core.addEventListener("resize", onCoreResize);
	core.addEventListener("timing", onCoreTiming);
	document.addEventListener("visibilitychange", onVisibilityChange);
	const setupResizeObserver = () => {
		resizeObserver = new ResizeObserver(debounce((_entries) => {
			setContainerSize({
				width: wrapperRef.offsetWidth,
				height: wrapperRef.offsetHeight
			});
			wrapperRef.dispatchEvent(new CustomEvent("resize", { detail: { el: playerRef } }));
		}, 10));
		resizeObserver.observe(wrapperRef);
	};
	onMount(async () => {
		logger.info("view: mounted");
		logger.debug("view: font measurements", {
			charW,
			charH
		});
		setupResizeObserver();
		setContainerSize({
			width: wrapperRef.offsetWidth,
			height: wrapperRef.offsetHeight
		});
	});
	onCleanup(() => {
		core.removeEventListener("ready", onCoreReady);
		core.removeEventListener("metadata", onCoreMetadata);
		core.removeEventListener("play", onCorePlay);
		core.removeEventListener("playing", onCorePlaying);
		core.removeEventListener("pause", onCorePause);
		core.removeEventListener("loading", onCoreLoading);
		core.removeEventListener("offline", onCoreOffline);
		core.removeEventListener("muted", onCoreMuted);
		core.removeEventListener("ended", onCoreEnded);
		core.removeEventListener("error", onCoreError);
		core.removeEventListener("input", onCoreInput);
		core.removeEventListener("seeked", onCoreSeeked);
		core.removeEventListener("reset", onCoreReset);
		core.removeEventListener("resize", onCoreResize);
		core.removeEventListener("timing", onCoreTiming);
		document.removeEventListener("visibilitychange", onVisibilityChange);
		core.stop();
		clearInterval(timeUpdateIntervalId);
		resizeObserver.disconnect();
	});
	const terminalElementSize = createMemo(() => {
		const terminalW = charW * terminalCols() + bordersW;
		const terminalH = charH * terminalRows() + bordersH;
		let fit = props.fit ?? "width";
		const currentContainerSize = containerSize();
		if (fit === "both" || isFullscreen()) {
			if (currentContainerSize.width / (currentContainerSize.height - controlBarHeight()) > terminalW / terminalH) fit = "height";
			else fit = "width";
		}
		if (fit === false || fit === "none") return {};
		else if (fit === "width") {
			const scale = currentContainerSize.width / terminalW;
			return {
				scale,
				width: currentContainerSize.width,
				height: terminalH * scale + controlBarHeight()
			};
		} else if (fit === "height") {
			const scale = (currentContainerSize.height - controlBarHeight()) / terminalH;
			return {
				scale,
				width: terminalW * scale,
				height: currentContainerSize.height
			};
		} else throw new Error(`unsupported fit mode: ${fit}`);
	});
	const onFullscreenChange = () => {
		setIsFullscreen(document.fullscreenElement ?? document.webkitFullscreenElement);
	};
	const toggleFullscreen = () => {
		if (isFullscreen()) (document.exitFullscreen ?? document.webkitExitFullscreen ?? (() => {})).apply(document);
		else (wrapperRef.requestFullscreen ?? wrapperRef.webkitRequestFullscreen ?? (() => {})).apply(wrapperRef);
	};
	const toggleHelp = () => {
		if (isHelpVisible()) setIsHelpVisible(false);
		else {
			core.pause();
			setIsHelpVisible(true);
		}
	};
	const toggleKeystrokeOverlay = () => {
		if (isKeystrokeOverlayEnabled()) {
			clearKeystrokes();
			setKeystrokeOverlayEnabled(false);
		} else setKeystrokeOverlayEnabled(true);
	};
	const onKeyDown = (e) => {
		if (e.altKey || e.metaKey || e.ctrlKey) return;
		if ((e.key == " " || e.key == "Enter") && e.target instanceof HTMLButtonElement) return;
		if (e.key == " ") togglePlay();
		else if (e.key == ",") core.step(-1);
		else if (e.key == ".") core.step();
		else if (e.key == "f") toggleFullscreen();
		else if (e.key == "m") toggleMuted();
		else if (e.key == "[") core.seek({ marker: "prev" });
		else if (e.key == "]") core.seek({ marker: "next" });
		else if (e.key.charCodeAt(0) >= 48 && e.key.charCodeAt(0) <= 57) {
			const pos = (e.key.charCodeAt(0) - 48) / 10;
			core.seek(`${pos * 100}%`);
		} else if (e.key == "?") toggleHelp();
		else if (e.key == "k") toggleKeystrokeOverlay();
		else if (e.key == "ArrowLeft") {
			if (e.shiftKey) core.seek("<<<");
			else core.seek("<<");
		} else if (e.key == "ArrowRight") {
			if (e.shiftKey) core.seek(">>>");
			else core.seek(">>");
		} else if (e.key == "Escape") setIsHelpVisible(false);
		else return;
		e.stopPropagation();
		e.preventDefault();
	};
	const wrapperOnMouseMove = () => {
		if (isFullscreen()) onUserActive(true);
	};
	const playerOnMouseLeave = () => {
		if (!isFullscreen()) onUserActive(false);
	};
	const updateTime = () => {
		const time = getTime(timing());
		setCurrentTime(time === null ? null : Math.max(0, Math.min(time, duration() ?? Infinity)));
	};
	const onUserActive = (show) => {
		clearTimeout(userActivityTimeoutId);
		if (show) userActivityTimeoutId = setTimeout(() => onUserActive(false), 2e3);
		setUserActive(show);
	};
	const embeddedTheme = createMemo(() => preferEmbeddedTheme ? originalTheme() : null);
	const playerStyle = () => {
		const style = {};
		if ((props.fit === false || props.fit === "none") && props.terminalFontSize !== void 0) {
			if (props.terminalFontSize === "small") style["font-size"] = "12px";
			else if (props.terminalFontSize === "medium") style["font-size"] = "18px";
			else if (props.terminalFontSize === "big") style["font-size"] = "24px";
			else style["font-size"] = props.terminalFontSize;
		}
		const size = terminalElementSize();
		if (size.width !== void 0) {
			style["width"] = `${size.width}px`;
			style["height"] = `${size.height}px`;
		}
		if (props.terminalFontFamily !== void 0) style["--term-font-family"] = props.terminalFontFamily;
		const themeColors = embeddedTheme();
		if (themeColors) {
			style["--term-color-foreground"] = themeColors.foreground;
			style["--term-color-background"] = themeColors.background;
		}
		return style;
	};
	const play = () => {
		core.play();
	};
	const togglePlay = () => {
		if (isPlaying()) core.pause();
		else core.play();
	};
	const toggleMuted = () => {
		if (isMuted() === true) core.unmute();
		else core.mute();
	};
	const seek = (pos) => {
		core.seek(pos);
	};
	const playerClass = () => `ap-player ap-default-term-ff asciinema-player-theme-${themeName}`;
	const terminalScale = () => terminalElementSize()?.scale;
	return (() => {
		var _el$ = _tmpl$(), _el$2 = _el$.firstChild;
		var _ref$ = wrapperRef;
		typeof _ref$ === "function" ? use(_ref$, _el$) : wrapperRef = _el$;
		_el$.addEventListener("webkitfullscreenchange", onFullscreenChange);
		_el$.addEventListener("fullscreenchange", onFullscreenChange);
		_el$.$$mousemove = wrapperOnMouseMove;
		_el$.$$keydown = onKeyDown;
		var _ref$2 = playerRef;
		typeof _ref$2 === "function" ? use(_ref$2, _el$2) : playerRef = _el$2;
		_el$2.$$mousemove = () => onUserActive(true);
		_el$2.addEventListener("mouseleave", playerOnMouseLeave);
		insert(_el$2, createComponent(Terminal, {
			get cols() {
				return terminalCols();
			},
			get rows() {
				return terminalRows();
			},
			get scale() {
				return terminalScale();
			},
			get blinking() {
				return blinking();
			},
			get cursorMode() {
				return props.cursorMode;
			},
			get boldIsBright() {
				return props.boldIsBright;
			},
			get adaptivePalette() {
				return props.adaptivePalette;
			},
			get lineHeight() {
				return props.terminalLineHeight;
			},
			preferEmbeddedTheme,
			core,
			logger,
			get onReady() {
				return props.onTerminalReady;
			},
			get stats() {
				return stats.terminal;
			}
		}), null);
		insert(_el$2, createComponent(Show, {
			get when() {
				return props.controls !== false;
			},
			get children() {
				return createComponent(ControlBar, {
					get duration() {
						return duration();
					},
					get currentTime() {
						return currentTime();
					},
					get remainingTime() {
						return remainingTime();
					},
					get timing() {
						return timing();
					},
					get markers() {
						return markers();
					},
					get isPlaying() {
						return isPlaying() || overlay() == "loader";
					},
					get isPausable() {
						return isPausable();
					},
					get isSeekable() {
						return isSeekable();
					},
					get isMuted() {
						return isMuted();
					},
					onPlayClick: togglePlay,
					onFullscreenClick: toggleFullscreen,
					onHelpClick: toggleHelp,
					onSeekClick: seek,
					onMuteClick: toggleMuted,
					ref(r$) {
						var _ref$3 = controlBarRef;
						typeof _ref$3 === "function" ? _ref$3(r$) : controlBarRef = r$;
					}
				});
			}
		}), null);
		insert(_el$2, createComponent(Show, {
			get when() {
				return keystrokes().length > 0;
			},
			get children() {
				return createComponent(KeystrokesOverlay, {
					get bottomOffset() {
						return controlBarHeight();
					},
					get keystrokes() {
						return keystrokes();
					},
					onExpired: removeKeystroke
				});
			}
		}), null);
		insert(_el$2, createComponent(Switch, { get children() {
			return [
				createComponent(Match, {
					get when() {
						return overlay() == "start";
					},
					get children() {
						return createComponent(StartOverlay, { onClick: play });
					}
				}),
				createComponent(Match, {
					get when() {
						return overlay() == "loader";
					},
					get children() {
						return createComponent(LoaderOverlay, {});
					}
				}),
				createComponent(Match, {
					get when() {
						return overlay() == "error";
					},
					get children() {
						return createComponent(ErrorOverlay, {});
					}
				})
			];
		} }), null);
		insert(_el$2, createComponent(Slide, { get children() {
			return createComponent(Show, {
				get when() {
					return overlay() == "info";
				},
				get children() {
					return createComponent(InfoOverlay, {
						get message() {
							return infoMessage();
						},
						get wasPlaying() {
							return wasPlaying();
						}
					});
				}
			});
		} }), null);
		insert(_el$2, createComponent(Show, {
			get when() {
				return isHelpVisible();
			},
			get children() {
				return createComponent(HelpOverlay, {
					onClose: () => setIsHelpVisible(false),
					get isPausable() {
						return isPausable();
					},
					get isSeekable() {
						return isSeekable();
					},
					get hasAudio() {
						return isMuted() !== void 0;
					}
				});
			}
		}), null);
		createRenderEffect((_p$) => {
			var _v$ = !!controlsVisible(), _v$2 = playerClass(), _v$3 = playerStyle();
			_v$ !== _p$.e && _el$.classList.toggle("ap-hud", _p$.e = _v$);
			_v$2 !== _p$.t && className(_el$2, _p$.t = _v$2);
			_p$.a = style(_el$2, _v$3, _p$.a);
			return _p$;
		}, {
			e: void 0,
			t: void 0,
			a: void 0
		});
		return _el$;
	})();
};
delegateEvents(["keydown", "mousemove"]);
function mount(core, elem, opts = {}) {
	const metrics = measureTerminal(opts.terminalFontFamily, opts.terminalLineHeight);
	const props = {
		core,
		logger: opts.logger,
		cols: opts.cols,
		rows: opts.rows,
		fit: opts.fit,
		controls: opts.controls,
		cursorMode: opts.cursorMode,
		keystrokeOverlay: opts.keystrokeOverlay,
		autoPlay: opts.autoPlay,
		boldIsBright: opts.boldIsBright,
		adaptivePalette: opts.adaptivePalette,
		terminalFontSize: opts.terminalFontSize,
		terminalFontFamily: opts.terminalFontFamily,
		terminalLineHeight: opts.terminalLineHeight,
		theme: opts.theme,
		onTerminalReady: opts.onTerminalReady,
		...metrics
	};
	let el;
	const dispose = render(() => {
		el = createComponent(Player, props);
		return el;
	}, elem);
	return {
		el,
		dispose
	};
}
function measureTerminal(fontFamily, lineHeight) {
	const cols = 80;
	const rows = 24;
	const playerDiv = document.createElement("div");
	playerDiv.className = "ap-default-term-ff";
	playerDiv.style.height = "0px";
	playerDiv.style.overflow = "hidden";
	playerDiv.style.fontSize = "15px";
	if (fontFamily !== void 0) playerDiv.style.setProperty("--term-font-family", fontFamily);
	const termDiv = document.createElement("div");
	termDiv.className = "ap-term";
	termDiv.style.width = `${cols}ch`;
	termDiv.style.height = `${rows * (lineHeight ?? 1.3333333333)}em`;
	termDiv.style.fontSize = "100%";
	playerDiv.appendChild(termDiv);
	document.body.appendChild(playerDiv);
	const metrics = {
		charW: termDiv.clientWidth / cols,
		charH: termDiv.clientHeight / rows,
		bordersW: termDiv.offsetWidth - termDiv.clientWidth,
		bordersH: termDiv.offsetHeight - termDiv.clientHeight
	};
	document.body.removeChild(playerDiv);
	return metrics;
}
var CORE_OPTS = [
	"audioUrl",
	"autoPlay",
	"autoplay",
	"cols",
	"idleTimeLimit",
	"loop",
	"markers",
	"pauseOnMarkers",
	"poster",
	"preload",
	"rows",
	"speed",
	"startAt"
];
var UI_OPTS = [
	"autoPlay",
	"autoplay",
	"boldIsBright",
	"cols",
	"adaptivePalette",
	"controls",
	"cursorMode",
	"fit",
	"keystrokeOverlay",
	"rows",
	"terminalFontFamily",
	"terminalFontSize",
	"terminalLineHeight",
	"theme"
];
function pick(inputOpts, keys) {
	return Object.fromEntries(Object.entries(inputOpts).filter(([key, value]) => keys.includes(key) && value != null));
}
function repr(value) {
	return typeof value === "string" ? JSON.stringify(value) : String(value);
}
function normalizeMarkers(markers) {
	if (!Array.isArray(markers)) throw new Error(`markers option must be an array, got: ${repr(markers)}`);
	return markers.map((m, i) => {
		if (Number.isFinite(m)) return [m, ""];
		if (Array.isArray(m) && Number.isFinite(m[0]) && typeof m[1] === "string") return [m[0], m[1]];
		throw new Error(`invalid marker at index ${i}: expected a number or a [number, string] pair`);
	});
}
function coreOpts(inputOpts, overrides = {}) {
	const opts = pick(inputOpts, CORE_OPTS);
	opts.autoPlay ??= opts.autoplay;
	opts.speed ??= 1;
	if (opts.markers !== void 0) opts.markers = normalizeMarkers(opts.markers);
	if (!Number.isFinite(opts.speed) || opts.speed <= 0) throw new Error(`speed option must be a positive number, got: ${repr(opts.speed)}`);
	return {
		...opts,
		...overrides
	};
}
function uiOpts(inputOpts, overrides = {}) {
	const opts = pick(inputOpts, UI_OPTS);
	opts.autoPlay ??= opts.autoplay;
	opts.adaptivePalette ??= false;
	opts.controls ??= "auto";
	opts.cursorMode ??= "blinking";
	opts.keystrokeOverlay ??= false;
	if (![
		"blinking",
		"steady",
		"hidden"
	].includes(opts.cursorMode)) throw new Error(`unsupported cursor mode: ${opts.cursorMode}`);
	if (typeof opts.keystrokeOverlay !== "boolean") throw new Error(`unsupported keystroke overlay option: ${opts.keystrokeOverlay}`);
	return {
		...opts,
		...overrides
	};
}
// ../../node_modules/.pnpm/asciinema-player@3.18.0/node_modules/asciinema-player/dist/index.js
function create(src, elem, opts = {}) {
	const logger = opts.logger ?? new DummyLogger();
	const core = new Core(src, coreOpts(opts, { logger }));
	const onTerminalReady = () => core.terminalReady();
	const { el, dispose } = mount(core, elem, uiOpts(opts, {
		logger,
		onTerminalReady
	}));
	core.init().catch(() => {});
	const player = {
		el,
		dispose,
		getCurrentTime: () => core.getCurrentTime(),
		getDuration: () => core.getDuration(),
		play: () => core.play(),
		pause: () => core.pause(),
		seek: (pos) => core.seek(pos)
	};
	player.addEventListener = (name, callback) => {
		return core.addEventListener(name, callback.bind(player));
	};
	return player;
}
// ../../packages/react/src/components/AsciinemaPlayerImpl.tsx
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var AsciinemaPlayerImpl = (t0) => {
	const $ = (0, import_compiler_runtime.c)(26);
	const { id, rows, cols, input, output, timing, cast, fit, speed, autoPlay, loop, theme, idleTimeLimit: t1, startAt, poster, controls, markers, autoFocus, clickToToggle, onPlayer, style } = t0;
	const idleTimeLimit = t1 === void 0 ? 2 : t1;
	const playerContainerRef = (0, import_react.useRef)(null);
	const resumeRef = (0, import_react.useRef)(null);
	const onPlayerRef = useLatestRef(onPlayer);
	let t2;
	let t3;
	if ($[0] !== autoFocus || $[1] !== autoPlay || $[2] !== cast || $[3] !== clickToToggle || $[4] !== cols || $[5] !== controls || $[6] !== fit || $[7] !== idleTimeLimit || $[8] !== input || $[9] !== loop || $[10] !== markers || $[11] !== onPlayerRef || $[12] !== output || $[13] !== poster || $[14] !== rows || $[15] !== speed || $[16] !== startAt || $[17] !== theme || $[18] !== timing) {
		t2 = () => {
			const container = playerContainerRef.current;
			if (!container) return;
			const source = cast !== void 0 ? {
				data: () => new Response(cast),
				parser: "asciicast"
			} : {
				data: () => [
					new Response(timing),
					new Response(output),
					new Response(input)
				],
				parser: "typescript"
			};
			const recording = {
				cast,
				input,
				output,
				timing
			};
			const resume = resumeRef.current && sameRecording(resumeRef.current.recording, recording) ? resumeRef.current : null;
			const player = create(source, container, {
				rows,
				cols,
				autoPlay: resume ? false : autoPlay,
				loop,
				theme,
				speed,
				idleTimeLimit: idleTimeLimit ?? Number.POSITIVE_INFINITY,
				startAt,
				fit,
				poster,
				controls,
				markers
			});
			let playing = false;
			player.addEventListener("playing", () => {
				playing = true;
			});
			player.addEventListener("pause", () => {
				playing = false;
			});
			player.addEventListener("ended", () => {
				playing = false;
			});
			if (resume) runPlayback(player.seek(resume.time).then(() => resume.playing ? player.play() : void 0));
			else if (autoPlay !== false) runPlayback(player.play());
			if (autoFocus) player.el.focus();
			const onPlayer_0 = onPlayerRef.current;
			onPlayer_0?.({
				seek: (seconds) => player.seek(seconds).then(_temp, _temp2),
				element: player.el
			});
			const onClick = (e) => {
				if (e.target instanceof Element && e.target.closest(".ap-control-bar, .ap-overlay")) return;
				if (window.getSelection()?.toString()) return;
				runPlayback(playing ? player.pause() : player.play());
			};
			if (clickToToggle) container.addEventListener("click", onClick);
			return () => {
				container.removeEventListener("click", onClick);
				const time = player.getCurrentTime();
				resumeRef.current = playing || time > 0 ? {
					recording,
					time,
					playing
				} : null;
				onPlayer_0?.(null);
				player.dispose();
			};
		};
		t3 = [
			timing,
			output,
			input,
			cast,
			rows,
			cols,
			autoPlay,
			loop,
			theme,
			speed,
			idleTimeLimit,
			startAt,
			fit,
			poster,
			controls,
			markers,
			autoFocus,
			clickToToggle,
			onPlayerRef
		];
		$[0] = autoFocus;
		$[1] = autoPlay;
		$[2] = cast;
		$[3] = clickToToggle;
		$[4] = cols;
		$[5] = controls;
		$[6] = fit;
		$[7] = idleTimeLimit;
		$[8] = input;
		$[9] = loop;
		$[10] = markers;
		$[11] = onPlayerRef;
		$[12] = output;
		$[13] = poster;
		$[14] = rows;
		$[15] = speed;
		$[16] = startAt;
		$[17] = theme;
		$[18] = timing;
		$[19] = t2;
		$[20] = t3;
	} else {
		t2 = $[19];
		t3 = $[20];
	}
	(0, import_react.useEffect)(t2, t3);
	const t4 = `asciinema-player-${id || "default"}`;
	let t5;
	if ($[21] !== style) {
		t5 = { ...style };
		$[21] = style;
		$[22] = t5;
	} else t5 = $[22];
	let t6;
	if ($[23] !== t4 || $[24] !== t5) {
		t6 = /*#__PURE__*/ (0, import_jsx_runtime.jsx)("div", {
			id: t4,
			ref: playerContainerRef,
			style: t5
		});
		$[23] = t4;
		$[24] = t5;
		$[25] = t6;
	} else t6 = $[25];
	return t6;
};
var sameRecording = (a, b) => a.cast === b.cast && a.input === b.input && a.output === b.output && a.timing === b.timing;
var runPlayback = (command) => {
	command.catch(() => void 0);
};
function _temp() {}
function _temp2() {}
export { AsciinemaPlayerImpl as default };

//# sourceMappingURL=AsciinemaPlayerImpl.js.map