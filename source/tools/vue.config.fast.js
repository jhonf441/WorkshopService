// vue-cli config used by tools/build_36.py to compile the service page quickly (VUE_CLI_SERVICE_CONFIG_PATH). It wraps the config of the
// DWC 3.6 clone without touching it (same idea as TallerPlugins/tools/vue.config.fast.js):
//   - persistent webpack cache (filesystem): the second build only recompiles what changed
//   - no source maps (devtool), no .gz copies (CompressionPlugin), no service worker (workbox): none of them is packed in the release zip
//     (tools/release_zips.py finalize_zip drops the maps and makes its own .gz from the final bytes)
// `python tools/build_36.py --completa` (or TALLER_BUILD_COMPLETO=1) uses the stock config again.
const path = require("path");
const dwc = process.env.TALLER_DWC_SRC || path.resolve(__dirname, "..", "..", "dwc-src");
const base = require(path.join(dwc, "vue.config.js"));
const { merge } = require(path.join(dwc, "node_modules", "webpack-merge"));
const CompressionPlugin = require(path.join(dwc, "node_modules", "compression-webpack-plugin"));
const StableModuleIds = require("./webpack-stable-module-ids");

const cfg = base.configureWebpack || {};
const sinGz = Object.assign({}, cfg, { plugins: (cfg.plugins || []).filter((p) => !(p instanceof CompressionPlugin)) });

module.exports = Object.assign({}, base, {
  productionSourceMap: false,
  configureWebpack: merge(sinGz, {
    devtool: false,
    // build slots reach node_modules through a junction: keep the module ids "./node_modules/..." (copy of TallerPlugins/tools/webpack-stable-module-ids.js)
    plugins: [new StableModuleIds()],
    cache: {
      type: "filesystem",
      cacheDirectory: path.join(dwc, "node_modules", ".cache", "taller-webpack-service"),
      buildDependencies: { config: [__filename, path.join(dwc, "vue.config.js")] },
    },
  }),
  chainWebpack: (config) => {
    if (base.chainWebpack) base.chainWebpack(config);
    config.plugins.delete("workbox");
  },
});
