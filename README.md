# HelixSR Decky Armada

Unofficial Blackheart909 adaptation of HelixSR Decky for Snapdragon Armada Linux. HelixSR is by lonewolf0622.

Version 0.3.0 brings the Steam Deck status-first interface to the pinned HelixSR 1.8.0 Model E V762 backend. Games suggests only Steam entries with scanned DX12 evidence and a supported installation route. A title or DLL filename is insufficient. Existing records remain available in Advanced troubleshooting for review, recovery and restoration.

The main view shows the next step and one install or enable control. It checks fresh game status, pauses changes while a game is running, preserves unrelated Steam options and verifies every launch-setting write. Source setup lives in Settings; recovery, removal, diagnostics and ownership details live in Advanced troubleshooting. Existing OptiScaler and fakenvapi configuration is preserved using the current Steam Deck ownership rules.

This is a private release candidate. Version 0.2.1 was installed and passed closed-game toggle checks on the Odin. PRAGMATA has historical physical gameplay confirmation. Witcher 3 has unresolved flashing with Helix; its matched original FSR test was clean. Installation is not proof of compatibility. See [release status](RELEASE_STATUS.md) and [installation instructions](ARMADA_INSTALL.md).

The ZIP includes plugin code and our source-backed capability probe. It contains no Helix provider, network weights, network pack or shader overrides. Supply your own exact local V762 assets. Ordinary upstream downloads and model switching are disabled. Lossless Scaling VK2 remains a separate plugin. Android GameHub, DeckDroid and GameNative need separate integration.

Build: `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test:armada`, `pnpm build`, then `python scripts/package_armada.py`.

Based on HelixSR Decky v0.1.18, with interface and configuration-preservation decisions from commit a6b42742d20e95137cb6b6f6356308b23db3eb65. Original license and third-party notices are retained. The complete public workflow for generating matching V762 runtime input dumps is still pending.
