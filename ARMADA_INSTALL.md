# HelixSR Decky Armada 0.3.0 preview

This is the unofficial Blackheart909 Armada adaptation of HelixSR Decky. HelixSR itself is by lonewolf0622. V762 is a local Snapdragon shader revision of HelixSR 1.8.0 Model E, not an official HelixSR version number or NVIDIA DLSS release.

1. Install Decky Loader on an Armada ARM64 system and install Steam's Proton Experimental (ARM64).
2. Install the plugin ZIP through Decky's developer installation option. It uses the separate `HelixSR-Decky-Armada` plugin directory.
3. Supply your own private V762 payload folder and select it in the plugin. The plugin verifies the exact provider, network assets, configuration and four shader hashes. Ordinary HelixSR downloads and automatic upstream updates cannot replace this revision.
4. Games lists only Steam games with scanned DX12 evidence and an eligible route. Close the selected game. Choose its executable and confirm DX12 when requested. Review and apply Install HelixSR.
5. Select the game's FSR 3.1 upscaler, or use the OptiScaler route for eligible DX12 games. Test a save locally before considering the title compatible.

The private source must contain `amd_fidelityfx_dx12.dll`, `helixsr_kernels.pak`, `helixsr_weights.bin`, `helixsr.ini`, and the four `shader-override/*.spv` files listed in `py_modules/armada_manager.py`. OptiScaler routes also require the complete OptiScaler and AMD FSR payload listed in `manager.PACKAGE_FILES`. This plugin does not generate these private assets or download NVIDIA weights. The separate V762 transform kit currently requires matching runtime dumps; a complete public extraction workflow is still pending.

The plugin creates a companion folder beside each game: `<game> Mod Files/HelixSR-Decky-Armada`. It holds verified packages, the original game DLLs required for disabling, and installation and launch-setting records. Preserve it while the game is managed. The plugin changes only its recorded game files and owns only the Steam launch options it adds. Custom shell launch scripts and conflicting override assignments need manual review and are preserved.

The HelixSR enabled toggle switches between V762 and the recorded original. Settings contains source setup. Advanced troubleshooting contains existing records, removal, launch repair and transaction recovery. Repair resumes only exact receipt-matching Steam settings and verifies fresh readback. Different current options are preserved for review. Close the game before all changes.

Version 0.2.1 also preserves the intent of PRAGMATA's separately installed combined HelixSR/LSFG launch helper across a stock/V762 toggle. It captures only the recognized, finalized plugin-owned helper configuration before disabling. Re-enable verifies the helper's pinned hash and reapplies it to the current Steam options, retaining edits made while V762 was disabled. Conflicting options or a changed/missing helper block re-enable for review. Disable remains available when the helper is missing or changed. Remove restores the original Steam options and clears the helper-preservation record after restoring game files; it does not delete the independent helper or LSFG installation.

The helper is not bundled or automatically installed by this preview. This integration is scoped to Steam PRAGMATA and the tested `Combined-Helix-LSFG-20261012/pragmata-combined-launch.py` helper. Version 0.2.1 was installed and its closed-game toggles passed. The new 0.3.0 interface needs separate device verification.

Existing installations can be adopted only with the exact V762 files and an independently verified genuine original FSR DLL bound to that same game folder. The preview installed on the maintainer's Odin seeds PRAGMATA's known original; selecting a different source does not reuse that binding for another game.

The read-only capability probe requires an actual Qualcomm adapter, 64..64 D3D12 wave limits and vkd3d-proton. It uses a separate prefix and does not change game settings or clocks. Matching hardware is necessary but does not prove game compatibility. PRAGMATA has historical physical confirmation. Witcher 3 has unresolved flashing with Helix despite a clean matched original FSR run. Stellar Blade and Android GameHub, DeckDroid and GameNative remain unverified. The Decky plugin targets Armada Linux; Android launchers need a separate integration.

This preview contains no NVIDIA network weights, generated kernels, provider DLLs or compiled game shader overrides. Follow upstream terms when building private assets. HelixSR's author has permitted the unofficial adaptation. That permission does not grant redistribution rights to third-party network data.
