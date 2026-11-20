// webpack plugin for the build slots (<clone>-slotN): node_modules is shared through a junction, so webpack names the modules that live there
// "../dwc-src/node_modules/..." (relative to the slot) instead of "./node_modules/...". A plugin chunk asks the DWC it is installed in for shared
// modules (e.g. vue-loader's componentNormalizer) BY ID, and that DWC knows them as "./node_modules/...": the id must not depend on the clone name.
// After webpack assigns the ids this rewrites "../<any clone>/node_modules/" to "./node_modules/", also inside loader chains ("a!b!./src/x.vue").
const PATTERN = /\.\.\/[^/!?]+\/node_modules\//g;

class StableModuleIds {
  apply(compiler) {
    compiler.hooks.compilation.tap("StableModuleIds", (compilation) => {
      compilation.hooks.afterOptimizeModuleIds.tap("StableModuleIds", (modules) => {
        for (const module of modules) {
          const id = compilation.chunkGraph.getModuleId(module);
          if (typeof id === "string" && id.includes("/node_modules/") && /\.\.\/[^/!?]+\/node_modules\//.test(id)) {
            compilation.chunkGraph.setModuleId(module, id.replace(PATTERN, "./node_modules/"));
          }
        }
      });
    });
  }
}

module.exports = StableModuleIds;
