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

  const centralDirOffset = eocdrView.getUint32(16, true);
  const centralDirSize = eocdrView.getUint32(12, true);

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
        // Defate compression
        const results = await decompressAsync(zipFileEntry.data, {
          size: zipFileEntry.uncompressedSize,
        });
        return results;
      } else {
        throw new Error(`Unsupported compressionMethod for file ${file}`);
      }
    },
  };
};

export const fetchSize = async (url: string): Promise<number> => {
  const response = await fetch(`${url}`, { method: "HEAD" });
  const contentLength = Number(response.headers.get("Content-Length"));
  return contentLength;
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
  const compressedSize = view.getUint32(offset, true);
  offset += 4;
  const uncompressedSize = view.getUint32(offset, true);
  offset += 4;
  const filenameLength = view.getUint16(offset, true);
  offset += 2;
  const extraFieldLength = view.getUint16(offset, true);
  offset += 2;

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
const parseCentralDirectory = (buffer: Uint8Array<ArrayBufferLike>) => {
  let offset = 0;
  const view = new DataView(buffer.buffer);
  const entries = new Map();

  while (offset < buffer.length) {
    // Central Directory signature
    if (view.getUint32(offset, true) !== 0x02014b50) break;

    const filenameLength = view.getUint16(offset + 28, true);
    const extraFieldLength = view.getUint16(offset + 30, true);
    const fileCommentLength = view.getUint16(offset + 32, true);

    const filename = new TextDecoder().decode(
      buffer.subarray(
        offset + kFileHeaderSize,
        offset + kFileHeaderSize + filenameLength,
      ),
    );

    // Read 32-bit file offset
    let fileOffset = view.getUint32(offset + 42, true);

    // If fileOffset is 0xFFFFFFFF, use the ZIP64 extended offset instead
    if (fileOffset === 0xffffffff) {
      // Move to extra field
      let extraOffset = offset + kFileHeaderSize + filenameLength;
      // Look through extra fields until we find zip64 extra field
      while (
        extraOffset <
        offset + kFileHeaderSize + filenameLength + extraFieldLength
      ) {
        const tag = view.getUint16(extraOffset, true);
        const size = view.getUint16(extraOffset + 2, true);
        if (tag === 0x0001) {
          // ZIP64 Extra Field - Read 64-bit offset
          fileOffset = Number(view.getBigUint64(extraOffset + 4, true));
          break;
        }
        extraOffset += 4 + size; // Move to next extra field
      }
    }

    const entry = {
      filename,
      compressionMethod: view.getUint16(offset + 10, true),
      compressedSize: view.getUint32(offset + 20, true),
      uncompressedSize: view.getUint32(offset + 24, true),
      fileOffset,
    };

    entries.set(filename, entry);
    offset +=
      kFileHeaderSize + filenameLength + extraFieldLength + fileCommentLength;
  }

  return entries;
};
