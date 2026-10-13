# Decky API 1.1.3 corresponding source

`src/index.ts`, `src/types.ts`, `src/types.d.ts` and `package.json` retain the unmodified source content of the installed `@decky/api` 1.1.3 npm package. Line endings may be normalized between LF and CRLF; the source content is unmodified. The complete LGPL 2.1 license is in [../decky-api-LGPL-2.1.txt](../decky-api-LGPL-2.1.txt).

Original project: [SteamDeckHomebrew/loader-api](https://github.com/SteamDeckHomebrew/loader-api). Exact published package, including its source and compiled JavaScript: [api-1.1.3.tgz](https://registry.npmjs.org/@decky/api/-/api-1.1.3.tgz).

The HelixSR Decky Armada frontend combines the API with its own TypeScript application using Rollup. Complete application source and build configuration are supplied in the [Armada fork](https://github.com/dawoodtogoo2020-code/HelixSR-Decky-Armada). The dependency versions are recorded in `package.json` and `pnpm-lock.yaml`. The public experimental release includes the complete source archive at the matching tag. Its README documents `pnpm install`, `pnpm typecheck` and `pnpm build`.

To rebuild with a changed API, obtain the application source, install the declared dependencies, modify/recompile this library using its TypeScript source and replace the installed `@decky/api` module with that build, then run the application build again. Rollup supplies the virtual `@decky/manifest` import from the plugin manifest. `react`, `react-dom` and `@decky/ui` remain runtime externals. The resulting `dist/index.js` can be repackaged with `python3 scripts/package_armada.py` and installed through Decky's local ZIP picker.

The plugin license permits application modification. Modification of the API and reverse engineering for debugging such library modifications are permitted under the LGPL terms. No generated HelixSR weights, game DLLs or private device data are part of this source directory.
