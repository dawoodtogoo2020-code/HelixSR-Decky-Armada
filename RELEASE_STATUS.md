# Release review, 12 October 2026

Private preview installed on the AYN Odin 3 running Armada 20261012.f9e8e2a. The Decky plugin loads, verifies native ARM64 through FEX and the Adreno 830 D3D12 wave64/vkd3d capability, and validates the exact private V762 source.

The real PRAGMATA adoption, disable and enable cycle passed. Disable restored its independently verified genuine AMD FSR DLL; enable restored the provider, network pack, weights and INI to the pinned hashes. Steam launch settings were saved and read back in both directions. The game was closed for all file changes.

The initial isolated smoke test used the installed per-game override path and 967 MHz GPU cap. A fresh Model E network-running log and the game's actual environment were captured. The title and main menu rendered correctly after F confirmation. The following Continue capture was black. Later, the user reported a visible game/menu on the physical Odin while fresh remote captures were black, so those captures do not establish a HelixSR rendering failure.

In the coordinated follow-up, the user explicitly confirmed that gameplay works and they can move around with HelixSR running and frame generation temporarily off. This verifies physical gameplay for that session. The 2× LSFG pipeline has subsequently initialized alongside HelixSR, but physical confirmation of that combined state and repeat cold-launch reliability are still pending. Do not claim a performance improvement or broad compatibility. Earlier V762 benchmarks are historical and do not validate the combined configuration.

With LSFG 2 enabled, some cold launches exited during LSFG initialization. The coordinating chat reports that disabling the Gamescope WSI layer allowed one combined launch but did not make the next cold launch reliable. This is an intermittent startup problem; the sequence does not establish a shader fault. V762 files remain unchanged, and the coordinating chat owns device tests and launch-setting changes through the plugin's receipts.

The Witcher 3 and OptiScaler routes have offline installation guards but no device gameplay proof. Stellar Blade and Android GameHub, DeckDroid and GameNative are also unverified. This plugin targets Armada Linux.

Public stable release is held. The separate source-only V762 transform kit reproduces the four pinned overrides from private matching runtime dumps, but a clean, complete public workflow from an ordinary user's official provider to those dumps remains missing. The plugin package contains no provider, weights, network pack or compiled shader overrides.
