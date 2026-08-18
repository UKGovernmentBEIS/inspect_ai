// Convert an Excalidraw JSON file to SVG.
//
// Usage: node excalidraw-to-svg.mjs <input.excalidraw> <output.svg> [options]
//
// Options:
//   --theme light|dark    (default: light)
//   --background          include background fill (default: no background)
//   --padding <number>    padding in px (default: 10)
//   --scale <number>      export scale factor (default: 1)
//
// Uses JSDOM to provide a DOM environment for @excalidraw/utils.

import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { deflateSync } from "node:zlib";
import { JSDOM, VirtualConsole } from "jsdom";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    theme: { type: "string", default: "light" },
    background: { type: "boolean", default: false },
    padding: { type: "string", default: "10" },
    scale: { type: "string", default: "1" },
  },
});

const [inputPath, outputPath] = positionals;

if (!inputPath || !outputPath) {
  console.error(
    "Usage: node excalidraw-to-svg.mjs <input> <output> [--theme light|dark] [--background] [--padding N] [--scale N]"
  );
  process.exit(1);
}

// Read the excalidraw diagram and apply CLI options to appState
const data = JSON.parse(readFileSync(inputPath, "utf-8"));

data.appState = {
  ...(data.appState ?? {}),
  exportWithDarkMode: values.theme === "dark",
  exportBackground: values.background,
  exportPadding: parseInt(values.padding, 10),
  exportScale: parseFloat(values.scale),
};

// Load @excalidraw/utils and canvas-5-polyfill as raw scripts for JSDOM
const __dirname = dirname(fileURLToPath(import.meta.url));
const excalidrawUtilsJs = readFileSync(
  join(__dirname, "node_modules/@excalidraw/utils/dist/excalidraw-utils.min.js"),
  "utf-8"
);
const path2DPolyfillJs = readFileSync(
  join(__dirname, "node_modules/canvas-5-polyfill/canvas.js"),
  "utf-8"
);

const diagram = JSON.stringify(data);

// Minimal canvas mock — excalidraw uses canvas for text measurement, but
// .excalidraw files already contain pre-computed width/height/baseline
// from the editor, so approximate values are sufficient.
const canvasMock = `
class CanvasRenderingContext2D {
  constructor() {
    this.font = "10px sans-serif";
    this.canvas = { width: 300, height: 150 };
  }
  measureText(text) {
    const fontSize = parseFloat(this.font) || 10;
    const width = text.length * fontSize * 0.6;
    return {
      width,
      actualBoundingBoxAscent: fontSize * 0.8,
      actualBoundingBoxDescent: fontSize * 0.2,
      actualBoundingBoxLeft: 0,
      actualBoundingBoxRight: width,
      fontBoundingBoxAscent: fontSize * 0.8,
      fontBoundingBoxDescent: fontSize * 0.2,
    };
  }
  getImageData() { return { data: new Uint8ClampedArray(4) }; }
  putImageData() {} createImageData() { return { data: new Uint8ClampedArray(4) }; }
  setTransform() { return this; } resetTransform() {} transform() {}
  translate() {} rotate() {} scale() {} save() {} restore() {}
  beginPath() {} closePath() {} moveTo() {} lineTo() {}
  bezierCurveTo() {} quadraticCurveTo() {} arc() {} arcTo() {}
  ellipse() {} rect() {} fill() {} stroke() {} clip() {}
  fillRect() {} strokeRect() {} clearRect() {}
  fillText() {} strokeText() {} drawImage() {}
  createLinearGradient() { return { addColorStop() {} }; }
  createRadialGradient() { return { addColorStop() {} }; }
  createPattern() { return {}; }
  setLineDash() {} getLineDash() { return []; }
  isPointInPath() { return false; } isPointInStroke() { return false; }
}
HTMLCanvasElement.prototype.getContext = function(type) {
  if (type === "2d") return new CanvasRenderingContext2D();
  return null;
};
`;

const html =
  "<body><script>" +
  canvasMock +
  path2DPolyfillJs +
  excalidrawUtilsJs +
  ";(async function(){" +
  "var svg=await ExcalidrawUtils.exportToSvg(" + diagram + ");" +
  "document.body.appendChild(svg)" +
  "})()" +
  "</script></body>";

// Suppress JSDOM errors (canvas not-implemented warnings, CSS injection)
const virtualConsole = new VirtualConsole();
virtualConsole.on("error", () => {});

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  resources: "usable",
  pretendToBeVisual: true,
  virtualConsole,
});

// Wait for the SVG to appear in the DOM
const svg = await new Promise((resolve, reject) => {
  let attempts = 100;
  const interval = setInterval(() => {
    const svgEl = dom.window.document.body.querySelector("svg");
    if (svgEl) {
      clearInterval(interval);
      resolve(svgEl);
    } else if (--attempts <= 0) {
      clearInterval(interval);
      reject(new Error("SVG was not created within the expected time"));
    }
  }, 20);
});

// Embed the original scene data so the SVG is editable in Excalidraw.
// Format matches Excalidraw's encodeSvgMetadata: deflate + base64 + payload markers.
// Must use btoa() (Latin-1) not Buffer.toString("base64") (UTF-8) since the
// compressed binary string has bytes > 127 that encode differently in each.
const sceneJson = readFileSync(inputPath, "utf-8");
const compressed = deflateSync(Buffer.from(sceneJson, "utf-8"));
const encoded = btoa(
  JSON.stringify({
    version: "1",
    encoding: "bstring",
    compressed: true,
    encoded: compressed.toString("binary"),
  })
);

const payload =
  "<!-- payload-type:application/vnd.excalidraw+json -->" +
  "<!-- payload-version:2 -->" +
  "<!-- payload-start -->" +
  encoded +
  "<!-- payload-end -->";

let svgString = svg.outerHTML;
// Insert payload after the opening <svg> tag
svgString = svgString.replace(
  /(<svg[^>]*>)/,
  "$1" + payload
);

// Replace remote Cascadia font with system monospace fallbacks
svgString = svgString.replace(
  /src: url\("https:\/\/excalidraw\.com\/Cascadia\.woff2"\);/g,
  "/* remote font replaced with system monospace */",
);
svgString = svgString.replace(
  /font-family="Cascadia, Segoe UI Emoji"/g,
  `font-family="'SFMono-Regular', Menlo, Consolas, 'Courier New', monospace"`,
);

writeFileSync(resolve(outputPath), svgString, "utf-8");
dom.window.close();
