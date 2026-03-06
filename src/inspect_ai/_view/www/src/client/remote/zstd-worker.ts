/**
 * Zstandard decompression via Web Worker.
 *
 * Provides a simple async interface for zstd decompression that automatically
 * uses a Web Worker for large payloads to avoid blocking the main thread.
 *
 * Uses Blob URL to load the worker, which works in VSCode webviews that have
 * CORS restrictions preventing external worker script loading.
 */

import { decompress as decompressZstdSync } from "fzstd";

import { kFzstdBase64, kZstdWorkerCode } from "./zstd-worker-code";

/**
 * Threshold for using Web Worker (1MB compressed).
 * Below this, synchronous decompression is fast enough.
 */
const WORKER_THRESHOLD = 1024 * 1024;

/**
 * Maximum window log supported by fzstd (2^25 = 32MB).
 * Ultra compression levels (20+) often use larger windows.
 */
const MAX_WINDOW_LOG = 25;

/**
 * Error thrown when zstd data uses a window size too large for fzstd.
 */
export class ZstdWindowSizeError extends Error {
  public readonly windowLog: number;
  public readonly maxWindowLog: number;

  constructor(windowLog: number) {
    super(
      `Zstd window size too large (windowLog=${windowLog}, max=${MAX_WINDOW_LOG}). ` +
        `This file may have been compressed with zstd "ultra" mode (level 20+). ` +
        `Try recompressing with --long=${MAX_WINDOW_LOG} or a lower compression level.`,
    );
    this.name = "ZstdWindowSizeError";
    this.windowLog = windowLog;
    this.maxWindowLog = MAX_WINDOW_LOG;

    Object.setPrototypeOf(this, ZstdWindowSizeError.prototype);
  }
}

/**
 * Validates that the zstd frame's window size is within fzstd's limits.
 * Parses the frame header to extract the window descriptor.
 *
 * @param data - The zstd-compressed data
 * @throws ZstdWindowSizeError if window size exceeds 2^25 bytes
 */
function validateZstdWindowSize(data: Uint8Array): void {
  // Need at least 5 bytes for magic + frame header descriptor
  if (data.length < 5) {
    return; // Let fzstd handle malformed data
  }

  // Check magic number (0xFD2FB528, little-endian)
  const magic = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24);
  if (magic !== 0xfd2fb528) {
    return; // Not a zstd frame, let fzstd handle it
  }

  // Frame header descriptor byte
  const descriptor = data[4];

  // Single_Segment_flag is bit 5
  const singleSegmentFlag = (descriptor >> 5) & 1;

  if (singleSegmentFlag) {
    // No window descriptor - window size equals frame content size
    // Frame content size is in the header, but for single-segment frames
    // fzstd should handle this fine as long as we have enough memory
    return;
  }

  // Window descriptor is at byte 5 (after magic + descriptor)
  if (data.length < 6) {
    return;
  }

  const windowDescriptor = data[5];
  const exponent = windowDescriptor >> 3; // bits 7-3
  const windowLog = 10 + exponent;

  if (windowLog > MAX_WINDOW_LOG) {
    throw new ZstdWindowSizeError(windowLog);
  }
}

/** Cached worker and blob URL */
let zstdWorker: Worker | null = null;
let blobURL: string | null = null;
let workerInitPromise: Promise<Worker> | null = null;

/** Request ID counter for worker messages */
let nextRequestId = 0;

/** Pending decompression requests */
const pendingRequests = new Map<
  number,
  { resolve: (value: Uint8Array) => void; reject: (error: Error) => void }
>();

/** Whether message handlers have been attached to the worker */
let handlersAttached = false;

/**
 * Gets or creates the zstd decompression worker.
 * Uses a Blob URL to work in VSCode webviews which have CORS restrictions.
 * Returns a promise that resolves when the worker is fully initialized.
 */
function getZstdWorker(): Promise<Worker> {
  if (workerInitPromise) {
    return workerInitPromise;
  }

  workerInitPromise = new Promise((resolve, reject) => {
    // Create worker from inline code using Blob URL
    // This avoids CORS issues in VSCode webviews
    const blob = new Blob([kZstdWorkerCode], {
      type: "application/javascript",
    });
    blobURL = URL.createObjectURL(blob);
    zstdWorker = new Worker(blobURL);

    // Wait for init confirmation before resolving
    const initHandler = (event: MessageEvent) => {
      if (event.data.type === "init_complete") {
        zstdWorker!.removeEventListener("message", initHandler);
        if (event.data.success) {
          resolve(zstdWorker!);
        } else {
          reject(new Error(event.data.error || "Worker initialization failed"));
        }
      }
    };
    zstdWorker.addEventListener("message", initHandler);

    // Send the fzstd library code to initialize the worker
    zstdWorker.postMessage({
      type: "init",
      scriptContent: kFzstdBase64,
    });
  });

  return workerInitPromise;
}

/**
 * Decompresses zstd-compressed data.
 *
 * For small payloads (< 1MB), uses synchronous decompression.
 * For larger payloads, uses a Web Worker to avoid blocking the main thread.
 *
 * Data transfer efficiency:
 * - Input data is transferred (zero-copy) to the worker
 * - Output data is transferred (zero-copy) back from the worker
 *
 * @param data - The zstd-compressed data
 * @returns Promise resolving to the decompressed data
 */
export async function decompressZstd(data: Uint8Array): Promise<Uint8Array> {
  // Check window size before attempting decompression
  validateZstdWindowSize(data);

  // For small data, synchronous is faster (avoids worker overhead)
  if (data.length < WORKER_THRESHOLD) {
    return decompressZstdSync(data);
  }

  // For large data, use Web Worker to avoid blocking UI
  // Wait for worker to be fully initialized first
  const worker = await getZstdWorker();

  return new Promise((resolve, reject) => {
    const requestId = nextRequestId++;

    pendingRequests.set(requestId, { resolve, reject });

    // Only add listeners once
    if (!handlersAttached) {
      handlersAttached = true;

      worker.addEventListener("message", (event: MessageEvent) => {
        const {
          requestId: respId,
          success,
          data: resultData,
          error,
        } = event.data;
        const pending = pendingRequests.get(respId);
        if (!pending) return;

        pendingRequests.delete(respId);

        if (success) {
          pending.resolve(resultData);
        } else {
          pending.reject(new Error(error || "Decompression failed"));
        }
      });

      worker.addEventListener("error", (error: ErrorEvent) => {
        // Reject all pending requests on worker error
        for (const [id, pending] of pendingRequests) {
          pending.reject(new Error(`Worker error: ${error.message}`));
          pendingRequests.delete(id);
        }
      });
    }

    // Transfer the input buffer to avoid copying (zero-copy transfer)
    // Note: After transfer, the original data.buffer becomes detached/unusable
    worker.postMessage(
      {
        type: "decompress",
        requestId,
        data,
      },
      [data.buffer],
    );
  });
}
