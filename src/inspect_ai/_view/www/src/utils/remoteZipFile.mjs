//@ts-check
import { decompress } from "fflate";

/**
 * @typedef {Object} ZipFileEntry
 * @property {number} versionNeeded - The minimum version needed to extract the ZIP entry.
 * @property {number} bitFlag - The general purpose bit flag of the ZIP entry.
 * @property {number} compressionMethod - The compression method used for the ZIP entry.
 * @property {number} crc32 - The CRC-32 checksum of the uncompressed data.
 * @property {number} compressedSize - The size of the compressed data in bytes.
 * @property {number} uncompressedSize - The size of the uncompressed data in bytes.
 * @property {number} filenameLength - The length of the filename in bytes.
 * @property {number} extraFieldLength - The length of the extra field in bytes.
 * @property {Uint8Array} data - The compressed data for the ZIP entry.
 */

/**
 * @typedef {Object} CentralDirectoryEntry
 * @property {string} filename - The name of the file in the ZIP archive.
 * @property {number} compressionMethod - The compression method used for the file.
 * @property {number} compressedSize - The size of the compressed file in bytes.
 * @property {number} uncompressedSize - The size of the uncompressed file in bytes.
 * @property {number} fileOffset - The offset of the file's data in the ZIP archive.
 */

/**
 * Represents an error thrown when a file exceeds the maximum allowed size.
 *
 * @class
 * @extends {Error}
 */
export class FileSizeLimitError extends Error {
  /**
   * Creates a new FileSizeLimitError.
   *
   * @param {string} file - The name of the file that caused the error.
   * @param {number} maxBytes - The maximum allowed size for the file, in bytes.
   */
  constructor(file, maxBytes) {
    super(
      `File "${file}" exceeds the maximum size (${maxBytes} bytes) and cannot be loaded.`,
    );
    this.name = "FileSizeLimitError";
    this.file = file;
    this.maxBytes = maxBytes;
  }
}

/**
 * Opens a remote ZIP file from the specified URL, fetches and parses the central directory,
 * and provides a method to read files within the ZIP.
 *
 * @param {string} url - The URL of the remote ZIP file.
 * @param {(url: string) => Promise<number>} [fetchContentLength] - Optional function to compute the content length of the remote file.
 * @param {(url: string, start: number, end: number) => Promise<Uint8Array>} [fetchBytes] - Optional function to fetch a range of bytes from the remote file.
 * @returns {Promise<{
 *   centralDirectory: Map<string, CentralDirectoryEntry>,
 *   readFile: (file: string, maxBytes?: number) => Promise<Uint8Array>
 * }>} A promise that resolves with an object containing:
 *   - `centralDirectory`: A map where keys are filenames and values are their corresponding central directory entries.
 *   - `readFile`: A function to read a specific file from the ZIP archive by name.
 *                  Takes the filename and an optional maximum byte length to read.
 * @throws {Error} If the file is not found or if an unsupported compression method is encountered.
 */
export const openRemoteZipFile = async (
  url,
  fetchContentLength = fetchSize,
  fetchBytes = fetchRange,
) => {
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
    readFile: async (file, maxBytes) => {
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

export const fetchSize = async (url) => {
  const response = await fetch(`${url}`, { method: "HEAD" });
  const contentLength = Number(response.headers.get("Content-Length"));
  return contentLength;
};

/**
 * Fetches a range of bytes from a remote resource and returns it as a `Uint8Array`.
 *
 * @param {string} url - The URL of the remote resource to fetch.
 * @param {number} start - The starting byte position of the range to fetch.
 * @param {number} end - The ending byte position of the range to fetch.
 * @returns {Promise<Uint8Array>} A promise that resolves to a `Uint8Array` containing the fetched byte range.
 * @throws {Error} If there is an issue with the network request.
 */
export const fetchRange = async (url, start, end) => {
  const response = await fetch(`${url}`, {
    headers: { Range: `bytes=${start}-${end}` },
  });
  const arrayBuffer = await response.arrayBuffer();
  return new Uint8Array(arrayBuffer);
};

/**
 * Asynchronously decompresses the provided data using the specified options.
 *
 * @param {Uint8Array} data - The compressed data to be decompressed.
 * @param {Object} opts - Options to configure the decompression process.
 * @returns {Promise<Uint8Array>} A promise that resolves with the decompressed data.
 * @throws {Error} If an error occurs during decompression, the promise is rejected with the error.
 */
const decompressAsync = async (data, opts) => {
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
 *
 * @param {string} file - The name of the file stream to be parsed
 * @param {Uint8Array} rawData - The raw binary data containing the ZIP entry.
 * @returns {Promise<ZipFileEntry>} A promise that resolves to an object containing the ZIP entry's header information and compressed data.
 * @throws {Error} If the ZIP entry signature is invalid.
 */
const parseZipFileEntry = async (file, rawData) => {
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

/**
 * Parses the central directory of a ZIP file from the provided buffer and returns a map of entries.
 *
 * @param {Uint8Array} buffer - The raw binary data containing the central directory of the ZIP archive.
 * @returns {Map<string, CentralDirectoryEntry>} A map where the key is the filename and the value is the corresponding central directory entry.
 * @throws {Error} If the buffer does not contain a valid central directory signature.
 */
const parseCentralDirectory = (buffer) => {
  let offset = 0;
  const view = new DataView(buffer.buffer);

  const entries = new Map();
  while (offset < buffer.length) {
    // Make sure there is a central directory signature
    if (view.getUint32(offset, true) !== 0x02014b50) break;

    const filenameLength = view.getUint16(offset + 28, true);
    const extraFieldLength = view.getUint16(offset + 30, true);
    const fileCommentLength = view.getUint16(offset + 32, true);

    const filename = new TextDecoder().decode(
      buffer.subarray(offset + 46, offset + 46 + filenameLength),
    );

    const entry = {
      filename,
      compressionMethod: view.getUint16(offset + 10, true),
      compressedSize: view.getUint32(offset + 20, true),
      uncompressedSize: view.getUint32(offset + 24, true),
      fileOffset: view.getUint32(offset + 42, true),
    };

    entries.set(filename, entry);

    offset += 46 + filenameLength + extraFieldLength + fileCommentLength;
  }
  return entries;
};
