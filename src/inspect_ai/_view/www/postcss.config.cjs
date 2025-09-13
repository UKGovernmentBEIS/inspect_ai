// postcss.config.js
module.exports = {
  plugins: [
    require("postcss-url")({
      url: "inline",
      maxSize: Infinity,
      fallback: "copy",
    }),
  ],
};
