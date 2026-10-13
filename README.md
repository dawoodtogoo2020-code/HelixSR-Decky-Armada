# HelixSR Decky Armada

Free, unofficial experimental Armada Linux adaptation by Blackheart909. HelixSR is by [lonewolf0622](https://github.com/lonewolf0622/HelixSR).

[Download the plugin](https://github.com/dawoodtogoo2020-code/HelixSR-Decky-Armada/releases/tag/v0.3.1-armada-preview) Â· [Installation and required assets](ARMADA_INSTALL.md) Â· [Known issues and test evidence](RELEASE_STATUS.md) Â· [V762 source tools](https://github.com/dawoodtogoo2020-code/HelixSR-Snapdragon-V762)

**Current public release:** 0.3.1 requires your own exact private V762 assets. Its separate source tools need matching runtime dumps. Installing the published 0.3.1 ZIP alone will not produce a model.

**0.4.0-rc.1 candidate:** adds **Set up model**, which downloads pinned official inputs, builds Model E locally and generates the four matching V762 overrides in an isolated probe. No supplied private folder is needed by this workflow. Progress and cancellation are shown in the plugin; existing local import is under Advanced troubleshooting. This candidate is awaiting clean Odin generation and interface testing and has not replaced the public release. Asset preparation does not establish correct images or gameplay.

Version 0.3.1 manages HelixSR 1.8.0 Model E with the V762 Snapdragon adaptation. Model E is sourced locally from DLSS 310.7.0; this is not a DLSS 3.7 release. The target is the tested Odin 3 / Adreno 830 Armada Linux environment. Other devices and Android launchers need their own validation.

The interface follows the Steam Deck plugin's status and setup flow. Games lists scanned DX12 entries with a supported route; a title or DLL filename is insufficient. Managed DX12 games remain visible during safety review, with unsafe actions disabled. Settings holds source setup. Advanced troubleshooting holds records, recovery, removal and diagnostics. The plugin checks fresh running status, verifies Steam launch settings, preserves unrelated options and existing configuration, and pauses file changes while a game is running.

**Witcher 3 still has flashing black geometry and occasional full-frame flashes.** Its matched original FSR test was clean. PRAGMATA has historical physical Helix and LSFG 2x confirmation. Version 0.3.1 installed with all 47 files matching and settings preserved; that does not establish fresh gameplay acceptance, performance gains or broad compatibility.

The candidate ZIP includes plugin code, licence notices and original source-backed capability and capture helpers. It includes no Helix provider DLL, NVIDIA weights, generated network pack, compiled override or private dump. Downloads come from pinned official sources only after explicit acknowledgement of linked terms. Generated material stays on the user's device. Other models are unavailable. Lossless Scaling VK2 remains a separate plugin. GameHub, DeckDroid, GameNative and Thor are unverified.

Build from the matching source archive or tag: `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test:armada`, `pnpm build`, then `python scripts/package_armada.py`. Complete source and third-party notices are included for rebuilding and library modifications.

Based on HelixSR Decky v0.1.18, incorporating interface and configuration-preservation decisions from commit a6b42742d20e95137cb6b6f6356308b23db3eb65. The [author permitted this free unofficial adaptation](https://github.com/lonewolf0622/HelixSR/issues/3#issuecomment-6128425735). Applicable third-party terms remain separate. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
