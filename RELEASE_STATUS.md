# Adreno 2.0 preview review, 28 October 2026

Version **0.5.0-adreno-preview** is qualified for the pinned, locally built HelixSR 2.0 FSR provider in PRAGMATA on the tested Odin 3 running Armada Linux. It is a free unofficial plugin. Other game/provider hashes, Android launchers and HelixSR 3.x are outside this release's scope.

## Implemented fixes

- A separate 2.0 route replaces obsolete V762 assumptions for this installation. It adopts existing files, registers a local official source, toggles original FSR/HelixSR, edits four supported INI settings and exposes checked transaction recovery.
- Full hashes, fresh preflight checks and running-game checks protect every change. Verified temporary files are flushed and atomically replaced; interrupted transactions retain recovery data. Unknown, mixed, linked or changed files are refused.
- Startup performs no Wine/GPU probe. Steam discovery reads metadata, unchanged hashes are cached, and the new view refreshes manually. Legacy capability checking is an explicit user action.
- H2 RPCs run on the plugin's event-loop thread under one lock. Threaded candidates reproduced a five-second Decky/FEX stop timeout; the thread-free H2 candidate passed the measured reload checks. Long legacy jobs retain separate per-call workers. Synchronous H2 disk I/O can delay the event loop, and a stalled filesystem remains a limitation; cancellation is not a way to interrupt an active file change.
- Confirmation dialogs remain open when Decky unmounts its side panel. Legacy V762 file/launcher actions cannot replace a recognized 2.0 installation.
- Optional SQLite loading no longer prevents Steam discovery in an embedded Python without SQLite.

## Validation

TypeScript checking, bundle build and 48 frontend tests passed. Native Odin Python passed 23 H2/backend/lifecycle tests, 10 Armada backend tests, 7 addon tests, 18 launch-receipt tests and 9 installation-status tests. The existing 156 general backend tests passed under x86 Linux/WSL. Those general tests intentionally require x86; running them unchanged on native ARM produced host-eligibility failures, so that result is not presented as an ARM pass. Windows link/path limitations were checked on native Linux rather than weakening the guards.

The candidate was installed through Decky and all 48 packaged files were verified. Live RPC checks passed adoption without changing game files, source registration, a wave-size change and exact restore, stock/Helix toggle cycles, running-game refusal, and legacy-action refusal. The visible Decky interface rendered the detected provider and settings. Its original-FSR and HelixSR confirmation flows were exercised, with exact provider hashes checked after each switch. The INI and game configuration returned to their original bytes.

After read and mutation requests, two measured reloads of the final thread-free H2 candidate replaced its process in 1.353 and 1.354 seconds and answered library/status requests by 2.662 and 2.661 seconds. Decky logged its unload callback and a clean 0.1-second stop on both, without SIGKILL. These are two observed idle reloads, not a guarantee for a blocked disk or active legacy probe. This measures plugin lifecycle, not game FPS.

A staged native read harness measured startup 0.16 ms, Steam discovery 9.42 ms, first status 43.04 ms and cached status 4.89 ms. The final installed RPC cached-status sample was 26.6 ms. The native figures are not FEX-hosted Decky startup measurements.

## Gameplay performance

The user confirmed that the saved game had loaded before the new sample. The tested configuration was 960 x 540, Balanced, INT8 on, wave auto, the current WinNative driver, GPU 1100 MHz and LSFG temporarily set to 1x. A 30-second sample recorded 879 frames: mean frame time 33.88 ms (about 29.5 base FPS), median 30.32 ms and p99 190.72 ms. GPU busy averaged 73.4%; the measured GPU time was 24.86 ms per frame. Peak temperatures were CPU 87.6 C and GPU 72.6 C, with no configured thermal cutoff triggered.

This short sample contains substantial frame-time spikes. It is not a controlled before/after comparison, a sustained thermal test, or acceptance of motion quality. Remote capture was unreliable; user confirmation established gameplay loading, not image-quality approval. No renderer FPS uplift is claimed for this plugin release. The game was closed afterward and the exact original LSFG 2x configuration restored.

Historical 27 October measurements used 720p, system Mesa and 967 MHz: HelixSR 2.0 INT8 Performance measured 31.2-31.7 FPS versus stock FSR Performance at 34.8-35.7. The older V762 Balanced and newer 2.0 Performance results use different render presets and must not be presented as an equal-quality uplift. WinNative wave32 was observed, but its role in reported trails and a wave64 remedy remain unproven. Wave64 is available for deliberate comparisons, not enabled as an assumed fix.

## Distribution and remaining limits

The archive includes no HelixSR provider/model DLL, weights, generated kernels or shader overrides. Build the official 2.0 source locally on the target device and select its fsr3-drop-in folder. Official setup binaries and generated providers are not modified by this plugin. A matching local provider is required, so the ZIP alone is not a model installer. See the [official 2.0 release](https://github.com/lonewolf0622/HelixSR/releases/tag/v2.0.0) and [upstream terms](https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE).

A crash before the transaction journal is prepared requires manual review. Conflicting recovery files are preserved. Long legacy V762 operations, other games, controller navigation across every control, extended gameplay, wave64 visual quality, alternate drivers and reboot acceptance are not newly qualified by this release. The original FSR provider is retained as an installed switching dependency. Saves, shader caches, game settings, launch options, clocks and independent LSFG ownership are preserved.

## Historical release evidence


# Release review, 13 October 2026

HelixSR Decky Armada 0.2.1 passed the original Odin installation and closed-game toggle checks: 47 package files matched, settings survived, and PRAGMATA/Witcher provider hashes and Steam launch readback passed. The independently installed PRAGMATA LSFG helper was retained. Version 0.3.0 subsequently installed and loaded. Version 0.3.1 keeps managed DX12 games visible during safety review. The new interface and gameplay acceptance remain separate checks.

The 0.3.0 interface uses a detected-DX12 list, actionable status, one enable toggle, conditional executable/renderer setup, Settings and Advanced troubleshooting. Managed records excluded from suggestions remain accessible for restoration. Launch operations use an in-flight lock, fresh running status, exact readback and pending receipts. Configuration preservation follows the latest Steam Deck fixes.

## Gameplay evidence

PRAGMATA has historical physical gameplay and combined LSFG 2x confirmation. Two earlier automatic cold starts activated 2x after 20.47 and 18.94 seconds. These are session observations, not measured FPS gains or proof for the new plugin build.

Witcher 3 DX12 uses its direct FSR provider route. Helix V762 flashed black textures with AO off, FSR Quality, a 30 FPS cap and LSFG off. The matched original FSR run was physically clean. A reboot retest was interrupted by an OS update. Witcher remains unaccepted until fresh same-scene visual testing succeeds. Its saved LSFG profile starts Off; live Off-to-2x behavior still needs confirmation. Earlier thermal cutoffs occurred at 1100 MHz; the intended showcase setting is 967 MHz with automatic fans.

## Remaining Odin checks

1. Load 0.3.1, check controller focus, DX12-only suggestions, existing records, source preservation and disabled actions while running.
2. With games closed, verify toggles and interrupted launch repair, including exact readback and the independent PRAGMATA helper.
3. Physically accept Witcher's image with Helix alone before testing LSFG Off-to-2x. Record sustained behavior, temperatures and pacing at the intended underclock.
4. Cold-launch PRAGMATA after the new toggle cycle, including a reboot launch, and confirm image, helper activation and live LSFG controls.
5. Check full removal/restoration without disturbing independent LSFG, saves or shader caches.

Stellar Blade and Android GameHub, DeckDroid and GameNative remain unverified. This plugin targets Armada Linux.

## Public preview limits

The free public experimental releases contain plugin code and generic source tools only. The separate source-only V762 kit reproduces four override hashes from held runtime dumps, but a clean ordinary-user workflow from official assets to matching dumps is still missing. The current public packages passed manifest and full-history review; complete gameplay acceptance and the ordinary-user extraction workflow remain outstanding. The author's permission for a free unofficial adaptation does not grant redistribution rights to third-party network assets.

The public 0.3.1 installer preserves the exact runtime code bytes from the installed candidate (source baseline 2ac296be4047c21401ed62719339ab4d5e7ceab8). Only release documentation and provenance metadata were refreshed for publication. The installed candidate SHA is 6f2ee74d290fdc79234607865e59aff0749099c907e0c04b1e403551f2cfff9a; the public archive has a separate recorded digest. Source and checksums accompany the release.

## 0.3.2 read-handling hotfix, 14 October 2026

This preview adds bounded read-only frontend requests for an unavailable backend. It fixes indefinite UI waiting and retains manual retry and existing mutation/readback guards. Local checks: TypeScript compilation, bundle build and 46 frontend tests passed; 13 tests cover the new watchdog behavior. These checks do not prove active Odin game discovery, gameplay, shutdown performance or automatic model generation. Private lifecycle source work remains separate from this public hotfix.
