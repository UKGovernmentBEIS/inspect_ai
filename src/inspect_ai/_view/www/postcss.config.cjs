// postcss.config.js
module.exports = {
  plugins: [
    require("postcss-import")({
      // Set the root directory for resolving imports to src
      root: require('path').resolve(__dirname, 'src'),
      // Add search paths
      path: [
        require('path').resolve(__dirname, 'src'),
        require('path').resolve(__dirname, 'src/app'),
        require('path').resolve(__dirname, 'src/components'),
        __dirname
      ],
      // Completely inline all imports - no relative paths left
      resolve: function(id, basedir, importOptions) {
        const path = require('path');
        const fs = require('fs');

        // For relative imports, always resolve from the src directory
        if (id.startsWith('./') || id.startsWith('../')) {
          // Remove the ./ prefix and resolve from src
          const cleanId = id.replace(/^\.\//, '');
          const srcPath = path.resolve(__dirname, 'src', cleanId);

          if (fs.existsSync(srcPath)) {
            return srcPath;
          }

          // Also try resolving relative to the current file's directory
          const relativePath = path.resolve(basedir, id);
          if (fs.existsSync(relativePath)) {
            return relativePath;
          }
        }

        // For absolute imports, try to resolve from src first
        if (!id.startsWith('./') && !id.startsWith('../') && !id.includes('node_modules')) {
          const srcPath = path.resolve(__dirname, 'src', id);
          if (fs.existsSync(srcPath)) {
            return srcPath;
          }
        }

        return id;
      }
    }),
    require("postcss-url")({
      url: "inline",
      maxSize: Infinity,
      fallback: "copy",
    }),
  ],
};

