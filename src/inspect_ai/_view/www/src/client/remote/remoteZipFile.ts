import { AsyncInflateOptions, decompress } from "fflate";

export interface ZipFileEntry {
  versionNeeded: number;
  bitFlag: number;
  compressionMethod: number;
  crc32: number;
  compressedSize: number;
  uncompressedSize: number;
  filenameLength: number;
  extraFieldLength: number;
  data: Uint8Array;
}

export interface CentralDirectoryEntry {
  filename: string;
  compressionMethod: number;
  compressedSize: number;
  uncompressedSize: number;
  fileOffset: number;
}

/**
 * Represents an error thrown when a file exceeds the maximum allowed size.
 */
export class FileSizeLimitError extends Error {
  public readonly file: string;
  public readonly maxBytes: number;

  constructor(file: string, maxBytes: number) {
    super(
      `File "${file}" exceeds the maximum size (${maxBytes} bytes) and cannot be loaded.`,
    );
    this.name = "FileSizeLimitError";
    this.file = file;
    this.maxBytes = maxBytes;

    Object.setPrototypeOf(this, FileSizeLimitError.prototype);
  }
}

/**
 * Opens a remote ZIP file from the specified URL, fetches and parses the central directory,
 * and provides a method to read files within the ZIP.
 */
export const openRemoteZipFile = async (
  url: string,
  fetchContentLength: (url: string) => Promise<number> = fetchSize,
  fetchBytes: (
    url: string,
    start: number,
    end: number,
  ) => Promise<Uint8Array> = fetchRange,
): Promise<{
  centralDirectory: Map<string, CentralDirectoryEntry>;
  readFile: (file: string, maxBytes?: number) => Promise<Uint8Array>;
}> => {
  const contentLength = await fetchContentLength(url);

  // Read the end of central directory record
  const eocdrBuffer = await fetchBytes(
    url,
    contentLength - 22,
    contentLength - 1,
  );
  const eocdrView = new DataView(eocdrBuffer.buffer);

  // Check signature to make sure we found the EOCD record
  if (eocdrView.getUint32(0, true) !== 0x06054b50) {
    if (eocdrBuffer.length !== 22) {
      // The range request seems like it was ignored because more bytes than
      // were requested were returned.
      throw new Error(
        "Unexpected central directory size - does the HTTP server serving this file support HTTP range requests?",
      );
    } else {
      throw new Error("End of central directory record not found");
    }
  }

  let centralDirOffset = eocdrView.getUint32(16, true);
  let centralDirSize = eocdrView.getUint32(12, true);

  // Check if we need to use ZIP64 format
  const needsZip64 =
    centralDirOffset === 0xffffffff || centralDirSize === 0xffffffff;

  if (needsZip64) {
    // We need to locate and read the ZIP64 EOCD record and locator
    // First, read the ZIP64 EOCD locator which is just before the standard EOCD
    // Standard EOCD (22 bytes) + Locator (20 bytes)
    const locatorBuffer = await fetchBytes(
      url,
      contentLength - 22 - 20,
      contentLength - 23,
    );
    const locatorView = new DataView(locatorBuffer.buffer);

    // Verify the ZIP64 EOCD locator signature
    if (locatorView.getUint32(0, true) !== 0x07064b50) {
      throw new Error("ZIP64 End of central directory locator not found");
    }

    // Get the offset to the ZIP64 EOCD record
    const zip64EOCDOffset = Number(locatorView.getBigUint64(8, true));

    // Now read the ZIP64 EOCD record
    const zip64EOCDBuffer = await fetchBytes(
      url,
      zip64EOCDOffset,
      zip64EOCDOffset + 56,
    );
    const zip64EOCDView = new DataView(zip64EOCDBuffer.buffer);

    // Verify the ZIP64 EOCD signature
    if (zip64EOCDView.getUint32(0, true) !== 0x06064b50) {
      throw new Error("ZIP64 End of central directory record not found");
    }

    // Get the 64-bit central directory size and offset
    centralDirSize = Number(zip64EOCDView.getBigUint64(40, true));
    centralDirOffset = Number(zip64EOCDView.getBigUint64(48, true));
  }

  // Fetch and parse the central directory
  const centralDirBuffer = await fetchBytes(
    url,
    centralDirOffset,
    centralDirOffset + centralDirSize - 1,
  );
  const centralDirectory = parseCentralDirectory(centralDirBuffer);

  return {
    centralDirectory: centralDirectory,
    readFile: async (file, maxBytes): Promise<Uint8Array> => {
      const entry = centralDirectory.get(file);
      if (!entry) {
        throw new Error(`File not found: ${file}`);
      }

      // Local file header is 30 bytes long by spec
      const headerSize = 30;
      const headerData = await fetchBytes(
        url,
        entry.fileOffset,
        entry.fileOffset + headerSize - 1,
      );

      // Parse the local file header to get the filename length and extra field length
      // 26-27 bytes in local header
      const filenameLength = headerData[26] + (headerData[27] << 8);

      // 28-29 bytes in local header
      const extraFieldLength = headerData[28] + (headerData[29] << 8);

      // Use the entry's compressed size from the central directory
      const totalSizeToFetch =
        headerSize + filenameLength + extraFieldLength + entry.compressedSize;

      // Throw an error if this request exceeds our maximum size
      if (maxBytes && totalSizeToFetch > maxBytes) {
        throw new FileSizeLimitError(file, maxBytes);
      }

      // Use the total size to fetch the compressed data
      const fileData = await fetchBytes(
        url,
        entry.fileOffset,
        entry.fileOffset + totalSizeToFetch - 1,
      );

      // Parse and decompress the entry
      const zipFileEntry = await parseZipFileEntry(file, fileData);
      if (zipFileEntry.compressionMethod === 0) {
        // No compression
        return zipFileEntry.data;
      } else if (zipFileEntry.compressionMethod === 8) {
        // Deflate compression
        const results = await decompressAsync(zipFileEntry.data, {
          size: zipFileEntry.uncompressedSize,
        });
        return results;
      } else {
        throw new Error(`Unsupported compression method for file ${file}`);
      }
    },
  };
};

export const fetchSize = async (url: string): Promise<number> => {
  // Make a HEAD request to find whether the server supports range requests
  const acceptResponse = await fetch(url, { method: "HEAD" });
  const acceptsRanges = acceptResponse.headers.get("Accept-Ranges");
  if (acceptsRanges === "bytes") {
    // attempt a range request to get the content length
    // Range requests are preferred since they bypass compression.
    // HEAD requests may return compressed content-length which doesn't
    // match the actual file size needed for downstream operations.
    const getResponse = await fetch(`${url}`, {
      method: "GET",
      headers: { Range: "bytes=0-0" },
    });

    const contentRange = getResponse.headers.get("Content-Range");
    if (contentRange !== null) {
      const rangeMatch = contentRange.match(/bytes (\d+)-(\d+)\/(\d+)/);
      if (rangeMatch !== null) {
        return Number(rangeMatch[3]);
      }
    }
  }

  //  use the HEAD request to get Content-Length
  const contentLength = acceptResponse.headers.get("Content-Length");
  if (contentLength !== null) {
    return Number(contentLength);
  }

  throw new Error(`Could not determine content length for ${url}`);
};

/**
 * Fetches a range of bytes from a remote resource and returns it as a `Uint8Array`.
 */
export const fetchRange = async (
  url: string,
  start: number,
  end: number,
): Promise<Uint8Array> => {
  const response = await fetch(`${url}`, {
    headers: { Range: `bytes=${start}-${end}` },
  });
  const arrayBuffer = await response.arrayBuffer();
  return new Uint8Array(arrayBuffer);
};

/**
 * Asynchronously decompresses the provided data using the specified options.
 */
const decompressAsync = async (
  data: Uint8Array,
  opts: AsyncInflateOptions,
): Promise<Uint8Array> => {
  return new Promise((resolve, reject) => {
    decompress(data, opts, (err, result) => {
      if (err) {
        reject(err);
      } else {
        resolve(result);
      }
    });
  });
};

/**
 * Extracts and parses the header and data of a compressed ZIP entry from raw binary data.
 */
const parseZipFileEntry = async (
  file: string,
  rawData: Uint8Array,
): Promise<ZipFileEntry> => {
  // Parse ZIP entry header
  const view = new DataView(rawData.buffer);
  let offset = 0;
  const signature = view.getUint32(offset, true);
  if (signature !== 0x04034b50) {
    throw new Error(`Invalid ZIP entry signature for ${file}`);
  }
  offset += 4;

  const versionNeeded = view.getUint16(offset, true);
  offset += 2;
  const bitFlag = view.getUint16(offset, true);
  offset += 2;
  const compressionMethod = view.getUint16(offset, true);
  offset += 2;
  offset += 4; // Skip last mod time and date
  const crc32 = view.getUint32(offset, true);
  offset += 4;

  // Get initial sizes from standard header
  let compressedSize = view.getUint32(offset, true);
  offset += 4;
  let uncompressedSize = view.getUint32(offset, true);
  offset += 4;

  const filenameLength = view.getUint16(offset, true);
  offset += 2;
  const extraFieldLength = view.getUint16(offset, true);
  offset += 2;

  // The original header offset
  const headerOffset = offset;

  // Check if we need to look for ZIP64 extra fields
  const needsZip64 =
    compressedSize === 0xffffffff || uncompressedSize === 0xffffffff;

  if (needsZip64) {
    // Skip the filename
    offset += filenameLength;

    // Look through extra fields for ZIP64 data
    const extraFieldEnd = offset + extraFieldLength;
    while (offset < extraFieldEnd) {
      const tag = view.getUint16(offset, true);
      const size = view.getUint16(offset + 2, true);

      if (tag === 0x0001) {
        // ZIP64 Extra Field
        // Position in the extra field data
        let zip64Offset = offset + 4;

        // Read values in the order they appear in the ZIP64 extra field
        if (
          uncompressedSize === 0xffffffff &&
          zip64Offset + 8 <= extraFieldEnd
        ) {
          uncompressedSize = Number(view.getBigUint64(zip64Offset, true));
          zip64Offset += 8;
        }

        if (compressedSize === 0xffffffff && zip64Offset + 8 <= extraFieldEnd) {
          compressedSize = Number(view.getBigUint64(zip64Offset, true));
        }

        break;
      }
      offset += 4 + size;
    }

    // Reset offset
    offset = headerOffset;
  }

  // Skip filename and extra field to get to the data
  offset += filenameLength + extraFieldLength;

  const data = rawData.subarray(offset, offset + compressedSize);
  return {
    versionNeeded,
    bitFlag,
    compressionMethod,
    crc32,
    compressedSize,
    uncompressedSize,
    filenameLength,
    extraFieldLength,
    data,
  };
};

const kFileHeaderSize = 46;
/**
 * Parses the central directory of a ZIP file from the provided buffer and returns a map of entries.
 */
const parseCentralDirectory = (buffer: Uint8Array) => {
  let offset = 0;
  const view = new DataView(buffer.buffer);
  const entries = new Map();

  while (offset < buffer.length) {
    // Central Directory signature
    if (view.getUint32(offset, true) !== 0x02014b50) break;

    const filenameLength = view.getUint16(offset + 28, true);
    const extraFieldLength = view.getUint16(offset + 30, true);
    const fileCommentLength = view.getUint16(offset + 32, true);

    // Get initial 32-bit values
    let compressedSize = view.getUint32(offset + 20, true);
    let uncompressedSize = view.getUint32(offset + 24, true);
    let fileOffset = view.getUint32(offset + 42, true);

    const filename = new TextDecoder().decode(
      buffer.subarray(
        offset + kFileHeaderSize,
        offset + kFileHeaderSize + filenameLength,
      ),
    );

    // Check if we need to use ZIP64 extra fields
    const needsZip64 =
      fileOffset === 0xffffffff ||
      compressedSize === 0xffffffff ||
      uncompressedSize === 0xffffffff;

    if (needsZip64) {
      // Move to extra field
      let extraOffset = offset + kFileHeaderSize + filenameLength;
      const extraEnd = extraOffset + extraFieldLength;

      // Look through extra fields until we find zip64 extra field
      while (extraOffset < extraEnd) {
        const tag = view.getUint16(extraOffset, true);
        const size = view.getUint16(extraOffset + 2, true);

        if (tag === 0x0001) {
          // ZIP64 Extra Field
          // Position in the extra field data
          let zip64Offset = extraOffset + 4;

          // Read values in the order they appear in the ZIP64 extra field
          if (uncompressedSize === 0xffffffff && zip64Offset + 8 <= extraEnd) {
            uncompressedSize = Number(view.getBigUint64(zip64Offset, true));
            zip64Offset += 8;
          }

          if (compressedSize === 0xffffffff && zip64Offset + 8 <= extraEnd) {
            compressedSize = Number(view.getBigUint64(zip64Offset, true));
            zip64Offset += 8;
          }

          if (fileOffset === 0xffffffff && zip64Offset + 8 <= extraEnd) {
            fileOffset = Number(view.getBigUint64(zip64Offset, true));
          }

          break;
        }
        extraOffset += 4 + size;
      }
    }

    const entry = {
      filename,
      compressionMethod: view.getUint16(offset + 10, true),
      compressedSize,
      uncompressedSize,
      fileOffset,
    };

    entries.set(filename, entry);
    offset +=
      kFileHeaderSize + filenameLength + extraFieldLength + fileCommentLength;
  }

  return entries;
};
