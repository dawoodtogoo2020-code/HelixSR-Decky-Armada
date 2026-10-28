# HelixSR Decky Armada: Adreno preview

Version **0.5.0-adreno-preview** adds HelixSR 2.0 controls for **PRAGMATA on Odin 3 running Armada Linux**. HelixSR is by [lonewolf0622](https://github.com/lonewolf0622/HelixSR); this free, unofficial plugin is by Blackheart909.

[Download the plugin](https://github.com/dawoodtogoo2020-code/HelixSR-Decky-Armada/releases/tag/v0.5.0-adreno-preview) · [Validation](RELEASE_STATUS.md)

The plugin recognizes the tested locally built 2.0 FSR provider, preserves the existing game settings and launcher, and exposes INT8, wave size, network resolution and reactive-mask settings. It can adopt the existing installation, switch to original FSR, re-enable HelixSR, and recover an interrupted managed change. It blocks changes while the game runs and prevents legacy V762 controls from replacing this newer installation.

**This is a limited preview, not general Adreno or Android support.** Only the exact PRAGMATA/provider pair is qualified by its hashes. Other builds and game updates are refused until reviewed. HelixSR 3.x's FSR drop-in is HLX FSR 4, a different route; it is not supported by these 2.0 controls.

## Install and use

1. Use [HelixSR's official 2.0 setup](https://github.com/lonewolf0622/HelixSR/releases/tag/v2.0.0) on the target device to build its provider. Keep that folder. Do not upload or transfer the generated model DLLs.
2. Install the plugin ZIP through Decky Loader's ZIP installation option. Open **HelixSR Adreno**.
3. With PRAGMATA closed, choose **Manage this installation** if the recognized 2.0 build is already installed. This records ownership without replacing its current DLL or INI.
4. Choose the local official **fsr3-drop-in** folder for installation or re-enabling. Its provider hash must match the qualified build. The plugin supplies an INI template when the official drop-in folder has none; existing game INI settings are preserved.
5. Review a setting or provider change, confirm it, then restart the game. Choose **AMD FSR** in PRAGMATA.

The ZIP contains the plugin and its source-backed capability probe. It contains **no HelixSR runtime DLL, model weights, generated shaders or proprietary payloads**. The official setup remains unmodified. [Upstream terms](https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE) apply to its software and generated files.

## Scope and behavior

- Source and stock files are identified by full SHA-256 hashes. Unknown providers, legacy network mixtures, unsafe links and changed files block writes.
- Replacements use verified, flushed temporary files and atomic replacement. Transactions keep exact snapshots until a change is verified; failures roll back or expose recovery when the recorded state is intact.
- A crash before the transaction journal is prepared requires manual review. Conflicting recovery files are never overwritten automatically.
- Game quality, resolution, cap, driver, clocks, saves, Steam launch options and independent LSFG controls are preserved. Removing management restores original FSR and retains the editable INI and original provider.
- Startup does not launch Wine or run a GPU probe. The new view reads Steam metadata and caches unchanged file hashes; it does not repeatedly scan every game's files.

Historical 720p/967 MHz measurements reported 31.2â€“31.7 FPS for 2.0 INT8 Performance and 34.8â€“35.7 FPS for stock FSR Performance. These are not measurements of this plugin or the current WinNative configuration. Wave64 is exposed for testing, not advertised as a proven trail fix. See [validation and limitations](RELEASE_STATUS.md).

Build: `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test:armada`, `pnpm build`, then `python scripts/package_armada.py`. Run the Python tests on Linux; some legacy launcher fixtures assume Linux paths. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).

## Historical V762 preview

The sections below describe the older 0.3.x route, available under **Show legacy controls**. They do not describe 2.0 setup.

Free, unofficial experimental Armada Linux adaptation by Blackheart909. HelixSR is by [lonewolf0622](https://github.com/lonewolf0622/HelixSR).

[Download the plugin](https://github.com/dawoodtogoo2020-code/HelixSR-Decky-Armada/releases/tag/v0.3.1-armada-preview) Ã‚· [Installation and required assets](ARMADA_INSTALL.md) Ã‚· [Known issues and test evidence](RELEASE_STATUS.md) Ã‚· [V762 source tools](https://github.com/dawoodtogoo2020-code/HelixSR-Snapdragon-V762)

**Read before downloading:** this plugin requires your own exact private V762 assets. It does not download or generate the model. The public source tools still need matching runtime dumps; a complete ordinary-user extraction workflow is missing. Installing this ZIP alone will not produce a working model.

Version 0.3.1 manages HelixSR 1.8.0 Model E with the V762 Snapdragon adaptation. Model E is sourced locally from DLSS 310.7.0; this is not a DLSS 3.7 release. The target is the tested Odin 3 / Adreno 830 Armada Linux environment. Other devices and Android launchers need their own validation.

The interface follows the Steam Deck plugin's status and setup flow. Games lists scanned DX12 entries with a supported route; a title or DLL filename is insufficient. Managed DX12 games remain visible during safety review, with unsafe actions disabled. Settings holds source setup. Advanced troubleshooting holds records, recovery, removal and diagnostics. The plugin checks fresh running status, verifies Steam launch settings, preserves unrelated options and existing configuration, and pauses file changes while a game is running.

**Witcher 3 still has flashing black geometry and occasional full-frame flashes.** Its matched original FSR test was clean. PRAGMATA has historical physical Helix and LSFG 2x confirmation. Version 0.3.1 installed with all 47 files matching and settings preserved; that does not establish fresh gameplay acceptance, performance gains or broad compatibility.

The ZIP includes plugin code, licence notices and our original source-backed capability probe. It includes no Helix provider DLL, NVIDIA weights, generated network pack, compiled override or private dump. Upstream downloads and model switching are disabled for this pinned adaptation. Lossless Scaling VK2 remains a separate plugin. GameHub, DeckDroid, GameNative and Thor are unverified.

Build from the matching source archive or tag: `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test:armada`, `pnpm build`, then `python scripts/package_armada.py`. Complete source and third-party notices are included for rebuilding and library modifications.

Based on HelixSR Decky v0.1.18, incorporating interface and configuration-preservation decisions from commit a6b42742d20e95137cb6b6f6356308b23db3eb65. The [author permitted this free unofficial adaptation](https://github.com/lonewolf0622/HelixSR/issues/3#issuecomment-6128425735). Applicable third-party terms remain separate. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
