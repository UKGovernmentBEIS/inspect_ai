//#region ../../packages/util/src/media.ts
var parseDataUri = (value) => {
	let uri;
	try {
		uri = new URL(value);
	} catch {
		return;
	}
	if (uri.protocol.toLowerCase() !== "data:") return;
	const comma = uri.pathname.indexOf(",");
	if (comma < 0) return;
	const [rawMimeType = "", ...parameters] = uri.pathname.slice(0, comma).split(";");
	const mimeType = rawMimeType.trim().toLowerCase();
	if (!mimeType) return;
	return {
		mimeType,
		base64: parameters.some((parameter) => parameter.trim().toLowerCase() === "base64")
	};
};
var rasterImageMimeTypes = /* @__PURE__ */ new Set([
	"image/avif",
	"image/bmp",
	"image/gif",
	"image/jpeg",
	"image/png",
	"image/webp",
	"image/x-icon"
]);
var imageMimeAliases = /* @__PURE__ */ new Map([["image/jpg", "image/jpeg"], ["image/vnd.microsoft.icon", "image/x-icon"]]);
var normalizedImageMimeType = (mimeType) => {
	const normalized = mimeType.trim().toLowerCase();
	return imageMimeAliases.get(normalized) ?? normalized;
};
var isRasterImageMimeType = (mimeType) => rasterImageMimeTypes.has(normalizedImageMimeType(mimeType));
var base64DataUriMimeType = (source) => {
	const dataUri = parseDataUri(source);
	return dataUri?.base64 ? dataUri.mimeType : void 0;
};
/** Inline image data that is safe to render without a network request. */ var isRenderableImageSource = (source) => {
	const mimeType = base64DataUriMimeType(source);
	return mimeType !== void 0 && isRasterImageMimeType(mimeType);
};
/**
* Canonical form of a renderable inline image source, or undefined.
*
* Callers that gate on the source must render THIS value rather than their
* input: validating one string and emitting another lets characters the URL
* parser rejects (U+FEFF, U+202F) survive into the DOM, where the browser
* reads the result as a relative path and fetches it.
*/ var canonicalImageSource = (source) => {
	const trimmed = source.trim();
	if (!isRenderableImageSource(trimmed)) return;
	try {
		return new URL(trimmed).href;
	} catch {
		return;
	}
};
var parseAbsoluteHttpUrl = (value) => {
	let url;
	try {
		url = new URL(value);
	} catch {
		return;
	}
	if (url.protocol !== "http:" && url.protocol !== "https:" || !url.hostname) return;
	return url.href;
};
//#endregion
//#region ../../packages/react/src/components/markdownText.ts
var defaultMarkdownRenderer = "full";
/**
* The part of `text` that truncating it to `maxLength` can depend on (plus
* one character, which keeps "was the text longer?"). Cutting to it first
* leaves the truncated result unchanged but bounds the work, and the length
* of what callers pass on or key caches by.
*/ var truncationWindow = (text, maxLength) => text.slice(0, maxLength * 8 + 1);
var escapeHtmlCharacters = (content) => {
	if (!content) return content;
	return content.replace(/[<>&'"]/g, (c) => {
		switch (c) {
			case "<": return "&lt;";
			case ">": return "&gt;";
			case "&": return "&amp;";
			case "'": return "&apos;";
			case "\"": return "&quot;";
			default: throw new Error("Matched a value that isn't replaceable");
		}
	});
};
/**
* Simple markdown truncation that falls back to basic string slicing
* This is a faster alternative when markdown parsing isn't critical
*/ function simpleMarkdownTruncate(markdown, maxLength = 250, ellipsis = "...") {
	if (!markdown || markdown.length <= maxLength) return markdown;
	const targetLength = maxLength - ellipsis.length;
	const truncated = markdown.slice(0, targetLength);
	const lastSpace = truncated.lastIndexOf(" ");
	if (lastSpace > 0) return truncated.slice(0, lastSpace) + ellipsis;
	return truncated + ellipsis;
}
//#endregion
export { base64DataUriMimeType as a, isRenderableImageSource as c, parseDataUri as d, truncationWindow as i, normalizedImageMimeType as l, escapeHtmlCharacters as n, canonicalImageSource as o, simpleMarkdownTruncate as r, isRasterImageMimeType as s, defaultMarkdownRenderer as t, parseAbsoluteHttpUrl as u };

//# sourceMappingURL=markdownText.js.map