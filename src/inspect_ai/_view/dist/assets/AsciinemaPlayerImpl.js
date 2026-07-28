import { i as __toESM } from "./rolldown-runtime.js";
import { n as require_react, t as require_jsx_runtime } from "./jsx-runtime.js";
//#region ../../node_modules/.pnpm/asciinema-player@3.17.0/node_modules/asciinema-player/dist/logging-DeB0koVt.js
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
	log(...args) {}
	debug(...args) {}
	info(...args) {}
	warn(...args) {}
	error(...args) {}
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
//#endregion
//#region ../../node_modules/.pnpm/asciinema-player@3.17.0/node_modules/asciinema-player/dist/core-BSn7GtYU.js
var Clock = class {
	constructor(speed = 1) {
		this.speed = speed;
		this.startTime = performance.now();
	}
	getTime() {
		return this.speed * (performance.now() - this.startTime);
	}
	setTime(time) {
		this.startTime = performance.now() - time / this.speed;
	}
};
var NullClock = class {
	constructor() {}
	getTime(_speed) {}
	setTime(_time) {}
};
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
		throw new Error(`failed parsing segmented recording index from ${src.url}: ${error.message}`);
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
				throw new Error(`failed parsing recording segment from ${segment.url}: ${error.message}`);
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
					}
				};
			case EVENT.LOAD_FAILED:
				if (currentState !== STATE.LOADING) return { nextState: currentState };
				return {
					nextState: STATE.FAILED,
					action: () => {
						ctx.failureError = payload.error;
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
		ctx.pauseElapsedTime = time;
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
	function pausePlaybackClock() {
		cancelScheduledRecordingEvent();
		ctx.pauseElapsedTime = now() - ctx.startTime;
	}
	function preparePlaybackClock() {
		if (ctx.audioElement && !ctx.audioCtx) setupAudioCtx();
	}
	function confirmPlaybackClockStart() {
		ctx.startTime = now() - ctx.pauseElapsedTime;
		ctx.pauseElapsedTime = null;
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
		if (state === STATE.READY_PLAYING) return now() - ctx.startTime;
		else return ctx.pauseElapsedTime ?? 0;
	}
	function getCurrentTime() {
		return getCurrentTimeMs() / 1e3;
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
		pausePlaybackClock();
		if (time !== void 0) ctx.pauseElapsedTime = time;
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
		cancelScheduledRecordingEvent();
		ctx.playCount++;
		const generation = ++ctx.positionGeneration;
		try {
			const segment = await getRequiredSegment(0, generation, () => {
				enqueueDriverEvent(EVENT.SEGMENT_WAITING, { time: ctx.duration });
			});
			if (generation !== ctx.positionGeneration) return;
			activateSegment(0, segment);
			resetTerminalFromSnapshot(segment, true);
			ctx.pauseElapsedTime = 0;
			ctx.startTime = now();
			prefetchNextSegment();
			if (ctx.audioElement && ctx.audioSeekable) ctx.audioElement.currentTime = 0;
			if (state === STATE.READY_BUFFERING_TO_RESUME || state === STATE.READY_BUFFERING_WHILE_PAUSED) await sendDriverEvent(EVENT.SEGMENT_READY);
			else {
				ctx.pauseElapsedTime = null;
				scheduleNextRecordingEvent();
			}
		} catch {}
	}
	function finishPlayback() {
		cancelScheduledRecordingEvent();
		ctx.playCount++;
		ctx.pauseElapsedTime = ctx.duration;
		if (ctx.audioElement) ctx.audioElement.pause();
		retainSegments([ctx.segmentIndex - 1, ctx.segmentIndex]);
		dispatch("ended");
	}
	function teardown() {
		ctx.positionGeneration++;
		ctx.segmentCache.clear();
		cancelPendingTimers();
		return teardownAudio();
	}
	return {
		init,
		stop,
		getDuration,
		getCurrentTime,
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
	const getCurrentTime = () => {
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
		getCurrentTime().forEach((seq) => {
			dispatch("output", seq);
		});
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
		},
		getCurrentTime: () => {
			const d = /* @__PURE__ */ new Date();
			return d.getHours() * 60 + d.getMinutes();
		}
	};
}
function random(_src, { dispatch }, { speed }) {
	const base = " ".charCodeAt(0);
	const range = "~".charCodeAt(0) - base;
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
			dispatch("playing");
			schedule();
		},
		stop() {
			clearInterval(timeoutId);
		}
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
	let data;
	let byteCount = 0;
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
			const startTime = performance.now();
			for (let i = 0; i < iterations; i++) {
				for (const [_, text] of data) dispatch("output", text);
				dispatch("output", "\x1Bc");
			}
			const duration = (performance.now() - startTime) / 1e3;
			const throughput = byteCount * iterations / duration;
			const throughputMbs = byteCount / (1024 * 1024) * iterations / duration;
			console.info("benchmark: result", {
				byteCount,
				iterations,
				duration,
				throughput,
				throughputMbs
			});
			setTimeout(() => {
				dispatch("ended");
			}, 0);
			return true;
		}
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
	let socket;
	let buf;
	let clock = new NullClock();
	let reconnectAttempt = 0;
	let successfulConnectionTimeout;
	let stop = false;
	let wasOnline = false;
	let gotExitEvent = false;
	let gotEotEvent = false;
	let initTimeout;
	let audioElement;
	function connect() {
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
			stopBuffer();
			if (stop) return;
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
				clearTimeout(successfulConnectionTimeout);
				const delay = reconnectDelay(reconnectAttempt++);
				logger.info(`unexpected close, reconnecting in ${delay}...`);
				dispatch("loading");
				setTimeout(connect, delay);
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
		buf = getBuffer(bufferTime, dispatch, (t) => clock.setTime(t), time, minFrameTime, logger);
		dispatch("reset", {
			size: {
				cols,
				rows
			},
			init,
			theme: theme ?? null
		});
		clock = new Clock();
		wasOnline = true;
		gotExitEvent = false;
		gotEotEvent = false;
		if (typeof time === "number") clock.setTime(time);
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
		clock = new NullClock();
	}
	function stopBuffer() {
		if (buf) buf.stop();
		buf = null;
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
			stopBuffer();
			if (socket !== void 0) socket.close();
			stopAudio();
		},
		mute,
		unmute,
		getCurrentTime: () => {
			const t = clock.getTime();
			return typeof t === "number" ? t / 1e3 : t;
		}
	};
}
function eventsource({ url, bufferTime, minFrameTime }, { dispatch, logger }) {
	logger = new PrefixedLogger(logger, "eventsource: ");
	let es;
	let buf;
	let clock = new NullClock();
	function initBuffer(baseStreamTime) {
		if (buf !== void 0) buf.stop();
		buf = getBuffer(bufferTime, dispatch, (t) => clock.setTime(t), baseStreamTime, minFrameTime, logger);
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
					clock = new Clock();
					if (time !== void 0) clock.setTime(time);
					dispatch("playing");
				} else if (e.state === "offline") {
					logger.info("stream offline");
					dispatch("offline", { message: "Stream offline" });
					clock = new NullClock();
				}
			});
			es.addEventListener("done", () => {
				logger.info("closed");
				es.close();
				dispatch("ended", { message: "Stream ended" });
			});
			return true;
		},
		stop: () => {
			if (buf !== void 0) buf.stop();
			if (es !== void 0) es.close();
		},
		getCurrentTime: () => {
			const t = clock.getTime();
			return typeof t === "number" ? t / 1e3 : t;
		}
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
			["seeked", []]
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
		if (this.driver.getCurrentTime === void 0) {
			const play = this.driver.play;
			let clock = new NullClock();
			this.driver.play = () => {
				clock = new Clock(this.speed);
				return play();
			};
			this.driver.getCurrentTime = () => {
				const t = clock.getTime();
				return typeof t === "number" ? t / 1e3 : t;
			};
		}
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
		return this.driver.getCurrentTime();
	}
	getRemainingTime() {
		const duration = this.getDuration();
		if (typeof duration === "number") return duration - Math.min(this.getCurrentTime(), duration);
	}
	getProgress() {
		const duration = this.getDuration();
		if (typeof duration === "number") return Math.min(this.getCurrentTime(), duration) / duration;
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
	if (typeof src === "string") if (src.substring(0, 5) == "ws://" || src.substring(0, 6) == "wss://") src = {
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
	if (src.driver === void 0) src.driver = "recording";
	if (src.driver == "recording") {
		if (src.format !== "segmented" && src.parser === void 0) src.parser = "asciicast";
		if (typeof src.parser === "string") if (PARSERS.has(src.parser)) src.parser = PARSERS.get(src.parser);
		else throw new Error(`unknown parser: ${src.parser}`);
	}
	if (DRIVERS.has(src.driver)) {
		const driver = DRIVERS.get(src.driver);
		return (callbacks, opts) => driver(src, callbacks, opts);
	} else throw new Error(`unsupported driver: ${JSON.stringify(src)}`);
}
//#endregion
//#region ../../node_modules/.pnpm/asciinema-player@3.17.0/node_modules/asciinema-player/dist/opts-Dj5f5MR1.js
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
	}, updateFn = unowned ? fn : () => fn(() => untrack(() => cleanNode(root)));
	Owner = root;
	Listener = null;
	try {
		return runUpdates(updateFn, true);
	} finally {
		Listener = listener;
		Owner = owner;
	}
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
function startTransition(fn) {
	const l = Listener;
	const o = Owner;
	return Promise.resolve().then(() => {
		Listener = l;
		Owner = o;
		runUpdates(fn, false);
		Listener = Owner = null;
	});
}
var [transPending] = /*@__PURE__*/ createSignal(false);
function useTransition() {
	return [transPending, startTransition];
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
	if (this.sources && this.state) if (this.state === STALE) updateComputation(this);
	else {
		const updates = Updates;
		Updates = null;
		runUpdates(() => lookUpstream(this), false);
		Updates = updates;
	}
	if (Listener) {
		const sSlot = this.observers ? this.observers.length : 0;
		if (!Listener.sources) {
			Listener.sources = [this];
			Listener.sourceSlots = [sSlot];
		} else {
			Listener.sources.push(this);
			Listener.sourceSlots.push(sSlot);
		}
		if (!this.observers) {
			this.observers = [Listener];
			this.observerSlots = [Listener.sources.length - 1];
		} else {
			this.observers.push(Listener);
			this.observerSlots.push(Listener.sources.length - 1);
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
	else if (Owner !== UNOWNED) if (!Owner.owned) Owner.owned = [c];
	else Owner.owned.push(c);
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
			Array.isArray(result) ? results.push.apply(results, result) : results.push(result);
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
			if (index != null) if (bStart < index && index < bEnd) {
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
			else a[aStart++].remove();
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
	const fn = isImportNode ? () => untrack(() => document.importNode(node || (node = create()), true)) : () => (node || (node = create())).cloneNode(true);
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
function addEventListener(node, name, handler, delegate) {
	if (Array.isArray(handler)) {
		node[`$$${name}`] = handler[0];
		node[`$$${name}Data`] = handler[1];
	} else node[`$$${name}`] = handler;
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
		} else if (currentArray) if (current.length === 0) appendNodes(parent, array, marker);
		else reconcileArrays(parent, current, array);
		else {
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
		else if (t === "function") if (unwrap) {
			while (typeof item === "function") item = item();
			dynamic = normalizeIncomingArray(normalized, Array.isArray(item) ? item : [item], Array.isArray(prev) ? prev : [prev]) || dynamic;
		} else {
			normalized.push(item);
			dynamic = true;
		}
		else {
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
var noop = () => {};
var noopTransition = (el, done) => done();
/**
* Create an element transition interface for switching between single elements.
* It can be used to implement own transition effect, or a custom `<Transition>`-like component.
*
* It will observe {@link source} and return a signal with array of elements to be rendered (current one and exiting ones).
*
* @param source a signal with the current element. Any nullish value will mean there is no element.
* Any object can used as the source, but most likely you will want to use a `HTMLElement` or `SVGElement`.
* @param options transition options {@link SwitchTransitionOptions}
* @returns a signal with an array of the current element and exiting previous elements.
*
* @see https://github.com/solidjs-community/solid-primitives/tree/main/packages/transition-group#createSwitchTransition
*
* @example
* const [el, setEl] = createSignal<HTMLDivElement>();
*
* const rendered = createSwitchTransition(el, {
*   onEnter(el, done) {
*     // the enter callback is called before the element is inserted into the DOM
*     // so run the animation in the next animation frame / microtask
*     queueMicrotask(() => { ... })
*   },
*   onExit(el, done) {
*     // the exitting element is kept in the DOM until the done() callback is called
*   },
* })
*
* // change the source to trigger the transition
* setEl(refToHtmlElement);
*/
function createSwitchTransition(source, options) {
	const initSource = untrack(source);
	const initReturned = initSource ? [initSource] : [];
	const { onEnter = noopTransition, onExit = noopTransition } = options;
	const [returned, setReturned] = createSignal(options.appear ? [] : initReturned);
	const [isTransitionPending] = useTransition();
	let next;
	let isExiting = false;
	function exitTransition(el, after) {
		if (!el) return after && after();
		isExiting = true;
		onExit(el, () => {
			batch(() => {
				isExiting = false;
				setReturned((p) => p.filter((e) => e !== el));
				after && after();
			});
		});
	}
	function enterTransition(after) {
		const el = next;
		if (!el) return after && after();
		next = void 0;
		setReturned((p) => [el, ...p]);
		onEnter(el, after ?? noop);
	}
	const triggerTransitions = options.mode === "out-in" ? (prev) => isExiting || exitTransition(prev, enterTransition) : options.mode === "in-out" ? (prev) => enterTransition(() => exitTransition(prev)) : (prev) => {
		exitTransition(prev);
		enterTransition();
	};
	createComputed((prev) => {
		const el = source();
		if (untrack(isTransitionPending)) {
			isTransitionPending();
			return prev;
		}
		if (el !== prev) {
			next = el;
			batch(() => untrack(() => triggerTransitions(prev)));
		}
		return el;
	}, options.appear ? void 0 : initSource);
	return returned;
}
/**
* Default predicate used in `resolveElements()` and `resolveFirst()` to filter Elements.
*
* On the client it uses `instanceof Element` check, on the server it checks for the object with `t` property. (generated by compiling JSX)
*/
var defaultElementPredicate = (item) => item instanceof Element;
/**
* Utility for resolving recursively nested JSX children in search of the first element that matches a predicate.
*
* It does **not** create a computation - should be wrapped in one to repeat the resolution on changes.
*
* @param value JSX children
* @param predicate predicate to filter elements
* @returns single found element or `null` if no elements were found
*/
function getFirstChild(value, predicate) {
	if (predicate(value)) return value;
	if (typeof value === "function" && !value.length) return getFirstChild(value(), predicate);
	if (Array.isArray(value)) for (const item of value) {
		const result = getFirstChild(item, predicate);
		if (result) return result;
	}
	return null;
}
function resolveFirst(fn, predicate = defaultElementPredicate, serverPredicate = defaultElementPredicate) {
	const children = createMemo(fn);
	return createMemo(() => getFirstChild(children(), predicate));
}
function createClassnames(props) {
	return createMemo(() => {
		const name = props.name || "s";
		return {
			enterActive: (props.enterActiveClass || name + "-enter-active").split(" "),
			enter: (props.enterClass || name + "-enter").split(" "),
			enterTo: (props.enterToClass || name + "-enter-to").split(" "),
			exitActive: (props.exitActiveClass || name + "-exit-active").split(" "),
			exit: (props.exitClass || name + "-exit").split(" "),
			exitTo: (props.exitToClass || name + "-exit-to").split(" "),
			move: (props.moveClass || name + "-move").split(" ")
		};
	});
}
function nextFrame(fn) {
	requestAnimationFrame(() => requestAnimationFrame(fn));
}
function enterTransition(classes, events, el, done) {
	const { onBeforeEnter, onEnter, onAfterEnter } = events;
	onBeforeEnter?.(el);
	el.classList.add(...classes.enter);
	el.classList.add(...classes.enterActive);
	queueMicrotask(() => {
		if (!el.parentNode) return done?.();
		onEnter?.(el, () => endTransition());
	});
	nextFrame(() => {
		el.classList.remove(...classes.enter);
		el.classList.add(...classes.enterTo);
		if (!onEnter || onEnter.length < 2) {
			el.addEventListener("transitionend", endTransition);
			el.addEventListener("animationend", endTransition);
		}
	});
	function endTransition(e) {
		if (!e || e.target === el) {
			done?.();
			el.removeEventListener("transitionend", endTransition);
			el.removeEventListener("animationend", endTransition);
			el.classList.remove(...classes.enterActive);
			el.classList.remove(...classes.enterTo);
			onAfterEnter?.(el);
		}
	}
}
function exitTransition(classes, events, el, done) {
	const { onBeforeExit, onExit, onAfterExit } = events;
	if (!el.parentNode) return done?.();
	onBeforeExit?.(el);
	el.classList.add(...classes.exit);
	el.classList.add(...classes.exitActive);
	onExit?.(el, () => endTransition());
	nextFrame(() => {
		el.classList.remove(...classes.exit);
		el.classList.add(...classes.exitTo);
		if (!onExit || onExit.length < 2) {
			el.addEventListener("transitionend", endTransition);
			el.addEventListener("animationend", endTransition);
		}
	});
	function endTransition(e) {
		if (!e || e.target === el) {
			done?.();
			el.removeEventListener("transitionend", endTransition);
			el.removeEventListener("animationend", endTransition);
			el.classList.remove(...classes.exitActive);
			el.classList.remove(...classes.exitTo);
			onAfterExit?.(el);
		}
	}
}
var TRANSITION_MODE_MAP = {
	inout: "in-out",
	outin: "out-in"
};
var Transition = (props) => {
	const classnames = createClassnames(props);
	return createSwitchTransition(resolveFirst(() => props.children), {
		mode: TRANSITION_MODE_MAP[props.mode],
		appear: props.appear,
		onEnter(el, done) {
			enterTransition(classnames(), props, el, done);
		},
		onExit(el, done) {
			exitTransition(classnames(), props, el, done);
		}
	});
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
	const ret = wasm.create(cols, rows, scrollback_limit, bold_is_bright);
	return Vt$1.__wrap(ret);
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
	if (typeof module !== "undefined") if (Object.getPrototypeOf(module) === Object.prototype) ({module} = module);
	else console.warn("using deprecated parameters for `initSync()`; pass a single object instead");
	const imports = __wbg_get_imports();
	if (!(module instanceof WebAssembly.Module)) module = new WebAssembly.Module(module);
	return __wbg_finalize_init(new WebAssembly.Instance(module, imports), module);
}
async function __wbg_init(module_or_path) {
	if (wasm !== void 0) return wasm;
	if (typeof module_or_path !== "undefined") if (Object.getPrototypeOf(module_or_path) === Object.prototype) ({module_or_path} = module_or_path);
	else console.warn("using deprecated parameters for the initialization function; pass a single object instead");
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
var vtWasmModule = base64Decode("AGFzbQEAAAABnAEXYAJ/fwBgA39/fwBgAX8AYAF/AX9gBX9/f39/AGACf38Bf2ADf39/AX9gBH9/f38AYAR/f39/AX9gBn9/f39/fwBgAAF/YAV/f39/fwF/YAF8AX9gAX4Bf2AHf39/f39/fwBgA39/fgF/YAR/f39+AGADf35/AGAGf39/f39/AX9gBX9/fH9/AGAFf39+f38AYAV/f31/fwBgAAAC6wIKA3diZxpfX3diZ19uZXdfMTMzMTdlZDE2MTg5MTU4ZQAKA3diZxpfX3diZ19zZXRfOGI2YTlhNjFlOThhODg4MQABA3diZxpfX3diaW5kZ2VuX29iamVjdF9kcm9wX3JlZgACA3diZxtfX3diaW5kZ2VuX29iamVjdF9jbG9uZV9yZWYAAwN3YmcaX193Ymdfc2V0XzNmMWQwYjk4NGVkMjcyZWQAAQN3YmcaX193YmdfbmV3XzRjZWI2YTc2NmJmNzhiMDQACgN3YmcnX193YmdfX193YmluZGdlbl90aHJvd19kZDI0NDE3ZWQzNmZjNDZlAAADd2JnIF9fd2JpbmRnZW5fY2FzdF9kNmNkMTliODE1NjBmZDZlAAwDd2JnIF9fd2JpbmRnZW5fY2FzdF80NjI1YzU3N2FiMmVjOWVlAA0Dd2JnIF9fd2JpbmRnZW5fY2FzdF8yMjQxYjZhZjRjNGIyOTQxAAUDpgGkAQYABgEAAgELBQEGBQYBCA4EBgkEAAkBAAgBCQQBAQcBAgEHAwAGBQQAAQkHBwAAAQEAAAAPAAMBAQEAAwMCBQAHAAAAAQIDAwECAQAABAIABgEQAgAEAAEACQQCAAEAAAAAAgcFBREBBQIDBAEECAAAAAAAAQIAAgEAAAAIAQgSBBMLFBUDBwUCAgIBAgAAAgIAAQACAAAAAQEBAgMWAAACAAACBAUBcAElJQUDAQARBgkBfwFBgIDAAAsHxAEMBm1lbW9yeQIADV9fd2JnX3Z0X2ZyZWUANwZjcmVhdGUAGAd2dF9mZWVkAAoJdnRfcmVzaXplAC8KdnRfZ2V0U2l6ZQBeCnZ0X2dldExpbmUADAx2dF9nZXRDdXJzb3IALRFfX3diaW5kZ2VuX2V4cG9ydABuEl9fd2JpbmRnZW5fZXhwb3J0MgB4H19fd2JpbmRnZW5fYWRkX3RvX3N0YWNrX3BvaW50ZXIApgESX193YmluZGdlbl9leHBvcnQzAJwBCTsBAEEBCyQSBwgJEhISEowBiQE0igGMARaQAYoBigGOAYsBjQGsAakBqgESqwGfARJUrQFphQESVBYSEgwBIArQtAKkAa01ARB/IwBBoAFrIgQkACAEQTBqIAAQVSAEKAIwIQMgBEEoaiIAIAI2AgQgACABNgIAIANB3ABqIQsgA0HQAGohDCADQTBqIQ8gA0EkaiEQIANBDGohESADQbIBaiEHIANBxAFqIQkgBCgCKCINIAQoAiwiDmohEiANIQIDQAJAAkACQAJAAkACQCADAn8CQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAIAIgEkYNAAJ/IAIsAAAiAEEATgRAIABB/wFxIQAgAkEBagwBCyACLQABQT9xIQUgAEEfcSEBIABBX00EQCABQQZ0IAVyIQAgAkECagwBCyACLQACQT9xIAVBBnRyIQUgAEFwSQRAIAUgAUEMdHIhACACQQNqDAELIAFBEnRBgIDwAHEgAi0AA0E/cSAFQQZ0cnIiAEGAgMQARg0BIAJBBGoLIQJBwQAgACAAQZ8BSxshAQJAAkACQCADLQDMBSIGDgUABAQEAQQLIAFBIGtB4ABJDQEMAwsgAUEwa0EMTw0CDCALIAQgADYCQCAEQSE6ADwMAgsgBEHwAGoiASADQeAAaigCACADQeQAaigCABAgIARBCGogAxAhIAQgBCkDCDcCfCAEIAQoAnQgBCgCeBBSIAQoAgQhACAEKAIAQQFxRQRAIAEQbCAOBEAgDSAOEDsLIAQoAjQgBCgCOBChASAEQaABaiQAIAAPCyAEIAA2AkwgBEHMAGpB3MLAABA8AAsCQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkAgAUH/AXEiBUEbRwRAIAVB2wBGDQEgBg4NAwQFBgcOCA4ODgIOCQ4LIANBAToAzAUgCRAqDFQLIAYODQEjAwQFDQYNDQ0ADQcNCyABQSBrQd8ASQ1SDAsLAkAgAUEYSQ0AIAFBGUYNACABQfwBcUEcRw0LCyAEQTxqIAAQPwwyCyABQfABcUEgRg0GIAFBMGtBIEkNCCABQdEAa0EHSQ0IAkAgBUHZAGsOBQkJAAkfAAsgAUHgAGtBH08NCQwICyABQTBrQc8ATw0IIANBADoAzAUgBEE8aiAJIAAQKwwwCyABQS9LBEAgAUE7RyABQTpPcUUEQCADQQQ6AMwFDE8LIAFBQGpBP0kNBAsgAUH8AXFBPEcNByADIAA2AsQBIANBBDoAzAUMTgsgAUFAakE/SQ0EIAFB/AFxQTxHDQYMSwsgAUFAakE/Tw0FDEkLIAFBIGtB4ABJDUsCQCAFQRhrDgMHBgcACyAFQZkBa0ECSQ0GIAVB0ABGDUsgBUEHRg1IDAULIANBADoAzAUgBEE8aiAJIAAQDQwrCyADIAA2AsQBIANBAjoAzAUMSQsgA0EAOgDMBSAEQTxqIAkgABANDCkLIANBADoAzAUgBEE8aiAJIAAQKwwoCwJAIAVBGGsOAwIBAgALIAVBmQFrQQJJDQEgBUHQAEcNACAGQQFrDgoVAwgJCiQLDA0ORgsgAUHwAXEiCEGAAUYNACABQZEBa0EGSw0BCyADQQA6AMwFIARBPGogABA/DCULIAhBIEcNASAGQQRHDQEMPwsgAUHwAXEhCAwBCyAGQQFrDgoBAAMEBQ4GBwgJDgsgCEEgRw0BDDsLIAFBGE8NCgwLCwJAIAFBGEkNACABQRlGDQAgAUH8AXFBHEcNDAsgBEE8aiAAED8MHwsCQAJAIAFBGEkNACABQRlGDQAgAUH8AXFBHEcNAQsgBEE8aiAAED8MHwsgAUHwAXFBIEYNOQwKCwJAIAFBGEkNACABQRlGDQAgAUH8AXFBHEcNCgsgBEE8aiAAED8MHQsgAUFAakE/TwRAIAFB8AFxIghBIEYNNyAIQTBGDToMCQsgA0EAOgDMBSAEQTxqIAkgABANDBwLIAFB/AFxQTxGDQMgAUHwAXFBIEYNLyABQUBqQT9PDQcMBAsgAUEvTQ0GIAFBOkkNOCABQTtGDTggAUFAakE+TQ0DDAYLIAFBQGpBP0kNAgwFCyABQRhJDTcgAUEZRg03IAFB/AFxQRxGDTcMBAsgAyAANgLEASADQQg6AMwFDDYLIANBCjoAzAUMNQsgBUHYAGsiCEEHTUEAQQEgCHRBwQFxGw0FIAVBGUYNACABQfwBcUEcRw0BCyAEQTxqIAAQPwwUCyAFQZABaw4QAQUFBQUFBQUDBQUCLwADAwQLIANBDDoAzAUMMQsgA0EHOgDMBSAJECoMMAsgA0EDOgDMBSAJECoMLwsgA0ENOgDMBQwuCwJAIAVBOmsOAgQCAAsgBUEZRg0CCyAGQQNrDgcJLAMKBQsHLAsgBkEDaw4HCCsrCQUKBysLIAZBA2sOBwcqAggqCQYqCyAGQQNrDgcGKSkHCQgFKQsgAUEYSQ0AIAFB/AFxQRxHDSgLIARBPGogABA/DAgLIAFBMGtBCk8NJgsgA0EIOgDMBQwkCyABQfABcUEgRg0fCyABQfABcUEwRw0jDAMLIAFBOkcNIgwgCwJAIAFBGEkNACABQRlGDQAgAUH8AXFBHEcNIgsgBEE8aiAAED8MAgsgAUHwAXFBIEYNFSABQTpGDQAgAUH8AXFBPEcNIAsgA0ELOgDMBQwfCyAELQA8IgBBMkYNHwJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkAgAEEBaw4xAgMEBQYHCAkKCwwNDg8lECYREhMUFRYXGBkaGxwdHh8AISIjJCUmJygpKissLTAxMgELIAQoAkAhAAwfCyADQX5BfyADKAJoIAMoApwBRhsQeww9CyAELwE+IQAgBCADKAJoNgJMIARBADoAfCAEIANB1ABqKAIAIgE2AnAgBCABIAMoAlhBAnRqNgJ0QQEgACAAQQFNGyEAIAQgBEHMAGo2AngDQCAAQQFrIgAEQCAEQfAAahBGDQEMNgsLIARB8ABqEEYiAEUNNCAAKAIADDULIANBASAELwE+IgAgAEEBTRtBAWsiACADKAKcASIBQQFrIAAgAUkbNgJoDDsLIANBASAELwE+IgAgAEEBTRsQLgw6CyADQQEgBC8BPiIAIABBAU0bEFYgA0EANgJoDDkLIANBASAELwE+IgAgAEEBTRsQWSADQQA2AmgMOAsgA0EANgJoDDcLAkAgBC0APUEBaw4CJgATCyADQQA2AlgMNgsgA0EBIAQvAT4iACAAQQFNGyIAQX9zQQAgAGsgAygCaCADKAKcAUYbEHsMNQsgA0EBIAQvAT4iACAAQQFNGxBWDDQLIANBASAELwE+IgAgAEEBTRsQewwzCyADQQEgBC8BQCIAIABBAU0bQQFrIgAgAygCnAEiAUEBayAAIAFJGzYCaCADQQEgBC8BPiIAIABBAU0bQQFrEEkMMgsgA0EBIAQvAT4iACAAQQFNGxBZDDELIAMoAmgiACADKAKcASIBTwRAIAMgAUEBayIANgJoC0EBIAQvAT4iASABQQFNGyIBIAMoAhggAGsiBSABIAVJGyEBIAMgAygCbEGwzcAAEFoiBSgCBCAFKAIIIABBqNnAABCGASgCBEUEQCAFKAIEIAUoAgggAEEBa0G42cAAEIYBIgZCoICAgBA3AgAgBiAHKQEANwEIIAZBEGogB0EIai8BADsBAAsgBEEYaiAFKAIEIAUoAgggAEHI2cAAEHUgBCgCGCAEKAIcIAEQfiAFKAIEIAUoAgggAEHY2cAAEIYBIgAoAgRFBEAgAEKggICAEDcCACAAIAcpAQA3AQggAEEQaiAHQQhqLwEAOwEACyAEQRBqIAUoAgQgBSgCCCIAIAAgAWtB6NnAABB1IAQoAhAhACAEKAIUIARB+ABqIAdBCGovAQA7AQAgBCAHKQEANwNwQRRsIQEDQCABBEAgAEKggICAEDcCACAAIAQpA3A3AgggAEEQaiAEQfgAai8BADsBACABQRRrIQEgAEEUaiEADAELCyAFQQA6AAwgA0HgAGooAgAgA0HkAGooAgAgAygCbBCHAQwwCyADKAKcASEFIAMoAqABIQZBACEBA0AgASAGRg0wQQAhAANAIAAgBUYEQCADQeAAaigCACADQeQAaigCACABEIcBIAFBAWohAQwCBSAEQQA7AHggBEECOgB0IARBAjoAcCADIAAgAUHFACAEQfAAahARGiAAQQFqIQAMAQsACwALAAsgBCgCSCEBIAQoAkQhACAEIAQoAkA2AnggBCAANgJwIAQgAUEBdCIBIABqIgU2AnwDQCABBEACQAJAAkACQAJAAkACQAJAAkACQCAALwEAIgZBAWsOBwExMTExAgMACyAGQZcIaw4DBAUGAwsgA0EAOgDBAQwHCyADQgA3AmggA0EAOgC+AQwGCyADQQA6AL8BDAULIANBADoAcAwECyADEGUMAgsgAxB/DAILIAMQZSADEH8LIAMQDwsgAEECaiEAIAFBAmshAQwBCwsgBCAFNgJ0IARB8ABqEJ4BDC4LIAQoAkghASAEKAJEIQAgBCAEKAJANgJ4IAQgADYCcCAEIAFBAXQiASAAaiIGNgJ8A0AgAQRAAkACQAJAAkACQAJAAkACQAJAIAAvAQAiBUEBaw4HAS8vLy8CAwALIAVBlwhrDgMGBAUDCyADQQE6AMEBDAYLIANBAToAvgEgA0EANgJoIAMgAygCqAE2AmwMBQsgA0EBOgC/AQwECyADQQE6AHAMAwsgAxBdDAILIAMQXQsjAEEwayIFJAAgAy0AvAFFBEAgA0EBOgC8ASADQfQAaiADQYgBahBqIAMgA0EkahBrIAVBDGoiCCADKAKcASADKAKgASIKQQFBACADQbIBahAcIANBDGoQlAEgAyAIQSQQFCIIKAJgIAgoAmRBACAKEEoLIAVBMGokACADEA8LIABBAmohACABQQJrIQEMAQsLIAQgBjYCdCAEQfAAahCeAQwtCwJAQQEgBC8BPiIAIABBAU0bQQFrIgAgBC8BQCIBIAMoAqABIgUgARtBAWsiAUkgASAFSXFFBEAgAygCqAEhAAwBCyADIAE2AqwBIAMgADYCqAELIANBADYCaCADIABBACADLQC+ARs2AmwMLAsgA0EBOgBwIANBADsAvQEgA0EAOwG6ASADQQI6ALYBIANBAjoAsgEgA0EAOwGwASADQgA3AqQBIANBgICACDYChAEgA0ECOgCAASADQQI6AHwgA0IANwJ0IAMgAygCoAFBAWs2AqwBDCsLIAMoAqABIAMoAqwBIgBBAWogACADKAJsIgBJGyEBIAMgACABQQEgBC8BPiIFIAVBAU0bIAcQGiADQeAAaigCACADQeQAaigCACAAIAEQSgwqCyADIAMoAmggAygCbCIAQQBBASAELwE+IgEgAUEBTRsgBxAfIANB4ABqKAIAIANB5ABqKAIAIAAQhwEMKQsCQAJAAkAgBC0APUEBaw4DAQIrAAsgAyADKAJoIAMoAmwiAEEBIAQgBxAfIANB4ABqKAIAIANB5ABqKAIAIAAgAygCoAEQSgwqCyADIAMoAmggAygCbCIAQQIgBCAHEB8gA0HgAGooAgAgA0HkAGooAgBBACAAQQFqEEoMKQsgA0EAIAMoAhwgBxAoIANB4ABqKAIAIANB5ABqKAIAQQAgAygCoAEQSgwoCyADIAMoAmggAygCbCIAIAQtAD1BBHIgBCAHEB8gA0HgAGooAgAgA0HkAGooAgAgABCHAQwnCyADIAQtAD06ALEBDCYLIAMgBC0APToAsAEMJQsgA0EBEC4MJAsjAEEQayIFJAACQAJAAkAgAygCaCIIRQ0AIAggAygCnAFPDQAgBUEIaiADKAJUIgAgAygCWCIBIAgQNSAFKAIIQQFHDQAgBSgCDCIGIAFLDQEgA0HQAGoiCigCACABRgR/IApBvOLAABBiIAMoAlQFIAALIAZBAnRqIQAgASAGSwRAIABBBGogACABIAZrQQJ0EBALIAAgCDYCACADIAFBAWo2AlgLIAVBEGokAAwBCyAGIAFBvOLAABBDAAsMIwsgAygCaCIAIAMoApwBIgVGBEAgAyAAQQFrIgA2AmgLIAMgACADKAJsIgFBASAELwE+IgYgBkEBTRsiBiAFIABrIgUgBSAGSxsiBSAHEB0gACAAIAVqIgUgACAFSxshBQNAIAAgBUcEQCADIAAgAUEgIAcQERogAEEBaiEADAELCyADQeAAaigCACADQeQAaigCACABEIcBDCILIAMoAqABIAMoAqwBIgBBAWogACADKAJsIgBJGyEBIAMgACABQQEgBC8BPiIFIAVBAU0bIAcQMSADQeAAaigCACADQeQAaigCACAAIAEQSgwhCyADEFMgAy0AwAFBAUcNICADQQA2AmgMIAsgAxBTIANBADYCaAwfCyADIAAQHgweCyADKAJoIgVFDR0gBC8BPiEAIAMoAmwhASAEQSBqIAMQZiAEKAIkIgYgAU0NEkEBIAAgAEEBTRshACAEKAIgIAFBBHRqIgFBBGooAgAgAUEIaigCACAFQQFrQbjlwAAQhgEoAgAhAQNAIABFDR4gAyABEB4gAEEBayEADAALAAsgAygCbCIAIAMoAqgBRg0SIABFDRwgAyAAQQFrEEkMHAsgBEHMAGoiACADKAKcASIFIAMoAqABIgEgAygCSCADKAJMQQAQHCAEQfAAaiIGIAUgAUEBQQBBABAcIBEQlAEgAyAAQSQQFCEAIA8QlAEgECAGQSQQFBogAEEAOgC8ASAEQZQBaiIGIAUQMiAAKAJQIABB1ABqKAIAQQQQlQEgDEEIaiAGQQhqIgUoAgA2AgAgDCAEKQKUATcCACAAQQA7AboBIABBAjoAtgEgAEECOgCyASAAQQE6AHAgAEIANwJoIABBADsBsAEgAEGAgAQ2AL0BIAAgAUEBazYCrAEgAEIANwKkASAAQYCAgAg2ApgBIABBAjoAlAEgAEECOgCQASAAQQA2AowBIABCgICACDcChAEgAEECOgCAASAAQQI6AHwgAEIANwJ0IAYgARBMIAAoAlwgAEHgAGooAgBBARCVASALQQhqIAUoAgA2AgAgCyAEKQKUATcCAAwbCyAEKAJIIQEgBCgCRCEAIAQgBCgCQDYCeCAEIAA2AnAgBCABQQF0IgEgAGoiBTYCfANAIAEEQAJAIAAvAQBBFEcEQCADQQA6AL0BDAELIANBADoAwAELIABBAmohACABQQJrIQEMAQsLIAQgBTYCdCAEQfAAahCeAQwaCyADEH8MGQsgAxBdDBgLIANBASAELwE+IgAgAEEBTRsQfAwXCyAEKAJIQQVsIQEgAy0AuwEhBSAEKAJAIAQoAkQiCiEAA0ACQCABRQ0AIAAoAAEhBgJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAIAAtAABBAWsOEgECAwQFBgcICQoLDA0ODxAREwALQQAhBSADQQA7AboBIANBAjoAtgEgA0ECOgCyAQwRCyADQQE6ALoBDBALIANBAjoAugEMDwsgAyAFQQFyIgU6ALsBDA4LIAMgBUECciIFOgC7AQwNCyADIAVBCHIiBToAuwEMDAsgAyAFQRByIgU6ALsBDAsLIAMgBUEEciIFOgC7AQwKCyADQQA6ALoBDAkLIAMgBUH+AXEiBToAuwEMCAsgAyAFQf0BcSIFOgC7AQwHCyADIAVB9wFxIgU6ALsBDAYLIAMgBUHvAXEiBToAuwEMBQsgAyAFQfsBcSIFOgC7AQwECyAHIAY2AQAMAwsgB0ECOgAADAILIAMgBjYBtgEMAQsgA0ECOgC2AQsgAEEFaiEAIAFBBWshAQwBCwsgCkEFEJUBDBYLIANBADYCpAEMFQsgBCgCSCEBIAQoAkQhACAEIAQoAkA2AnggBCAANgJwIAQgAUEBdCIBIABqIgU2AnwDQCABBEACQCAALwEAQRRHBEAgA0EBOgC9AQwBCyADQQE6AMABCyAAQQJqIQAgAUECayEBDAELCyAEIAU2AnQgBEHwAGoQngEMFAsgA0EBNgKkAQwTCyADQQEgBC8BPiIAIABBAU0bEH0MEgsgBC0APQ0BCyMAQRBrIgAkACAAQQhqIAMoAlQiBiADKAJYIgEgAygCaBA1AkACQCAAKAIIRQRAIAAoAgwiBSABTw0BIAYgBUECdGoiBiAGQQRqIAEgBUF/c2pBAnQQECADIAFBAWs2AlgLIABBEGokAAwBCyMAQTBrIgAkACAAIAE2AgQgACAFNgIAIABBAzYCDCAAQcjFwAA2AgggAEICNwIUIAAgAEEEaq1CgICAgIABhDcDKCAAIACtQoCAgICAAYQ3AyAgACAAQSBqNgIQIABBCGpBzOLAABCAAQALDBALIANBADYCWAwPCyADQQEgBC8BPiIAIABBAU0bQQFrEEkMDgsgA0EBIAQvAT4iACAAQQFNGxBWDA0LIAMtAMIBQQFHDQwgAyAELwE+IgAgAygCnAEgABsgBC8BQCIAIAMoAqABIAAbECMMDAsgAyAANgLEASADQQk6AMwFDAoLIAEgBkG45cAAEEIACyADQQEQfAwJCwALQQALIgAgAygCnAEiAUEBayAAIAFJGzYCaAwGCyAJIAA2AgAMBAsgAyAANgLEASADQQU6AMwFDAMLIANBADoAzAUMAgsgA0EGOgDMBQwBCyAJKAKEBCEBAkACQAJAAkACQCAAQTprDgIBAAILIAlBHyABQQFqIgAgAEEgRhs2AoQEDAMLIAFBIEkNASABQSBB5NvAABBCAAsgAUEgTwRAIAFBIEH028AAEEIACyAJIAFBBHRqQQRqIgUoAgAiAUEGSQRAIAUgAUEBdGpBBGoiASABLwEAQQpsIABBMGtB/wFxajsBAAwCCyABQQZBtOHAABBCAAsgCSABQQR0akEEaiIBKAIAQQFqIQAgAUEFIAAgAEEFTxs2AgALCyAEQTI6ADwMAAsAC7oUAQZ/IwBBwAJrIgIkACABKAIEIQMDQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAIAMEQCACQbgCaiABKAIAEGAgAigCuAIhAyACKAK8AkEBaw4GAQUEBQIDBQsgAEESOgAADAsLAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAIAMvAQAiAw4eAAECAwQFDgYOBw4ODg4ODg4ODg4OCAgJCgsODA4NDgsgAkGoAWpBASABKAIAIAEoAgRB1NzAABB3IAEgAikDqAE3AgAgAEEAOgAADBgLIAJBsAFqQQEgASgCACABKAIEQeTcwAAQdyABIAIpA7ABNwIAIABBAToAAAwXCyACQbgBakEBIAEoAgAgASgCBEH03MAAEHcgASACKQO4ATcCACAAQQI6AAAMFgsgAkHAAWpBASABKAIAIAEoAgRBhN3AABB3IAEgAikDwAE3AgAgAEEDOgAADBULIAJByAFqQQEgASgCACABKAIEQZTdwAAQdyABIAIpA8gBNwIAIABBBDoAAAwUCyACQdABakEBIAEoAgAgASgCBEGk3cAAEHcgASACKQPQATcCACAAQQU6AAAMEwsgAkHYAWpBASABKAIAIAEoAgRBtN3AABB3IAEgAikD2AE3AgAgAEEGOgAADBILIAJB4AFqQQEgASgCACABKAIEQcTdwAAQdyABIAIpA+ABNwIAIABBBzoAAAwRCyACQegBakEBIAEoAgAgASgCBEHU3cAAEHcgASACKQPoATcCACAAQQg6AAAMEAsgAkHwAWpBASABKAIAIAEoAgRB5N3AABB3IAEgAikD8AE3AgAgAEEJOgAADA8LIAJB+AFqQQEgASgCACABKAIEQfTdwAAQdyABIAIpA/gBNwIAIABBCjoAAAwOCyACQYACakEBIAEoAgAgASgCBEGE3sAAEHcgASACKQOAAjcCACAAQQs6AAAMDQsgAkGIAmpBASABKAIAIAEoAgRBlN7AABB3IAEgAikDiAI3AgAgAEEMOgAADAwLIAJBkAJqQQEgASgCACABKAIEQaTewAAQdyABIAIpA5ACNwIAIABBDToAAAwLCwJAAkAgA0Eea0H//wNxQQhPBEAgA0Emaw4CAQgCCyACQQhqQQEgASgCACABKAIEQcTgwAAQdyABIAIpAwg3AgAgACADQR5rOgACIABBDjsAAAwMCwJAIAEoAgQiA0ECTwRAIAJBmAFqIAEoAgBBEGoQYCACKAKYASIDDQEgASgCBCEDCyACQegAakEBIAEoAgAgA0G03sAAEHcgAigCbCEDIAIoAmghBAwNCwJAAkACQCACKAKcAUEBRw0AIAMvAQBBAmsOBAEAAAIACyACQfAAakEBIAEoAgAgASgCBEGE38AAEHcgAigCdCEDIAIoAnAhBAwOCyABKAIAIQMgASgCBCIEQQVPBEAgAy0AJCEFIAMvATQhBiADLwFEIQcgAkGAAWpBBSADIARBxN7AABB3IAEgAikDgAE3AgAgAEEOOgAAIAAgBSAGQQh0QYD+A3EgB0EQdHJyQQh0QQFyNgABDA0LIAJB+ABqQQIgAyAEQdTewAAQdyACKAJ8IQMgAigCeCEEDA0LIAEoAgAhAyABKAIEIgRBA08EQCADLQAkIQUgAkGQAWpBAyADIARB5N7AABB3IAEgAikDkAE3AgAgACAFOgACIABBDjsAAAwMCyACQYgBakECIAMgBEH03sAAEHcgAigCjAEhAyACKAKIASEEDAwLAkACQCADQfj/A3FBKEcEQCADQTBrDgIBCQILIAJBEGpBASABKAIAIAEoAgRBtODAABB3IAEgAikDEDcCACAAIANBKGs6AAIgAEEQOwAADAwLAkAgASgCBCIDQQJPBEAgAkHYAGogASgCAEEQahBgIAIoAlgiAw0BIAEoAgQhAwsgAkEoakEBIAEoAgAgA0Gk38AAEHcgAigCLCEDIAIoAighBAwNCwJAAkACQCACKAJcQQFHDQAgAy8BAEECaw4EAQAAAgALIAJBMGpBASABKAIAIAEoAgRB9N/AABB3IAIoAjQhAyACKAIwIQQMDgsgASgCACEDIAEoAgQiBEEFTwRAIAMtACQhBSADLwE0IQYgAy8BRCEHIAJBQGtBBSADIARBtN/AABB3IAEgAikDQDcCACAAQRA6AAAgACAFIAZBCHRBgP4DcSAHQRB0cnJBCHRBAXI2AAEMDQsgAkE4akECIAMgBEHE38AAEHcgAigCPCEDIAIoAjghBAwNCyABKAIAIQMgASgCBCIEQQNPBEAgAy0AJCEFIAJB0ABqQQMgAyAEQdTfwAAQdyABIAIpA1A3AgAgACAFOgACIABBEDsAAAwMCyACQcgAakECIAMgBEHk38AAEHcgAigCTCEDIAIoAkghBAwMCyADQdoAa0H//wNxQQhJDQcgA0HkAGtB//8DcUEITw0DIAJBIGpBASABKAIAIAEoAgRBlODAABB3IAEgAikDIDcCACAAIANB3ABrOgACIABBEDsAAAwKCyADLwEAIgRBMEcEQCAEQSZHDQMgAy8BAkECRw0DQQghBEEGIQVBBCEGDAkLIAMvAQJBAkcNAkEIIQRBBiEFQQQhBgwHCyADLwEAIgRBMEcEQCAEQSZHDQIgAy8BAkECRw0CQQohBEEIIQVBBiEGDAgLIAMvAQJBAkcNAUEKIQRBCCEFQQYhBgwGCyADLwEAIgRBMEcEQCAEQSZHDQEgAy8BAkEFRw0BIAMtAAQhAyACQagCakEBIAEoAgAgASgCBEH04MAAEHcgASACKQOoAjcCACAAIAM6AAIgAEEOOwAADAgLIAMvAQJBBUYNAQsgAkEBIAEoAgAgASgCBEGU4cAAEHcgAigCBCEDIAIoAgAhBAwHCyADLQAEIQMgAkGwAmpBASABKAIAIAEoAgRBhOHAABB3IAEgAikDsAI3AgAgACADOgACIABBEDsAAAwFCyACQaABakEBIAEoAgAgASgCBEGU38AAEHcgASACKQOgATcCACAAQQ86AAAMBAsgAkHgAGpBASABKAIAIAEoAgRBhODAABB3IAEgAikDYDcCACAAQRE6AAAMAwsgAkEYakEBIAEoAgAgASgCBEGk4MAAEHcgASACKQMYNwIAIAAgA0HSAGs6AAIgAEEOOwAADAILIAMgBmotAAAhBiADIAVqLwEAIQUgAyAEai8BACEDIAJBoAJqQQEgASgCACABKAIEQeTgwAAQdyABIAIpA6ACNwIAIABBEDoAACAAIAYgBUEIdEGA/gNxIANBEHRyckEIdEEBcjYAAQwBCyACQZgCakEBIAEoAgAgASgCBEHU4MAAEHcgASACKQOYAjcCACADIAZqLQAAIQEgAyAFai8BACEFIAMgBGovAQAhAyAAQQ46AAAgACABIAVBCHRBgP4DcSADQRB0cnJBCHRBAXI2AAELIAJBwAJqJAAPCyABIAQ2AgAgASADNgIEDAALAAuXEwIkfwF+IwBB8ABrIgMkACADQTRqIAAQVSADKAI0IgVBADYCiAYgBUEANgL8BSAFQQA2AvAFIAVBADYC5AUgBUEANgLYBSAFLQBwQQFxBEAgBSgCbCABRiACQQBHcSEhIAUoAmghBgsgA0EoaiAFEGYgAygCLCIAIAFLBEAgBUGABmohHSAFQfwFaiEUIAVB9AVqIR4gBUHwBWohFSAFQegFaiEfIAVB3AVqIRYgBUHQBWohGCADKAIoIAFBBHRqIgEoAgQhACAAIAEoAghBFGxqISIgA0HWAGohIyADQdAAaiIBQQRyISQgBkH//wNxISUgAUEJaiEmQQUhAUEFIQkDQAJAAkACQCAAIgggIkcEQCAIQRRqIQAgCCgCBCIORQ0EIAgoAgAhBiAIQQhqISACQAJAIAMCfwJAICEgJSAPQf//A3EiGUZxIAhBEWoiEC0AAEEQcUEEdkcEQEEBICAoAAAiBEH/AXFBAkYNAhogBEEBcQ0BIARBgP4DcUEDcgwCCyADQQUgCCgADCICQYB+cUEEQQMgAkEBcRtyIAJB/wFxQQJGGyIENgJsQQAhCiAIKAAIIgdB/wFxQQJHDQJBACECDAcLIARBgH5xQQRyCyIENgJsQQIhAiAIKAAMIgdB/wFxQQJHDQFBACEKDAULIAdBCHYhCiAHQQFxDQNBAyECIAdBgPADcQ0EIAUtAIwGQQFHDQQMAgsgB0EIdiEKIAdBAXENAkEDIQIgB0GA8ANxDQMgBS0AjAYNAQwDCyAJQf8BcUEFRwRAIBggEa0gCa1C/wGDQiCGIBqtQiiGhIRB/MLAABBwCyABQf8BcUEFRwRAIAMgCzsAVyADQdkAaiALQRB2OgAAIAMgDDoAWiADIAE6AFYgAyANOwFUIAMgFzYCUCAWIANB0ABqQYzDwAAQWwsgBSgCiAYhASAFKAKEBiECIAUoAvwFIQQgBSgC+AUhCCAFKALwBSEUIAUoAuwFIRUgBSgC5AUhBiAFKALgBSEHIAUoAtgFIQkgBSgC1AUhBSADQQA2AmwgA0EgaiADQewAahAFIgBB38HAAEECIAUgCRAZAkACfyADKAIgBEAgAygCJAwBCyADQRhqIANB7ABqIABB4cHAAEEEIAcgBhAZIAMoAhgEQCADKAIcDAELIANBEGogA0HsAGogAEHlwcAAQQogAiABEBkgAygCEARAIAMoAhQMAQsgA0EIaiADQewAaiAAQe/BwABBDiAVIBQQGSADKAIIBEAgAygCDAwBCyADIANB7ABqIABB/cHAAEEOIAggBBAZIAMoAgBFDQEgAygCBAshASAAEJoBIAMgATYCbCADQewAakGcw8AAEDwACyADKAI4IAMoAjwQoQEgA0HwAGokACAADwsgCkEIciAKIAgtABBBAUYbIQoMAQtBBCECCyADIApBCHRBgP4DcSAHQYCAfHFyIgogAnIiBzYCQCADQQAgA0HsAGoiEiAEQf8BcUEFRiIEGzYCWCADIBGtIAmtQv8Bg0IghiAarUIohoSEIic3A1ACQCAJQf8BcUEFRgRAQQUhCSAEDQEgDkEQdCAZciERIBIQUCIJQQh2IRoMAQsgBEUEQCAkIANB7ABqIgQQSEUEQCAYICdBvMPAABBwIA5BEHQgGXIhESAEEFAiCUEIdiEaDAILIA5BEHQgEWohEQwBCyAYICdBrMPAABBwQQUhCQtBiMHAACAGEG8hBAJAAkACQAJAAn8CQCAGQaDLAEYNACAGQYPKAEYNACAGQf3//wBxQfnKAEYNACAEDQBBlMHAACAGEG8NAEHYwMAAIAYQbyEEAkAgBkGPzQBGDQAgBA0AQeTAwAAgBhBvDQBB8MDAACAGEG8NAEH8wMAAIAYQb0UNAwsgA0FAaxBQIRIgEC0AAEECdEH8AHFBAiAIQRBqLQAAIgRBAUYgBEECRhtyQf8BcSETIB4oAgAiGyAUKAIAIgdGBEAjAEEQayIEJAAgBEEIaiAeIBtBAUEEQRAQJCAEKAIIIhtBgYCAgHhHBEAgBCgCDBogG0HMw8AAEJ0BAAsgBEEQaiQACyAFKAL4BSAHQQR0aiIEIBM6AAwgBCASNgIIIAQgBjYCBCAEIA87AQAgFAwBCyADQUBrEFAhEiAfKAIAIhMgFSgCACIHRgRAIwBBEGsiBCQAIARBCGogHyATQQFBBEEMECQgBCgCCCITQYGAgIB4RwRAIAQoAgwaIBNB3MPAABCdAQALIARBEGokAAsgBSgC7AUgB0EMbGoiBCASNgIIIAQgBjYCBCAEIA87AQAgFQsgB0EBajYCAEEgIQYMAQsgBkGAAUkNACAOQf//A3FBAUsNASAGQf//A00EQCAGQQN2QcCAwABqLQAAIAZBB3F2QQFxRQ0BDAILQczAwAAgBhBvDQELIAMgCzsAVyAmIAtBEHYiBDoAACADICA2AlwgAyAMOgBaIAMgDTsBVCADIBc2AlAgAyABOgBWAkAgAUH/AXFBBUYNAAJAIANBQGsgIxBIBEAgEC0AAEECdEH8AHFBAiAIQRBqLQAAIgdBAUYgB0ECRhtyQb8BcSAMc0G/AXFFDQELAkAgBkEgRw0AIAxBCHFBA3YgEC0AACIHQQJxQQF2Rw0AIAxBEHFBBHYgB0EEcUECdkYNAQsgAyALOwBnIANB4ABqIgdBCWogBDoAACADIAw6AGogAyABOgBmIAMgDTsBZCADIBc2AmAgFiAHQezDwAAQWwwBCyANQQFqIQ0gASECDAILIBxBEHQgGXIhFyAQLQAAQQJ0QfwAcUECIAhBEGotAAAiAUEBRiABQQJGG3JB/wFxIQwgCkEIdiELQQEhDQwBCyABQf8BcUEFRwRAIAMgCzsASyADQcQAaiICQQlqIAtBEHY6AAAgAyAMOgBOIAMgAToASiADIA07AUggAyAXNgJEIBYgAkH8w8AAEFsLIBAtAAAhAiAIQRBqLQAAIQEgAyAHNgFWIANBATsBVCADIBw7AVIgAyAPOwFQIAMgAkECdEH8AHFBAiABQQFGIAFBAkYbcjoAWiAWIANB0ABqQYzEwAAQW0EFIQILIAUoAogGIgQgBSgCgAZGBEAjAEEQayIBJAAgAUEIaiAdIB0oAgBBAUEEQQQQJCABKAIIIghBgYCAgHhHBEAgASgCDBogCEGcxMAAEJ0BAAsgAUEQaiQACyAcQQFqIRwgBSgChAYgBEECdGogBjYCACAFIARBAWo2AogGIA4gD2ohDyACIQEMAAsACyABIABBmOXAABBCAAu5DgEDfyMAQeAAayIDJAAgAUEEaiEEAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQAJAAkACQCABKAIAIgVBgIDEAEYEQCACQUBqDjYBAgMEBQYHCAkKCwwNDjc3Dzc3EBE3NxITNxQ3Nzc3NxUWFzcYGRobHDc3Nx0eNzc3Nx8gMiE3CwJAIAJB7ABrDgU1Nzc3MwALIAJB6ABGDTMMNgsgAEEdOgAAIAAgAS8BCDsBAgw2CyAAQQw6AAAgACABLwEIOwECDDULIABBCToAACAAIAEvAQg7AQIMNAsgAEEKOgAAIAAgAS8BCDsBAgwzCyAAQQg6AAAgACABLwEIOwECDDILIABBBDoAACAAIAEvAQg7AQIMMQsgAEEFOgAAIAAgAS8BCDsBAgwwCyAAQQI6AAAgACABLwEIOwECDC8LIABBCzoAACAAIAEvARg7AQQgACABLwEIOwECDC4LIABBAzoAACAAIAEvAQg7AQIMLQsgAS8BCA4EFxgZGhYLIAEvAQgOAxscHRoLIABBHjoAACAAIAEvAQg7AQIMKgsgAEEVOgAAIAAgAS8BCDsBAgwpCyAAQQ06AAAgACABLwEIOwECDCgLIABBLToAACAAIAEvAQg7AQIMJwsgAEEoOgAAIAAgAS8BCDsBAgwmCyABLwEIDgYZGBoYGBsYCyAAQRY6AAAgACABLwEIOwECDCQLIABBAToAACAAIAEvAQg7AQIMIwsgAEECOgAAIAAgAS8BCDsBAgwiCyAAQQo6AAAgACABLwEIOwECDCELIABBIjoAACAAIAEvAQg7AQIMIAsgAEEvOgAAIAAgAS8BCDsBAgwfCyAAQTA6AAAgACABLwEIOwECDB4LIABBCzoAACAAIAEvARg7AQQgACABLwEIOwECDB0LIAEvAQgOBBQTExUTCyADIAQgASgChARBhNzAABBtIANBQGsiASADKAIAIgIgAiADKAIEQQR0ahAmIANBO2ogAUEIaigCADYAACADIAMpAkA3ADMgAEErOgAAIAAgAykAMDcAASAAQQhqIANBN2opAAA3AAAMGwsgA0EIaiAEIAEoAoQEQZTcwAAQbSADQUBrIgEgAygCCCICIAIgAygCDEEEdGoQJiADQTtqIAFBCGooAgA2AAAgAyADKQJANwAzIABBJToAACAAIAMpADA3AAEgAEEIaiADQTdqKQAANwAADBoLIANBGGogBCABKAKEBEGk3MAAEG0gAyADKQMYNwJMIANB1gBqIANBzABqEAsCfyADLQBWQRJGBEBBACEBQQAhBEEBDAELIANBEGpBBEEBQQVBlMjAABBXIANB2gBqLQAAIQEgAygCECECIAMoAhQiBCADKABWNgAAIARBBGogAToAACADQQE2AjggAyAENgI0IAMgAjYCMCADIAMpAkw3AkBBBSECQQEhAQNAIANB2wBqIANBQGsQCyADLQBbQRJGRQRAIAMoAjAgAUYEQCADQTBqIAFBAUEBQQUQZCADKAI0IQQLIAIgBGoiBSADKABbNgAAIAVBBGogA0HfAGotAAA6AAAgAyABQQFqIgE2AjggAkEFaiECDAELCyADKAIwIQQgAygCNAshAiAAIAE2AgwgACACNgIIIAAgBDYCBCAAQSk6AAAMGQsgAEETOgAAIAAgAS8BGDsBBCAAIAEvAQg7AQIMGAsgAEEnOgAADBcLIABBJjoAAAwWCyAAQTI6AAAMFQsgAEEXOwEADBQLIABBlwI7AQAMEwsgAEGXBDsBAAwSCyAAQZcGOwEADBELIABBMjoAAAwQCyAAQRg7AQAMDwsgAEGYAjsBAAwOCyAAQZgEOwEADA0LIABBMjoAAAwMCyAAQQc7AQAMCwsgAEGHAjsBAAwKCyAAQYcEOwEADAkLIABBMjoAAAwICyAAQS47AQAMBwsgAEGuAjsBAAwGCyABLwEIQQhGDQMgAEEyOgAADAULIAVBIUcNAyAAQRQ6AAAMBAsgBUE/Rw0CIANBIGogBCABKAKEBEG03MAAEG0gA0FAayIBIAMoAiAiAiACIAMoAiRBBHRqECcgA0E7aiABQQhqKAIANgAAIAMgAykCQDcAMyAAQRI6AAAgACADKQAwNwABIABBCGogA0E3aikAADcAAAwDCyAFQT9HDQEgA0EoaiAEIAEoAoQEQcTcwAAQbSADQUBrIgEgAygCKCICIAIgAygCLEEEdGoQJyADQTtqIAFBCGooAgA2AAAgAyADKQJANwAzIABBEDoAACAAIAMpADA3AAEgAEEIaiADQTdqKQAANwAADAILIABBMToAACAAIAEvARg7AQQgACABLwEoOwECDAELIABBMjoAAAsgA0HgAGokAAvaCwIPfwJ+IwBB0ABrIgIkACABQQRqIQwgAkFAayENIAJBJWohDiACQRxqIQ8gASgCJCEFIAEoAhQhECABKAIQIQMCQAJAAn8CQANAIAEoAgAhBiABQYCAgIB4NgIAIAEoAgQhCwJAAkACQAJAAkAgBkGAgICAeEcEQCABKQIIIREgCyEHDAELAkAgAyAQRgRAQYCAgIB4IQYMAQsgASADQRBqIgg2AhAgAykCCCERIAMoAgQhByADKAIAIQYgCCEDC0GAgICAeCALEJgBIAZBgICAgHhGDQELIAIgBzYCDCACIAY2AgggAiARNwIQIBFCIIghEkF/IAUgEaciBEcgBCAFSxtB/wFxDgICAwELQYCAgIB4IAcQmAEgAEGAgICAeDYCACABQYCAgIB4NgIADAcLAkAgEqdBAXENACAFIAQgByAEEDBrIgMgAyAFSRsiAyAESw0AIAIgAzYCECADIQQLAn9BgICAgHggBCAFTQ0AGgJAAkAgByAEIAVBuNrAABCGASgCBEUEQCACQThqIgMgAkEIaiIIIAVBAWsQOSACQTBqIANBCGooAgA2AgAgAiACKQI4NwMoIAItABQhBCADQRBqIAIoAgwgAigCECIHIAdBAWtB2NrAABCGASIHQRBqLwEAOwEAIAJCoICAgBA3AjggAiAHKQIINwJAIAggA0Ho2sAAEE4gAiAEOgA0IAItABRBAXFFDQEMAgsgAkE4aiIDIAJBCGogBRA5IAJBMGogA0EIaigCADYCACACIAIpAjg3AyggAiACLQAUIgM6ADQgAw0BCyACQShqEIEBCyACKAIwBEAgAkFAayACQTRqKAIANgIAIAJBAToAFCACIAIpAiw3AzggAigCKAwBCyACKAIoIAIoAixBFBCVAUGAgICAeAshA0GAgICAeCALEJgBIAEgAzYCACAMIAIpAzg3AgAgDEEIaiACQUBrKAIANgIAIABBCGogAkEQaikCADcCACAAIAIpAgg3AgAMBgsgACARNwIIIAAgBzYCBCAAIAY2AgAMBQsCQCADIBBHBEAgASADQRBqIgg2AhAgAygCACIGQYCAgIB4Rw0BCyACQQA7AEAgAkECOgA8IAJBAjoAOCACQQhqIgEgBSACQThqEDogACACKQIINwIAIAJBADoAFCAAQQhqIAFBCGopAgA3AgAMBQsgA0EMaigCACEJIA8gAykCBDcCACAPQQhqIAk2AgAgAiAGNgIYIAUgBGsiCUUNASASp0EBcUUEQCACQQA7AEAgAkECOgA8IAJBAjoAOCACQQhqIAUgAkE4ahA6DAILIAItACRFBEAgAkEYahCBAQsgAigCHCEDIAIoAiAiCiAJTQRAIAJBCGoiBCADIAoQdgJAIAItACQiBg0AIAJBADoAFCACKAIQIAVPDQAgAkEAOwBAIAJBAjoAPCACQQI6ADggBCAFIAJBOGoQOgsgAigCGCADQRQQlQEgBkUNBEGAgICAeCALEJgBIAFBCGogAkEQaikCADcCACABIAIpAgg3AgBBgICAgHggAhCYASAIIQMMAQsLIAMgCiAJQfjZwAAQhgEoAgRFBEAgDUEIaiAHIAQgBEEBa0GI2sAAEIYBIghBEGovAQA7AQAgDSAIKQIINwIAIAJCoICAgBA3AjggAkEIaiACQThqQZjawAAQTiAJQQFrIQkLIAkgCk0EQCACQQhqIAMgCRB2IAIoAhghBiADIAogCRB+IAZBgICAgHhGDQMgCiAKIAlrIgggCCAKSxshBCACLQAkDAILIAkgCkGo2sAAEKIBAAsgAkEqaiAOQQJqLQAAOgAAIAIgDi8AADsBKCACKAIgIQQgAigCHCEDIAItACQLIQhBgICAgHggCxCYASABIAg6AAwgASAENgIIIAEgAzYCBCABIAY2AgAgASACLwEoOwAN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AiAAEHogAiADEHogASgCGAVBgAELIAEoAgggASgCDBCXASABQSBqJAALpwEBAn8jAEEgayICJAAgAiAAKAJoNgIMIAJBADoAHCACIAAoAlQiAzYCECACIAMgACgCWEECdGo2AhQgAiACQQxqNgIYIAACfwJAAkADQCABQQFrIgEEQCACQRBqEEANAQwCCwsgAkEQahBAIgENAQsgACgCnAEiA0EBayIADAELIAAoApwBIgNBAWshACABKAIACyIBIAAgASADSRs2AmggAkEgaiQAC6MBAQF/IwBBQGoiAyQAIANBHGogABBVIAMoAhwiACABIAIQIyADQShqIABB4ABqKAIAIABB5ABqKAIAECAgA0EQaiAAECEgAyADKQMQNwI0IANBCGogAygCLCADKAIwEFIgAygCDCEAIAMoAghBAXEEQCADIAA2AjwgA0E8akHswsAAEDwACyADQShqEGwgAygCICADKAIkEKEBIANBQGskACAAC5kBAQN/IAFBbGwhAiABQf////8DcSEDIAAgAUEUbGohAUEAIQACQANAIAJFDQECQCABQRRrIgQoAgBBIEcNACABQRBrKAIAQQFHDQAgAUEMay0AAEECRw0AIAFBCGstAABBAkcNACABQQRrLQAADQAgAUEDay0AAEEfcQ0AIAJBFGohAiAAQQFqIQAgBCEBDAELCyAAIQMLIAMLoAEBA38jAEEQayIFJAAgBUEIaiAAIAEgAkHgzsAAEF8gBSgCDCIGIAMgAiABayIHIAMgB0kbIgNPBEAgBiADayIGIAUoAgggBkEEdGogAxATIAAgASABIANqIAQQKCABBEAgACABQQFrQfDOwAAQWkEAOgAMCyAAIAJBAWtBgM/AABBaQQA6AAwgBUEQaiQADwtBzMnAAEEhQfDJwAAQZwALiwEBAn8jAEEQayICJAAgAkKAgICAwAA3AgQgAkEANgIMIAFBCGsiA0EAIAEgA08bIgFBA3YgAUEHcUEAR2ohAUEIIQMDQCABBEAgAkEEaiADQaziwAAQcSABQQFrIQEgA0EIaiEDDAEFIAAgAikCBDcCACAAQQhqIAJBDGooAgA2AgAgAkEQaiQACwsLjQEBBH8gASAAKAIAIAAoAggiBGtLBEAgACAEIAFBAUEBEGQgACgCCCEECyAAKAIEIARqIQVBASABIAFBAU0bIgZB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dGo2AgALRAEBfyABKAIAIgIgASgCBEYEQCAAQYCAgIB4NgIADwsgASACQRBqNgIAIAAgAikCADcCACAAQQhqIAJBCGopAgA3AgALOwEDfwNAIAJBFEZFBEAgACACaiIDKAIAIQQgAyABIAJqIgMoAgA2AgAgAyAENgIAIAJBBGohAgwBCwsLOwEDfwNAIAJBJEZFBEAgACACaiIDKAIAIQQgAyABIAJqIgMoAgA2AgAgAyAENgIAIAJBBGohAgwBCwsLQAECfyAAKAIAIAAoAgRBBBCVASAAKAIMIQEgACgCECIAKAIAIgIEQCABIAIRAgALIAAoAgQiAARAIAEgABA7Cws6AQF/AkAgAkF/RwRAIAJBAWohBCACQSBJDQEgBEEgIAMQogEACyADEHMACyAAIAQ2AgQgACABNgIACzgAAkAgAWlBAUcNAEGAgICAeCABayAASQ0AIAAEQEH4qsEALQAAGiABIAAQFSIBRQ0BCyABDwsACy0BAX8gASAAKAIATwR/IAAoAgQhAiAALQAIRQRAIAEgAk0PCyABIAJJBUEACwtwAQN/IAAoAgAiBCAAKAIIIgVGBEAjAEEQayIDJAAgA0EIaiAAIARBAUECQQgQJCADKAIIIgRBgYCAgHhHBEAgAygCDBogBCACEJ0BAAsgA0EQaiQACyAAIAVBAWo2AgggACgCBCAFQQN0aiABNwEACzQBAX8gACgCCCIDIAAoAgBGBEAgACACEGILIAAgA0EBajYCCCAAKAIEIANBAnRqIAE2AgALLgEBfyMAQRBrIgIkACACQQhqIAEgABCCASACKAIIIgAEQCACQRBqJAAgAA8LAAs3AQF/IwBBIGsiASQAIAFBADYCGCABQQE2AgwgAUGM6cAANgIIIAFCBDcCECABQQhqIAAQgAEACyUAIABBgQJPBEAgAEEeIABnIgBrdiAAQQF0a0E8ag8LIABBBHYLKwAgAiADSQRAIAMgAiAEEKMBAAsgACACIANrNgIEIAAgASADQRRsajYCAAsvAQF/IAAgAhCEASAAKAIEIAAoAggiA0EUbGogASACQRRsEBQaIAAgAiADajYCCAsrACABIANLBEAgASADIAQQowEACyAAIAMgAWs2AgQgACACIAFBBHRqNgIACy8AAkACQCADaUEBRw0AQYCAgIB4IANrIAFJDQAgACABIAMgAhAiIgANAQsACyAACywAA0AgAQRAIAAoAgAgAEEEaigCAEEUEJUBIAFBAWshASAAQRBqIQAMAQsLCzIBAX8gACgCCCECIAEgACgCAEECai0AABCRASEBIAAoAgQgAiABEAEgACACQQFqNgIICyoAIAAgACgCaCABaiIBIAAoApwBIgBBAWsgACABSxtBACABQQBOGzYCaAszAQJ/IAAgACgCqAEiAiAAKAKsAUEBaiIDIAEgAEGyAWoQMSAAKAJgIAAoAmQgAiADEEoLMwECfyAAIAAoAqgBIgIgACgCrAFBAWoiAyABIABBsgFqEBogACgCYCAAKAJkIAIgAxBKCyoAIAEgAkkEQEGkyMAAQSNBvMnAABBnAAsgAiAAIAJBFGxqIAEgAmsQFws1ACAAIAApAnQ3AmggACAAKQF8NwGyASAAIAAvAYYBOwG+ASAAQboBaiAAQYQBai8BADsBAAvsAQICfwF+IwBBEGsiAiQAIAJBATsBDCACIAE2AgggAiAANgIEIwBBEGsiASQAIAJBBGoiACkCACEEIAEgADYCDCABIAQ3AgQjAEEQayIAJAAgAUEEaiIBKAIAIgIoAgwhAwJAAkACQAJAIAIoAgQOAgABAgsgAw0BQQEhAkEAIQMMAgsgAw0AIAIoAgAiAigCBCEDIAIoAgAhAgwBCyAAQYCAgIB4NgIAIAAgATYCDCABKAIIIgEtAAkaIABBFSABLQAIEEEACyAAIAM2AgQgACACNgIAIAEoAggiAS0ACRogAEEWIAEtAAgQQQALKwECfwJAIAAoAgQgACgCCCIBEDAiAkUNACABIAJJDQAgACABIAJrNgIICwsmACACBEBB+KrBAC0AABogASACEBUhAQsgACACNgIEIAAgATYCAAsjAQF/IAEgACgCACAAKAIIIgJrSwRAIAAgAiABQQRBEBBkCwsjAQF/IAEgACgCACAAKAIIIgJrSwRAIAAgAiABQQRBFBBkCwslACAAQQE2AgQgACABKAIEIAEoAgBrQQR2IgE2AgggACABNgIACxsAIAEgAk0EQCACIAEgAxBCAAsgACACQRRsagsgACABIAJNBEAgAiABQeTjwAAQQgALIAAgAmpBAToAAAsbACABIAJNBEAgAiABIAMQQgALIAAgAkEEdGoLAwAACwMAAAsDAAALAwAACwMAAAsDAAALGgBB+KrBAC0AABpBBCAAEBUiAARAIAAPCwALAwAACxYAIAFBAXFFBEAgALgQBw8LIACtEAgLRAEBfyAAIAAoAgBBAWsiATYCACABRQRAIABBDGoQRwJAIABBf0YNACAAIAAoAgRBAWsiATYCBCABDQAgAEGcBhA7CwsLHgEBfyAAKAIQIgEgACgCFBB5IAAoAgwgAUEQEJUBCx4BAX8gACgCBCIBIAAoAggQeSAAKAIAIAFBEBCVAQsQACAABEAgASAAIAJsEDsLCxYAIABBEGoQTyAAKAIAIAAoAgQQmAELFAAgACAAKAIAQQFrNgIAIAEQkgELFwAgAEGAgICAeEcEQCAAIAFBFBCVAQsLEwAgAARADwtBpKnBAEEbEKgBAAsPACAAQYQBTwRAIAAQAgsLDQAgAQRAIAAgARA7CwsNACABBEAgACABEDsLCzwAIABFBEAjAEEgayIAJAAgAEEANgIYIABBATYCDCAAQdDEwAA2AgggAEIENwIQIABBCGogARCAAQALAAsRACAAKAIIIAAoAgBBAhCVAQsUACAAQQA2AgggAEKAgICAEDcCAAsSACAAIAFBkM3AABBaQQE6AAwLDgAgAEEANgIAIAEQkgELawEBfyMAQTBrIgMkACADIAE2AgQgAyAANgIAIANBAjYCDCADQejpwAA2AgggA0ICNwIUIAMgA0EEaq1CgICAgIABhDcDKCADIAOtQoCAgICAAYQ3AyAgAyADQSBqNgIQIANBCGogAhCAAQALawEBfyMAQTBrIgMkACADIAE2AgQgAyAANgIAIANBAjYCDCADQcjpwAA2AgggA0ICNwIUIAMgA0EEaq1CgICAgIABhDcDKCADIAOtQoCAgICAAYQ3AyAgAyADQSBqNgIQIANBCGogAhCAAQALawEBfyMAQTBrIgMkACADIAE2AgQgAyAANgIAIANBAjYCDCADQZzqwAA2AgggA0ICNwIUIAMgA0EEaq1CgICAgIABhDcDKCADIAOtQoCAgICAAYQ3AyAgAyADQSBqNgIQIANBCGogAhCAAQALDgBB8OXAAEErIAAQZwALCwAgACMAaiQAIwALDgBBv6nBAEHPABCoAQALCQAgACABEAYACwwAIAAgASkCADcDAAsKACAAKAIAEJoBCw0AIABBgICAgHg2AgALCQAgAEEANgIACwYAIAAQTwsL0m0gAEGAgMAAC0AXAAAABAAAAAQAAAAYAAAAY2FsbGVkIGBSZXN1bHQ6OnVud3JhcCgpYCBvbiBhbiBgRXJyYCB2YWx1ZUVycm9yAEG/icAACwF4AEHgicAACxD/////////////////////AEGGisAACw8BAAAAAAAgAAAAAAAAAAIAQcCKwAALIP//////////////////////////////////////////AEGki8AACwgQAAAAAAAAAQBBwLjAAAsC/wcAQdS4wAALBw8A////9f8AQYC5wAALFv///////////////////////////wMAQaC5wAALHf////////////////////////////////////8PAEH/ucAACxj8//////////////////////////////8AQaC6wAALPv//////////////////////////////////////////////////////////////////////////////////AEGMu8AACzj/////////////////////////////////////////////////////////////////////////fwBB4LvAAAvRAf////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8DAEHAvcAACyf//////////////////////////////////////////////////w8AQcDAwAALwSNzcmMvbGliLnJzAAABAA8A8BoPAAAAAADiJQAA5SUAAAAAAACw4AAAv+AAAAAAAAA8+wEAafsBAAAAAABq+wEAbPsBAAAAAACAJQAAnyUAAAAAAAAA+wEAO/sBAAAAAABhdHRlbXB0ZWQgdG8gdGFrZSBvd25lcnNoaXAgb2YgUnVzdCB2YWx1ZSB3aGlsZSBpdCB3YXMgYm9ycm93ZWRiZ3RleHRjb2RlcG9pbnRzcmFzdGVyX3N5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VVVVVRVRVVVVVVVVVQAAAAAAAEBVVVVVVVVVVVXVV1VVVVVVVVVVVVVVBQAAVFVVVVVVVVVVVVVVVVUVAABVVVFVVVVVVQUQAAABAVBVVVVVVVVVVVVVAVVVVVVV/////39VVVVQVQAAVVVVVVVVVVVVVQUAQcD8wAALmARAVVVVVVVVVVVVVVVVVUVUAQBUUQEAVVUFVVVVVVVVVVFVVVVVVVVVVVVVVVVVVUQBVFVRVRVVVQVVVVVVVVVFQVVVVVVVVVVVVVVVVVVVVEEVFFBRVVVVVVVVVVBRVVVBVVVVVVVVVVVVVVVVVVVUARBUUVVVVVUFVVVVVVUFAFFVVVVVVVVVVVVVVVVVVQQBVFVRVQFVVQVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVRVRVVVFVFVVVVVVVVVVVVVVUVFVVVVVVVVVVVVVVVVUEVAUEUFVBVVUFVVVVVVVVVVFVVVVVVVVVVVVVVVVVVRREBQRQVUFVVQVVVVVVVVVVUFVVVVVVVVVVVVVVVVUVRAFUVUFVFVVVBVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVFFQVEVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVEAQFVVFQBAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUQAAVFVVAEBVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVEVFVVVVVVVVVVVVVVVVVAQAAQAAEVQEAAAEAAAAAAAAAAFRVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUBBABBQVVVVVVVVVAFVFVVVQFUVVVFQVVRVVVVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqgBBgIHBAAuQA1VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAVVVVVVVVVVVVVVVVQVUVVVVVVVVBVVVVVVVVVUFVVVVVVVVVQVVVVV///33//3XX3fW1ddVEABQVUUBAABVV1FVVVVVVVVVVVVVFQBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUFVVVVVVVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAVVFVFVQFVVVVVVVVVVVVVVVVVVVVVVVVVVVVXFRRVVVVVVVVVVVVVVVVVVUUAQEQBAFQVAAAUVVVVVVVVVVVVVVVVAAAAAAAAAEBVVVVVVVVVVVVVVVUAVVVVVVVVVVVVVVVVAABQBVVVVVVVVVVVVRUAAFVVVVBVVVVVVVVVBVAQUFVVVVVVVVVVVVVVVVVFUBFQVVVVVVVVVVVVVVVVVVUAAAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAAAAAEAFRRVVRQVVVVVVVVVVVVVVVVVVVVVVUAQaCEwQALkwhVVRUAVVVVVVVVBUBVVVVVVVVVVVVVVVUAAAAAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAAAAAAAAAABUVVVVVVVVVVVV9VVVVWlVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf1X11VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV9VVVVVVVfVVVVVVVVVVVVVVVV////VVVVVVVVVVVVVdVVVVVV1VVVVV1V9VVVVVV9VV9VdVVXVVVVVXVV9V11XVVd9VVVVVVVVVVXVVVVVVVVVVV31d9VVVVVVVVVVVVVVVVVVVX9VVVVVVVVV1VV1VVVVVVVVVVVVVVVVVVVVVVVVVVVVVXVV1VVVVVVVVVVVVVVVVddVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVQVVVVVVVVVVVVVVVVVVVV/f///////////////19V1VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAAAAAAAAAAKqqqqqqqpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqVVVVqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpaVVVVVVVVqqqqqqqqqqqqqqqqqqoKAKqqqmqpqqqqqqqqqqqqqqqqqqqqqqqqqqpqgaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpVqaqqqqqqqqqqqqqpqqqqqqqqqqqqqqqqqKqqqqqqqqqqqmqqqqqqqqqqqqqqqqqqqqqqqqqqqqpVVZWqqqqqqqqqqqqqqmqqqqqqqqqqqqqqVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqVVVVVVVVVVVVVVVVVVVVVaqqqlaqqqqqqqqqqqqqqqqqalVVVVVVVVVVVVVVVVVfVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFUAAAFBVVVVVVVVVBVVVVVVVVVVVVVVVVVVVVVVVVVVVUFVVVUVFFVVVVVVVVUFVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVAAAAAFBVRRVVVVVVVVVVVVUFAFBVVVVVVRUAAFBVVVWqqqqqqqqqVkBVVVVVVVVVVVVVVRUFUFBVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVQFAQUFVVRVVVVRVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVUEFFQFUVVVVVVVVVVVVVVQVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVFFVVVVVqqqqqqqqqqqqVVVVAAAAAABAFQBBv4zBAAvhDFVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAAAPCqqlpVAAAAAKqqqqqqqqqqaqqqqqpqqlVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRWpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpWVVVVVVVVVVVVVVVVVVUFVFVVVVVVVVVVVVVVVVVVVapqVVUAAFRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBUBVAUFVAFVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQVVVVVVVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVRVVVVVVVVVVVVVVVVVVVVVVVVVAVVVVVVVVVVVVVVVVVVVVVVVBQAAVFVVVVVVVVVVVVVVBVBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVQAAAEBVVVVVVVVVVVVVFFRVFVBVVVVVVVVVVVVVVRVAQVVFVVVVVVVVVVVVVVVVVVVVQFVVVVVVVVVVFQABAFRVVVVVVVVVVVVVVVVVVRVVVVVQVVVVVVVVVVVVVVVVBQBABVUBFFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVAEVUVRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVFQBAVVVVVVVQVVVVVVVVVVVVVVVVVRVEVFVVVVUVVVVVBQBUAFRVVVVVVVVVVVVVVVVVVVVVAAAFRFVVVVVVRVVVVVVVVVVVVVVVVVVVVVVVVVVVFABEEQRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRUFUFUQVFVVVVVVVVBVVVVVVVVVVVVVVVVVVVVVVVVVVRUAQBFUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVRABBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAQUQAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFQAAQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFUVBBFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUABVVUVVVVVVVVVQEAQFVVVVVVVVVVVRUABEBVFVVVAUABVVVVVVVVVVVVVQAAAABAUFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAQAAQVVVVVVVVVVVVVVVVVVVVVVVVVVUFAAAAAAAFAARBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAUBFEAAAVVVVVVVVVVVVVVVVVVVVVVVVUBFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVVFVVQFVVVVVVVVVVVVVVVQVAVURVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBUAAABQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAVFVVVVVVVVVVVVVVVVVVAEBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVFVVVVVVVVVVVVVVVVVVVVRVAVVVVVVVVVVVVVVVVVVVVVVVVVapUVVVaVVVVqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqVVWqqqqqqqqqqqqqqqqqqqqqqqqqqqpaVVVVVVVVVVVVVaqqVlVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVaqpqmmqqqqqqqqqqmpVVVVlVVVVVVVVVWpZVVVVqlVVqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpVVVVVVVVVVUEAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUAQauZwQALdVAAAAAAAEBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVURUAUAAAAAQAEAVVVVVVVVVQVQVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVBVRVVVVVVVVVVVVVVVVVVQBBrZrBAAsCQBUAQbuawQALxQZUVVFVVVVUVVVVVRUAAQAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVAEAAAAAAFAAQBEBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRVVVVVVVVVVVVVVVVVVVVQBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQBAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVAEBVVVVVVVVVVVVVVVVVVVdVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV1VVVVVVVVVVVVVVVVVVVVXX9/39VVVVVVVVVVVVVVVVVVVVVVVX1////////blVVVaqquqqqqqrq+r+/VaqqVlVfVVVVqlpVVVVVVVX//////////1dVVf3/3///////////////////////9///////VVVV/////////////3/V/1VVVf////9XV///////////////////////f/f/////////////////////////////////////////////////////////////1////////////////////19VVdV/////////VVVVVXVVVVVVVVV9VVVVV1VVVVVVVVVVVVVVVVVVVVVVVVVV1f///////////////////////////1VVVVVVVVVVVVVVVf//////////////////////X1VXf/1V/1VV1VdV//9XVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV////VVdVVVVVVVX//////////////3///9//////////////////////////////////////////////////////////////VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf///1f//1dV///////////////f/19V9f///1X//1dV//9XVaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpaVVVVVVVVVVVZllVhqqVZqlVVVVVVlVVVVVVVVVWVVVUAQY6hwQALAQMAQZyhwQALiQlVVVVVVZVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVRUAlmpaWmqqBUCmWZVlVVVVVVVVVVUAAAAAVVZVValWVVVVVVVVVVVVVlVVVVVVVVVVAAAAAAAAAABUVVVVlVlZVVVlVVVpVVVVVVVVVVVVVVWVVpVqqqqqVaqqWlVVVVlVqqqqVVVVVWVVVVpVVVVVpWVWVVVVlVVVVVVVVaaWmpZZWWWplqqqZlWqVVpZVVpWZVVVVWqqpaVaVVVVpapaVVVZWVVVWVVVVVVVlVVVVVVVVVVVVVVVVVVVVVVVVVVVZVX1VVVVaVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqVaqqqqqqqqqqqlVVVaqqqqqlWlVVmqpaVaWlVVpapZalWlVVVaVaVZVVVVV9VWlZpVVfVWZVVVVVVVVVVWZV////VVVVmppqmlVVVdVVVVVV1VVVpV1V9VVVVVW9Va+quqqrqqqaVbqq+q66rlVd9VVVVVVVVVVXVVVVVVlVVVV31d9VVVVVVVVVpaqqVVVVVVVV1VdVVVVVVVVVVVVVVVVXrVpVVVVVVVVVVVWqqqqqqqqqaqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqgAAAMCqqlpVAAAAAKqqqqqqqqqqaqqqqqpqqlVVVVVVVVVVVVVVVQVUVVVVVVVVVVVVVVVVVVVVqmpVVQAAVFmqqmpVqqqqqqqqqlqqqqqqqqqqqqqqqqqqqlpVqqqqqqqqqrr+/7+qqqqqVlVVVVVVVVVVVVVVVVX1////////L25peC9zdG9yZS8yOGh5emZsMzM4a3M0YW1oYTd2cHBubGJxMXMxbnFhdi1ydXN0LWRlZmF1bHQtMS44NS4wL2xpYi9ydXN0bGliL3NyYy9ydXN0L2xpYnJhcnkvYWxsb2Mvc3JjL3Jhd192ZWMucnMvaG9tZS9ydW5uZXIvLmNhcmdvL3JlZ2lzdHJ5L3NyYy9pbmRleC5jcmF0ZXMuaW8tMTk0OWNmOGM2YjViNTU3Zi93YXNtLWJpbmRnZW4tMC4yLjEwNi9zcmMvY29udmVydC9zbGljZXMucnMvaG9tZS9ydW5uZXIvLmNhcmdvL3JlZ2lzdHJ5L3NyYy9pbmRleC5jcmF0ZXMuaW8tMTk0OWNmOGM2YjViNTU3Zi93YXNtLWJpbmRnZW4tMC4yLjEwNi9zcmMvZXh0ZXJucmVmLnJzHVQQAGcAAAB/AAAAEQAAAB1UEABnAAAAjAAAABEAAABudWxsIHBvaW50ZXIgcGFzc2VkIHRvIHJ1c3RyZWN1cnNpdmUgdXNlIG9mIGFuIG9iamVjdCBkZXRlY3RlZCB3aGljaCB3b3VsZCBsZWFkIHRvIHVuc2FmZSBhbGlhc2luZyBpbiBydXN0SnNWYWx1ZSgpAA5VEAAIAAAAFlUQAAEAQaiqwQALAQQASAlwcm9kdWNlcnMBDHByb2Nlc3NlZC1ieQIGd2FscnVzBjAuMjQuNAx3YXNtLWJpbmRnZW4TMC4yLjEwNiAoMTE4MzFmYjg5KQ==");
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
var _tmpl$$f = /*#__PURE__*/ template(`<div class="ap-term"><canvas></canvas><svg class="ap-term-symbols" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" width="100%" height="100%" aria-hidden="true"><defs></defs><g></g></svg><pre class="ap-term-text" aria-live="off" tabindex="0"></pre></div>`, 12);
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
		const _el$ = _tmpl$$f.cloneNode(true), _el$2 = _el$.firstChild, _el$3 = _el$2.nextSibling, _el$4 = _el$3.firstChild, _el$5 = _el$4.nextSibling, _el$6 = _el$3.nextSibling;
		const _ref$ = el;
		typeof _ref$ === "function" ? use(_ref$, _el$) : el = _el$;
		const _ref$2 = canvasEl;
		typeof _ref$2 === "function" ? use(_ref$2, _el$2) : canvasEl = _el$2;
		const _ref$3 = vectorSymbolsEl;
		typeof _ref$3 === "function" ? use(_ref$3, _el$3) : vectorSymbolsEl = _el$3;
		const _ref$4 = vectorSymbolDefsEl;
		typeof _ref$4 === "function" ? use(_ref$4, _el$4) : vectorSymbolDefsEl = _el$4;
		const _ref$5 = vectorSymbolRowsEl;
		typeof _ref$5 === "function" ? use(_ref$5, _el$5) : vectorSymbolRowsEl = _el$5;
		const _ref$6 = textEl;
		typeof _ref$6 === "function" ? use(_ref$6, _el$6) : textEl = _el$6;
		createRenderEffect((_p$) => {
			const _v$ = style$1(), _v$2 = `0 0 ${size().cols} ${size().rows}`, _v$3 = !!blinkOn(), _v$4 = !!blinkOn();
			_p$._v$ = style(_el$, _v$, _p$._v$);
			_v$2 !== _p$._v$2 && setAttribute(_el$3, "viewBox", _p$._v$2 = _v$2);
			_v$3 !== _p$._v$3 && _el$3.classList.toggle("ap-blink", _p$._v$3 = _v$3);
			_v$4 !== _p$._v$4 && _el$6.classList.toggle("ap-blink", _p$._v$4 = _v$4);
			return _p$;
		}, {
			_v$: void 0,
			_v$2: void 0,
			_v$3: void 0,
			_v$4: void 0
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
			ctx.fillRect(x, y + unitY * 7, BLOCK_H_RES, unitY);
			break;
		case 9602:
			ctx.fillRect(x, y + unitY * 6, BLOCK_H_RES, unitY * 2);
			break;
		case 9603:
			ctx.fillRect(x, y + unitY * 5, BLOCK_H_RES, unitY * 3);
			break;
		case 9604:
			ctx.fillRect(x, y + halfY, BLOCK_H_RES, halfY);
			break;
		case 9605:
			ctx.fillRect(x, y + unitY * 3, BLOCK_H_RES, unitY * 5);
			break;
		case 9606:
			ctx.fillRect(x, y + unitY * 2, BLOCK_H_RES, unitY * 6);
			break;
		case 9607:
			ctx.fillRect(x, y + unitY, BLOCK_H_RES, unitY * 7);
			break;
		case 9608:
			ctx.fillRect(x, y, BLOCK_H_RES, BLOCK_V_RES);
			break;
		case 9632:
			ctx.fillRect(x, y + unitY * 2, BLOCK_H_RES, unitY * 4);
			break;
		case 9609:
			ctx.fillRect(x, y, unitX * 7, BLOCK_V_RES);
			break;
		case 9610:
			ctx.fillRect(x, y, unitX * 6, BLOCK_V_RES);
			break;
		case 9611:
			ctx.fillRect(x, y, unitX * 5, BLOCK_V_RES);
			break;
		case 9612:
			ctx.fillRect(x, y, halfX, BLOCK_V_RES);
			break;
		case 9613:
			ctx.fillRect(x, y, unitX * 3, BLOCK_V_RES);
			break;
		case 9614:
			ctx.fillRect(x, y, unitX * 2, BLOCK_V_RES);
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
			ctx.fillRect(x + unitX * 7, y, unitX, BLOCK_V_RES);
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
			ctx.fillRect(x, y, sextantX * 2, sextantY);
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
			ctx.fillRect(x, y, sextantX * 2, sextantY);
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
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129803:
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			break;
		case 129804:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			break;
		case 129805:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			break;
		case 129806:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			break;
		case 129807:
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129808:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129809:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129810:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129811:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129812:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129813:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129814:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129815:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129816:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY * 2);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129817:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129818:
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129819:
			ctx.fillRect(x, y, sextantX, sextantY * 3);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			break;
		case 129820:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129821:
			ctx.fillRect(x, y, sextantX * 2, sextantY * 2);
			ctx.fillRect(x, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129822:
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129823:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129824:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129825:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129826:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129827:
			ctx.fillRect(x, y, sextantX, sextantY * 2);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129828:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129829:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129830:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129831:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129832:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129833:
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129834:
			ctx.fillRect(x, y, sextantX, sextantY * 2);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY * 2);
			break;
		case 129835:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129836:
			ctx.fillRect(x, y, sextantX * 2, sextantY * 2);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129837:
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129838:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129839:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129840:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129841:
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129842:
			ctx.fillRect(x, y, sextantX, sextantY * 2);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129843:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129844:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129845:
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129846:
			ctx.fillRect(x, y, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129847:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY * 2);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129848:
			ctx.fillRect(x, y, sextantX * 2, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY * 2, sextantX * 2, sextantY);
			break;
		case 129849:
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY * 2);
			break;
		case 129850:
			ctx.fillRect(x, y, sextantX, sextantY * 3);
			ctx.fillRect(x + sextantX, y + sextantY, sextantX, sextantY);
			ctx.fillRect(x + sextantX, y + sextantY * 2, sextantX, sextantY);
			break;
		case 129851:
			ctx.fillRect(x + sextantX, y, sextantX, sextantY);
			ctx.fillRect(x, y + sextantY, sextantX * 2, sextantY * 2);
			break;
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
			const horizontalGap = .15;
			const verticalGap = .2;
			const lineHeight = .17;
			const halfHorizontalGap = horizontalGap / 2;
			const halfVerticalGap = verticalGap / 2;
			const toViewBoxY = (offset) => .5 + offset * CELL_RATIO;
			const leftX1 = .5 - halfHorizontalGap;
			const rightX0 = .575;
			const rightX1 = 1.02;
			const topY0 = toViewBoxY(-.1 - lineHeight);
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
var _tmpl$$e = /*#__PURE__*/ template(`<svg version="1.1" viewBox="0 0 12 12" class="ap-icon ap-icon-fullscreen-off" aria-hidden="true"><path d="M7,5 L7,0 L9,2 L11,0 L12,1 L10,3 L12,5 Z"></path><path d="M5,7 L0,7 L2,9 L0,11 L1,12 L3,10 L5,12 Z"></path></svg>`, 6);
var ExpandIcon = (props) => {
	return _tmpl$$e.cloneNode(true);
};
var _tmpl$$d = /*#__PURE__*/ template(`<svg version="1.1" viewBox="6 8 14 16" class="ap-icon" aria-hidden="true"><path d="M0.938 8.313h22.125c0.5 0 0.938 0.438 0.938 0.938v13.5c0 0.5-0.438 0.938-0.938 0.938h-22.125c-0.5 0-0.938-0.438-0.938-0.938v-13.5c0-0.5 0.438-0.938 0.938-0.938zM1.594 22.063h20.813v-12.156h-20.813v12.156zM3.844 11.188h1.906v1.938h-1.906v-1.938zM7.469 11.188h1.906v1.938h-1.906v-1.938zM11.031 11.188h1.938v1.938h-1.938v-1.938zM14.656 11.188h1.875v1.938h-1.875v-1.938zM18.25 11.188h1.906v1.938h-1.906v-1.938zM5.656 15.031h1.938v1.938h-1.938v-1.938zM9.281 16.969v-1.938h1.906v1.938h-1.906zM12.875 16.969v-1.938h1.906v1.938h-1.906zM18.406 16.969h-1.938v-1.938h1.938v1.938zM16.531 20.781h-9.063v-1.906h9.063v1.906z"></path></svg>`, 4);
var KeyboardIcon = (props) => {
	return _tmpl$$d.cloneNode(true);
};
var _tmpl$$c = /*#__PURE__*/ template(`<svg version="1.1" viewBox="0 0 12 12" class="ap-icon" aria-hidden="true"><path d="M1,0 L4,0 L4,12 L1,12 Z"></path><path d="M8,0 L11,0 L11,12 L8,12 Z"></path></svg>`, 6);
var PauseIcon = (props) => {
	return _tmpl$$c.cloneNode(true);
};
var _tmpl$$b = /*#__PURE__*/ template(`<svg version="1.1" viewBox="0 0 12 12" class="ap-icon" aria-hidden="true"><path d="M1,0 L11,6 L1,12 Z"></path></svg>`, 4);
var PlayIcon = (props) => {
	return _tmpl$$b.cloneNode(true);
};
var _tmpl$$a = /*#__PURE__*/ template(`<svg version="1.1" viewBox="0 0 12 12" class="ap-icon ap-icon-fullscreen-on" aria-hidden="true"><path d="M12,0 L7,0 L9,2 L7,4 L8,5 L10,3 L12,5 Z"></path><path d="M0,12 L0,7 L2,9 L4,7 L5,8 L3,10 L5,12 Z"></path></svg>`, 6);
var ShrinkIcon = (props) => {
	return _tmpl$$a.cloneNode(true);
};
var _tmpl$$9 = /*#__PURE__*/ template(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M10.5 3.75a.75.75 0 0 0-1.264-.546L5.203 7H2.667a.75.75 0 0 0-.7.48A6.985 6.985 0 0 0 1.5 10c0 .887.165 1.737.468 2.52.111.29.39.48.7.48h2.535l4.033 3.796a.75.75 0 0 0 1.264-.546V3.75ZM16.45 5.05a.75.75 0 0 0-1.06 1.061 5.5 5.5 0 0 1 0 7.778.75.75 0 0 0 1.06 1.06 7 7 0 0 0 0-9.899Z"></path><path d="M14.329 7.172a.75.75 0 0 0-1.061 1.06 2.5 2.5 0 0 1 0 3.536.75.75 0 0 0 1.06 1.06 4 4 0 0 0 0-5.656Z"></path></svg>`, 6);
var SpeakerOnIcon = (props) => {
	return _tmpl$$9.cloneNode(true);
};
var _tmpl$$8 = /*#__PURE__*/ template(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5" aria-hidden="true"><path d="M10.047 3.062a.75.75 0 0 1 .453.688v12.5a.75.75 0 0 1-1.264.546L5.203 13H2.667a.75.75 0 0 1-.7-.48A6.985 6.985 0 0 1 1.5 10c0-.887.165-1.737.468-2.52a.75.75 0 0 1 .7-.48h2.535l4.033-3.796a.75.75 0 0 1 .811-.142ZM13.78 7.22a.75.75 0 1 0-1.06 1.06L14.44 10l-1.72 1.72a.75.75 0 0 0 1.06 1.06l1.72-1.72 1.72 1.72a.75.75 0 1 0 1.06-1.06L16.56 10l1.72-1.72a.75.75 0 0 0-1.06-1.06L15.5 8.94l-1.72-1.72Z"></path></svg>`, 4);
var SpeakerOffIcon = (props) => {
	return _tmpl$$8.cloneNode(true);
};
var _tmpl$$7 = /*#__PURE__*/ template(`<button class="ap-button ap-playback-button" type="button"></button>`, 2);
var _tmpl$2$2 = /*#__PURE__*/ template(`<span class="ap-bar"><span class="ap-gutter ap-gutter-empty"></span><span class="ap-gutter ap-gutter-full"></span></span>`, 6);
var _tmpl$3$1 = /*#__PURE__*/ template(`<span class="ap-tooltip">Unmute (m)</span>`, 2);
var _tmpl$4$1 = /*#__PURE__*/ template(`<span class="ap-tooltip">Mute (m)</span>`, 2);
var _tmpl$5$1 = /*#__PURE__*/ template(`<button class="ap-button ap-speaker-button ap-tooltip-container" type="button" aria-label="Mute / unmute"></button>`, 2);
var _tmpl$6$1 = /*#__PURE__*/ template(`<div class="ap-control-bar"><span class="ap-timer"><span class="ap-time-elapsed"></span><span class="ap-time-remaining"></span></span><span class="ap-progressbar"></span><button class="ap-button ap-kbd-button ap-tooltip-container" type="button" aria-label="Show keyboard shortcuts"><span class="ap-tooltip">Keyboard shortcuts (?)</span></button><button class="ap-button ap-fullscreen-button ap-tooltip-container" type="button" aria-label="Toggle fullscreen mode"><span class="ap-tooltip">Fullscreen (f)</span></button></div>`, 18);
var _tmpl$7$1 = /*#__PURE__*/ template(`<span class="ap-marker-container ap-tooltip-container"><span class="ap-marker"></span><span class="ap-tooltip"></span></span>`, 6);
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
var ControlBar = (props) => {
	const e = (f) => {
		return (e) => {
			e.preventDefault();
			f(e);
		};
	};
	const currentTime = () => typeof props.currentTime === "number" ? formatTime(props.currentTime) : "--:--";
	const remainingTime = () => typeof props.remainingTime === "number" ? "-" + formatTime(props.remainingTime) : currentTime();
	const markers = createMemo(() => typeof props.duration === "number" ? props.markers.filter((m) => m[0] < props.duration) : []);
	const markerPosition = (m) => `${m[0] / props.duration * 100}%`;
	const markerText = (m) => {
		if (m[1] === "") return formatTime(m[0]);
		else return `${formatTime(m[0])} - ${m[1]}`;
	};
	const isPastMarker = (m) => typeof props.currentTime === "number" ? m[0] <= props.currentTime : false;
	const gutterBarStyle = () => {
		return { transform: `scaleX(${props.progress || 0}` };
	};
	const calcPosition = (e) => {
		const barWidth = e.currentTarget.offsetWidth;
		const rect = e.currentTarget.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;
		return `${Math.max(0, mouseX / barWidth) * 100}%`;
	};
	const [mouseDown, setMouseDown] = createSignal(false);
	const throttledSeek = throttle(props.onSeekClick, 50);
	const onMouseDown = (e) => {
		if (e._marker) return;
		if (e.altKey || e.shiftKey || e.metaKey || e.ctrlKey || e.button !== 0) return;
		setMouseDown(true);
		props.onSeekClick(calcPosition(e));
	};
	const seekToMarker = (index) => {
		return e(() => {
			props.onSeekClick({ marker: index });
		});
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
		const _el$ = _tmpl$6$1.cloneNode(true), _el$3 = _el$.firstChild, _el$4 = _el$3.firstChild, _el$5 = _el$4.nextSibling, _el$6 = _el$3.nextSibling, _el$11 = _el$6.nextSibling, _el$12 = _el$11.firstChild, _el$13 = _el$11.nextSibling, _el$14 = _el$13.firstChild;
		const _ref$ = props.ref;
		typeof _ref$ === "function" ? use(_ref$, _el$) : props.ref = _el$;
		insert(_el$, createComponent(Show, {
			get when() {
				return props.isPausable;
			},
			get children() {
				const _el$2 = _tmpl$$7.cloneNode(true);
				addEventListener(_el$2, "click", e(props.onPlayClick));
				insert(_el$2, createComponent(Switch, { get children() {
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
				createRenderEffect(() => setAttribute(_el$2, "aria-label", props.isPlaying ? "Pause" : "Play"));
				return _el$2;
			}
		}), _el$3);
		insert(_el$4, currentTime);
		insert(_el$5, remainingTime);
		insert(_el$6, createComponent(Show, {
			get when() {
				return typeof props.progress === "number" || props.isSeekable;
			},
			get children() {
				const _el$7 = _tmpl$2$2.cloneNode(true), _el$9 = _el$7.firstChild.nextSibling;
				_el$7.$$mousemove = onMove;
				_el$7.$$mousedown = onMouseDown;
				insert(_el$7, createComponent(For, {
					get each() {
						return markers();
					},
					children: (m, i) => (() => {
						const _el$15 = _tmpl$7$1.cloneNode(true), _el$16 = _el$15.firstChild, _el$17 = _el$16.nextSibling;
						_el$15.$$mousedown = (e) => {
							e._marker = true;
						};
						addEventListener(_el$15, "click", seekToMarker(i()));
						insert(_el$17, () => markerText(m));
						createRenderEffect((_p$) => {
							const _v$ = markerPosition(m), _v$2 = !!isPastMarker(m);
							_v$ !== _p$._v$ && _el$15.style.setProperty("left", _p$._v$ = _v$);
							_v$2 !== _p$._v$2 && _el$16.classList.toggle("ap-marker-past", _p$._v$2 = _v$2);
							return _p$;
						}, {
							_v$: void 0,
							_v$2: void 0
						});
						return _el$15;
					})()
				}), null);
				createRenderEffect((_$p) => style(_el$9, gutterBarStyle(), _$p));
				return _el$7;
			}
		}));
		insert(_el$, createComponent(Show, {
			get when() {
				return props.isMuted !== void 0;
			},
			get children() {
				const _el$0 = _tmpl$5$1.cloneNode(true);
				addEventListener(_el$0, "click", e(props.onMuteClick));
				insert(_el$0, createComponent(Switch, { get children() {
					return [createComponent(Match, {
						get when() {
							return props.isMuted === true;
						},
						get children() {
							return [createComponent(SpeakerOffIcon, {}), _tmpl$3$1.cloneNode(true)];
						}
					}), createComponent(Match, {
						get when() {
							return props.isMuted === false;
						},
						get children() {
							return [createComponent(SpeakerOnIcon, {}), _tmpl$4$1.cloneNode(true)];
						}
					})];
				} }));
				return _el$0;
			}
		}), _el$11);
		addEventListener(_el$11, "click", e(props.onHelpClick));
		insert(_el$11, createComponent(KeyboardIcon, {}), _el$12);
		addEventListener(_el$13, "click", e(props.onFullscreenClick));
		insert(_el$13, createComponent(ShrinkIcon, {}), _el$14);
		insert(_el$13, createComponent(ExpandIcon, {}), _el$14);
		createRenderEffect(() => _el$.classList.toggle("ap-seekable", !!props.isSeekable));
		return _el$;
	})();
};
delegateEvents([
	"click",
	"mousedown",
	"mousemove"
]);
var _tmpl$$6 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-error"><span>💥</span></div>`, 4);
var ErrorOverlay = (props) => {
	return _tmpl$$6.cloneNode(true);
};
var _tmpl$$5 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-loading"><span class="ap-loader"></span></div>`, 4);
var LoaderOverlay = (props) => {
	return _tmpl$$5.cloneNode(true);
};
var _tmpl$$4 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-info"><span></span></div>`, 4);
var InfoOverlay = (props) => {
	return (() => {
		const _el$ = _tmpl$$4.cloneNode(true), _el$2 = _el$.firstChild;
		insert(_el$2, () => props.message);
		createRenderEffect(() => _el$.classList.toggle("ap-was-playing", !!props.wasPlaying));
		return _el$;
	})();
};
var _tmpl$$3 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-start"><div class="ap-play-button"><div><span><svg version="1.1" viewBox="0 0 1000.0 1000.0" class="ap-icon"><defs><mask id="small-triangle-mask"><rect width="100%" height="100%" fill="white"></rect><polygon points="700.0 500.0, 400.00000000000006 326.7949192431122, 399.9999999999999 673.2050807568877" fill="black"></polygon></mask></defs><polygon points="1000.0 500.0, 250.0000000000001 66.98729810778059, 249.99999999999977 933.0127018922192" mask="url(#small-triangle-mask)" fill="white" class="ap-play-btn-fill"></polygon><polyline points="673.2050807568878 400.0, 326.7949192431123 600.0" stroke="white" stroke-width="90" class="ap-play-btn-stroke"></polyline></svg></span></div></div></div>`, 22);
var StartOverlay = (props) => {
	const e = (f) => {
		return (e) => {
			e.preventDefault();
			f(e);
		};
	};
	return (() => {
		const _el$ = _tmpl$$3.cloneNode(true);
		addEventListener(_el$, "click", e(props.onClick));
		return _el$;
	})();
};
delegateEvents(["click"]);
var _tmpl$$2 = /*#__PURE__*/ template(`<li><kbd>space</kbd> - pause / resume</li>`, 4);
var _tmpl$2$1 = /*#__PURE__*/ template(`<li><kbd>←</kbd> / <kbd>→</kbd> - rewind / fast-forward by 5 seconds</li>`, 6);
var _tmpl$3 = /*#__PURE__*/ template(`<li><kbd>Shift</kbd> + <kbd>←</kbd> / <kbd>→</kbd> - rewind / fast-forward by 10%</li>`, 8);
var _tmpl$4 = /*#__PURE__*/ template(`<li><kbd>[</kbd> / <kbd>]</kbd> - jump to the previous / next marker</li>`, 6);
var _tmpl$5 = /*#__PURE__*/ template(`<li><kbd>0</kbd>, <kbd>1</kbd>, <kbd>2</kbd> ... <kbd>9</kbd> - jump to 0%, 10%, 20% ... 90%</li>`, 10);
var _tmpl$6 = /*#__PURE__*/ template(`<li><kbd>,</kbd> / <kbd>.</kbd> - step back / forward, a frame at a time (when paused)</li>`, 6);
var _tmpl$7 = /*#__PURE__*/ template(`<li><kbd>m</kbd> - mute / unmute audio</li>`, 4);
var _tmpl$8 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-help"><div><div><p>Keyboard shortcuts</p><ul><li><kbd>f</kbd> - toggle fullscreen mode</li><li><kbd>k</kbd> - toggle keystroke overlay</li><li><kbd>?</kbd> - show this help popup</li></ul></div></div></div>`, 22);
var HelpOverlay = (props) => {
	const e = (f) => {
		return (e) => {
			e.preventDefault();
			f(e);
		};
	};
	return (() => {
		const _el$ = _tmpl$8.cloneNode(true), _el$2 = _el$.firstChild, _el$5 = _el$2.firstChild.firstChild.nextSibling, _el$10 = _el$5.firstChild, _el$13 = _el$10.nextSibling.nextSibling;
		addEventListener(_el$, "click", e(props.onClose));
		_el$2.$$click = (e) => {
			e.stopPropagation();
		};
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.isPausable;
			},
			get children() {
				return _tmpl$$2.cloneNode(true);
			}
		}), _el$10);
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.isSeekable;
			},
			get children() {
				return [
					_tmpl$2$1.cloneNode(true),
					_tmpl$3.cloneNode(true),
					_tmpl$4.cloneNode(true),
					_tmpl$5.cloneNode(true),
					_tmpl$6.cloneNode(true)
				];
			}
		}), _el$10);
		insert(_el$5, createComponent(Show, {
			get when() {
				return props.hasAudio;
			},
			get children() {
				return _tmpl$7.cloneNode(true);
			}
		}), _el$13);
		return _el$;
	})();
};
delegateEvents(["click"]);
var _tmpl$$1 = /*#__PURE__*/ template(`<div><kbd></kbd></div>`, 4);
var _tmpl$2 = /*#__PURE__*/ template(`<div class="ap-overlay ap-overlay-keystrokes"></div>`, 2);
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
		const _el$ = _tmpl$$1.cloneNode(true), _el$2 = _el$.firstChild;
		insert(_el$2, () => props.keystroke.label());
		createRenderEffect(() => className(_el$, isFading() ? "ap-keystroke-pill fading" : "ap-keystroke-pill"));
		return _el$;
	})();
}
var KeystrokesOverlay = (props) => {
	return (() => {
		const _el$3 = _tmpl$2.cloneNode(true);
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
		createRenderEffect(() => _el$3.style.setProperty("--ap-keystrokes-bottom", `${(props.bottomOffset ?? 0) + 12}px`));
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
var _tmpl$ = /*#__PURE__*/ template(`<div class="ap-wrapper" tabindex="-1"><div></div></div>`, 4);
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
	const [terminalSize, setTerminalSize] = createTerminalSizeSignal(props.cols, props.rows);
	const [containerSize, setContainerSize] = createContainerSizeSignal();
	const [isPausable, setIsPausable] = createSignal(true);
	const [isSeekable, setIsSeekable] = createSignal(true);
	const [isFullscreen, setIsFullscreen] = createSignal(false);
	const [currentTime, setCurrentTime] = createSignal(null);
	const [remainingTime, setRemainingTime] = createSignal(null);
	const [progress, setProgress] = createSignal(null);
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
	function onPlaying() {
		setBlinking(true);
		startTimeUpdates();
	}
	function onStopped() {
		setBlinking(false);
		stopTimeUpdates();
		updateTime();
	}
	const onCoreReady = ({ isPausable, isSeekable }) => {
		batch(() => {
			setIsPausable(isPausable);
			setIsSeekable(isSeekable);
		});
	};
	const onCoreMetadata = (meta) => {
		batch(() => {
			if (meta.duration !== void 0) {
				setDuration(meta.duration);
				setCurrentTime(0);
				setRemainingTime(meta.duration);
				setProgress(0);
			}
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
			onPlaying();
		});
	};
	const onCorePause = () => {
		batch(() => {
			setIsPlaying(false);
			onStopped();
		});
	};
	const onCoreLoading = () => {
		batch(() => {
			setIsPlaying(false);
			onStopped();
			setOverlay("loader");
			clearKeystrokes();
		});
	};
	const onCoreOffline = ({ message }) => {
		batch(() => {
			setIsPlaying(false);
			onStopped();
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
			onStopped();
			if (message !== void 0) {
				setInfoMessage(message);
				setOverlay("info");
			}
		});
		logger.debug("stats", stats.terminal);
	};
	const onCoreError = () => {
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
		updateTime();
		clearKeystrokes();
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
		core.stop();
		stopTimeUpdates();
		resizeObserver.disconnect();
	});
	const terminalElementSize = createMemo(() => {
		const terminalW = charW * terminalCols() + bordersW;
		const terminalH = charH * terminalRows() + bordersH;
		let fit = props.fit ?? "width";
		const currentContainerSize = containerSize();
		if (fit === "both" || isFullscreen()) if (currentContainerSize.width / (currentContainerSize.height - controlBarHeight()) > terminalW / terminalH) fit = "height";
		else fit = "width";
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
		else if (e.key == ",") core.step(-1).then(updateTime);
		else if (e.key == ".") core.step().then(updateTime);
		else if (e.key == "f") toggleFullscreen();
		else if (e.key == "m") toggleMuted();
		else if (e.key == "[") core.seek({ marker: "prev" });
		else if (e.key == "]") core.seek({ marker: "next" });
		else if (e.key.charCodeAt(0) >= 48 && e.key.charCodeAt(0) <= 57) {
			const pos = (e.key.charCodeAt(0) - 48) / 10;
			core.seek(`${pos * 100}%`);
		} else if (e.key == "?") toggleHelp();
		else if (e.key == "k") toggleKeystrokeOverlay();
		else if (e.key == "ArrowLeft") if (e.shiftKey) core.seek("<<<");
		else core.seek("<<");
		else if (e.key == "ArrowRight") if (e.shiftKey) core.seek(">>>");
		else core.seek(">>");
		else if (e.key == "Escape") setIsHelpVisible(false);
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
	const startTimeUpdates = () => {
		clearInterval(timeUpdateIntervalId);
		timeUpdateIntervalId = setInterval(updateTime, 100);
	};
	const stopTimeUpdates = () => {
		clearInterval(timeUpdateIntervalId);
	};
	const updateTime = async () => {
		const newCurrentTime = await core.getCurrentTime();
		const newRemainingTime = await core.getRemainingTime();
		const newProgress = await core.getProgress();
		batch(() => {
			setCurrentTime(newCurrentTime);
			setRemainingTime(newRemainingTime);
			setProgress(newProgress);
		});
	};
	const onUserActive = (show) => {
		clearTimeout(userActivityTimeoutId);
		if (show) userActivityTimeoutId = setTimeout(() => onUserActive(false), 2e3);
		setUserActive(show);
	};
	const embeddedTheme = createMemo(() => preferEmbeddedTheme ? originalTheme() : null);
	const playerStyle = () => {
		const style = {};
		if ((props.fit === false || props.fit === "none") && props.terminalFontSize !== void 0) if (props.terminalFontSize === "small") style["font-size"] = "12px";
		else if (props.terminalFontSize === "medium") style["font-size"] = "18px";
		else if (props.terminalFontSize === "big") style["font-size"] = "24px";
		else style["font-size"] = props.terminalFontSize;
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
		const _el$ = _tmpl$.cloneNode(true), _el$2 = _el$.firstChild;
		const _ref$ = wrapperRef;
		typeof _ref$ === "function" ? use(_ref$, _el$) : wrapperRef = _el$;
		_el$.addEventListener("webkitfullscreenchange", onFullscreenChange);
		_el$.addEventListener("fullscreenchange", onFullscreenChange);
		_el$.$$mousemove = wrapperOnMouseMove;
		_el$.$$keydown = onKeyDown;
		const _ref$2 = playerRef;
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
					get progress() {
						return progress();
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
						const _ref$3 = controlBarRef;
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
		insert(_el$2, createComponent(Transition, {
			name: "slide",
			get children() {
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
			}
		}), null);
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
			const _v$ = !!controlsVisible(), _v$2 = playerClass(), _v$3 = playerStyle();
			_v$ !== _p$._v$ && _el$.classList.toggle("ap-hud", _p$._v$ = _v$);
			_v$2 !== _p$._v$2 && className(_el$2, _p$._v$2 = _v$2);
			_p$._v$3 = style(_el$2, _v$3, _p$._v$3);
			return _p$;
		}, {
			_v$: void 0,
			_v$2: void 0,
			_v$3: void 0
		});
		return _el$;
	})();
};
function createTerminalSizeSignal(cols, rows) {
	return createSignal({
		cols,
		rows
	}, { equals: (newVal, oldVal) => newVal.cols === oldVal.cols && newVal.rows === oldVal.rows });
}
function createContainerSizeSignal() {
	return createSignal({
		width: 0,
		height: 0
	}, { equals: (newVal, oldVal) => newVal.width === oldVal.width && newVal.height === oldVal.height });
}
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
function coreOpts(inputOpts, overrides = {}) {
	const opts = Object.fromEntries(Object.entries(inputOpts).filter(([key]) => CORE_OPTS.includes(key)));
	opts.autoPlay ??= opts.autoplay;
	opts.speed ??= 1;
	return {
		...opts,
		...overrides
	};
}
function uiOpts(inputOpts, overrides = {}) {
	const opts = Object.fromEntries(Object.entries(inputOpts).filter(([key]) => UI_OPTS.includes(key)));
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
//#endregion
//#region ../../node_modules/.pnpm/asciinema-player@3.17.0/node_modules/asciinema-player/dist/index.js
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
//#endregion
//#region ../../packages/react/src/components/AsciinemaPlayerImpl.tsx
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var import_jsx_runtime = require_jsx_runtime();
var AsciinemaPlayerImpl = ({ id, rows, cols, inputUrl, outputUrl, timingUrl, fit, speed, autoPlay, loop, theme, idleTimeLimit = 2, style }) => {
	const playerContainerRef = (0, import_react.useRef)(null);
	(0, import_react.useEffect)(() => {
		if (!playerContainerRef.current) return;
		const player = create({
			url: [
				timingUrl,
				outputUrl,
				inputUrl
			],
			parser: "typescript"
		}, playerContainerRef.current, {
			rows,
			cols,
			autoPlay,
			loop,
			theme,
			speed,
			idleTimeLimit,
			fit
		});
		player.play();
		return () => {
			player.dispose();
		};
	}, [
		timingUrl,
		outputUrl,
		inputUrl,
		rows,
		cols,
		autoPlay,
		loop,
		theme,
		speed,
		idleTimeLimit,
		fit
	]);
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		id: `asciinema-player-${id || "default"}`,
		ref: playerContainerRef,
		style: { ...style }
	});
};
//#endregion
export { AsciinemaPlayerImpl as default };

//# sourceMappingURL=AsciinemaPlayerImpl.js.map