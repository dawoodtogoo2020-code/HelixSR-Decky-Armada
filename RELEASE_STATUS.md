# Release review, 12 October 2026

Private preview installed on the AYN Odin 3 running Armada 20261012.f9e8e2a. The Decky plugin loads, verifies native ARM64 through FEX and the Adreno 830 D3D12 wave64/vkd3d capability, and validates the exact private V762 source.

The real PRAGMATA adoption, disable and enable cycle passed. Disable restored its independently verified genuine AMD FSR DLL; enable restored the provider, network pack, weights and INI to the pinned hashes. Steam launch settings were saved and read back in both directions. The game was closed for all file changes.

The initial isolated smoke test used the installed per-game override path and 967 MHz GPU cap. A fresh Model E network-running log and the game's actual environment were captured. The title and main menu rendered correctly after F confirmation. The following Continue capture was black. Later, the user reported a visible game/menu on the physical Odin while fresh remote captures were black, so those captures do not establish a HelixSR rendering failure.

In the coordinated follow-up, the user confirmed gameplay and movement with HelixSR running and frame generation temporarily off, then confirmed correct, smoother gameplay with both HelixSR and LSFG 2× active after enabling frame generation live. These are physical confirmations for those sessions, not measured FPS gains or broad compatibility evidence. Earlier V762 benchmarks are historical and do not validate the combined configuration.

With LSFG 2 enabled, some cold launches exited during LSFG initialization. The coordinating chat reports that disabling the Gamescope WSI layer allowed one combined launch but did not make the next cold launch reliable. This is an intermittent startup problem; the sequence does not establish a shader fault. V762 files remain unchanged, and the coordinating chat owns device tests and launch-setting changes through the plugin's receipts.

A separate PRAGMATA-only launch helper now starts with a private 1× LSFG configuration, waits for the tagged game and fresh Helix rendering evidence, then applies and continues mirroring the Decky-selected settings. Two automatic cold starts activated 2× in 20.47 and 18.94 seconds and stayed running. A live off/2× control cycle reached the running session, and the first temporary configuration was removed on exit. Physical Continue/gameplay confirmation after the latest automatic cold start is still pending. The helper and native LSFG engine are separate from this plugin's installation ZIP; the V762 provider and shader files are unchanged.

The full HelixSR disable/re-enable cycle with this new helper has not been verified. Version 0.2.0 restores its original launch settings on disable and rebuilds only the V762 launch environment on enable; automatic reattachment of the separate warm-up helper is not implemented. That integration needs review before treating the combined setup as a complete plugin-managed release. Leave the user's current game untouched while the coordinating chat owns testing.

The Witcher 3 and OptiScaler routes have offline installation guards but no device gameplay proof. Stellar Blade and Android GameHub, DeckDroid and GameNative are also unverified. This plugin targets Armada Linux.

Public stable release is held. The separate source-only V762 transform kit reproduces the four pinned overrides from private matching runtime dumps, but a clean, complete public workflow from an ordinary user's official provider to those dumps remains missing. The plugin package contains no provider, weights, network pack or compiled shader overrides.
