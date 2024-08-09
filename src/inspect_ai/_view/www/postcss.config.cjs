
// postcss.config.js
module.exports = {
    plugins: [
      require('postcss-url')({
        url: 'inline', // Inline all assets
        maxSize: Infinity, // Maximum file size to inline (in kilobytes). Adjust as needed.
        fallback: 'copy', // Copy files to output directory if they are larger than the maxSize
      }),
    ],
  };