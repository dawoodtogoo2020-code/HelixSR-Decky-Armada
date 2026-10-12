# Release review, 13 October 2026

HelixSR Decky Armada 0.2.0 is installed on the AYN Odin 3 running Armada 20261012.f9e8e2a. Version 0.2.1 is a prepared local candidate, not installed or device-tested. Both releases remain private and unpublished.

The installed plugin loaded, verified native ARM64 through FEX and actual Adreno 830 D3D12 wave64/vkd3d capability, and validated the exact private HelixSR 1.8.0 Model E V762 source. PRAGMATA adoption, disable and enable passed: disable restored its independently verified genuine AMD FSR DLL, and enable restored the provider, network pack, weights and INI to pinned hashes. Steam launch options were saved and read back in both directions with the game closed.

The user physically confirmed gameplay and movement with HelixSR running, correct and smoother gameplay with HelixSR plus LSFG 2x, and smooth gameplay after the latest automatic cold launch. The separate PRAGMATA helper passed two automatic cold starts, activating 2x after 20.47 and 18.94 seconds; live Decky changes reached the running session and the first temporary configuration was cleaned on exit. These confirmations establish the tested sessions, not measured FPS gains or broad compatibility. Black remote captures contradicted the physical display and cannot establish a rendering failure. The combined evidence is recorded by the coordinating chat in Odin-combined-launch-installation.json.

Version 0.2.1 fixes the gap where disabling V762 restored the original Steam options and a later enable lost the independent startup helper. A separate receipt stores only the recognized PRAGMATA helper path, pinned hash and WSI intent. It never stores or replays an old full launch string. Re-enable merges into current Steam options, checks the helper during preview and again immediately before game-file writes, and blocks conflicting settings. Missing or changed helpers do not prevent disabling. Original launch receipt semantics remain intact. Remove restores the earliest owned launch settings and clears the helper attachment record; independently installed helper files, the native LSFG engine and global configuration are untouched. Older managed installations without a launch receipt preserve their unowned options on disable and need manual launch-setting review.

## Required Odin checks for the 0.2.1 preview

1. With PRAGMATA closed, install 0.2.1 over the separate Armada plugin. Confirm Decky loads it, finds the existing source and managed game, and retains settings.
2. Disable and re-enable V762 through Decky. Verify genuine FSR and pinned V762 hashes, exact Steam readback, retained helper/WSI settings, and preservation of an unrelated option added while disabled. Repeat once and verify interrupted launch-setting repair remains usable.
3. Cold-launch PRAGMATA after that toggle cycle, Continue into gameplay, and physically confirm the image, movement and automatic LSFG 2x activation. Repeat at least three launches, including one after a device reboot. Verify live off/2x controls and session cleanup.
4. Run a sustained gameplay session at the intended underclock. Record crashes, frame pacing, temperatures and fan behavior. No performance-gain claim is justified without a matched comparison.
5. Test the stock/removal path with the game closed, then restore the desired managed configuration. Confirm the independent LSFG setup, saves and shader caches remain intact.

The Witcher 3 DX12 needs a separate installation, launch and gameplay test before adding it to supported titles. Test its OptiScaler route, toggles and restoration, and combine LSFG only after Helix alone works. Stellar Blade and Android GameHub, DeckDroid and GameNative remain unverified. This plugin targets Armada Linux.

## V762 source preview and publication gates

The separate source-only kit reproduced all four pinned override hashes from held private runtime dumps and passed independent SPIR-V validation. It includes generic transformation tools, manifests, grammar and licenses. A clean redistributable probe and tested workflow from an ordinary user's official HelixSR assets to the matching runtime dumps are still missing. This is an additional release blocker that gameplay testing alone cannot resolve.

Public release remains held for the candidate's Odin checks, the complete user-buildable extraction workflow, final package review and publication approval. The packages contain no provider DLL, NVIDIA network weights, generated network pack or compiled game shader overrides. The author permitted the free unofficial adaptation; this does not grant redistribution rights to third-party network data.
