# Release review, 13 October 2026

HelixSR Decky Armada 0.2.1 is installed on the Odin. Its 47 packaged files matched the installer, settings survived, and PRAGMATA/Witcher closed-game disable and enable cycles passed provider hashes and Steam readback. PRAGMATA's independently installed combined LSFG launcher was retained. Version 0.3.0 is the interface and DX12-filtering candidate; installation and physical controller checks are tracked separately.

The 0.3.0 interface uses a detected-DX12 list, actionable status, one enable toggle, conditional executable/renderer setup, Settings and Advanced troubleshooting. Managed records excluded from suggestions remain accessible for restoration. Launch operations use an in-flight lock, fresh running status, exact readback and pending receipts. Configuration preservation follows the latest Steam Deck fixes.

## Gameplay evidence

PRAGMATA has historical physical gameplay and combined LSFG 2x confirmation. Two earlier automatic cold starts activated 2x after 20.47 and 18.94 seconds. These are session observations, not measured FPS gains or proof for the new plugin build.

Witcher 3 DX12 uses its direct FSR provider route. Helix V762 flashed black textures with AO off, FSR Quality, a 30 FPS cap and LSFG off. The matched original FSR run was physically clean. A reboot retest was interrupted by an OS update. Witcher remains unaccepted until fresh same-scene visual testing succeeds. Its saved LSFG profile starts Off; live Off-to-2x behavior still needs confirmation. Earlier thermal cutoffs occurred at 1100 MHz; the intended showcase setting is 967 MHz with automatic fans.

## Remaining Odin checks

1. Load 0.3.0, check controller focus, DX12-only suggestions, existing records, source preservation and disabled actions while running.
2. With games closed, verify toggles and interrupted launch repair, including exact readback and the independent PRAGMATA helper.
3. Physically accept Witcher's image with Helix alone before testing LSFG Off-to-2x. Record sustained behavior, temperatures and pacing at the intended underclock.
4. Cold-launch PRAGMATA after the new toggle cycle, including a reboot launch, and confirm image, helper activation and live LSFG controls.
5. Check full removal/restoration without disturbing independent LSFG, saves or shader caches.

Stellar Blade and Android GameHub, DeckDroid and GameNative remain unverified. This plugin targets Armada Linux.

## Publication gates

Both releases remain private and unpublished. The separate source-only V762 kit reproduces four override hashes from held runtime dumps, but a clean ordinary-user workflow from official assets to matching dumps is still missing. Physical acceptance, final package review and publication approval also remain outstanding. The author's permission for a free unofficial adaptation does not grant redistribution rights to third-party network assets.
