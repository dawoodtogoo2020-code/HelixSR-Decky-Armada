# Release review, 13 October 2026

## 0.4.0-rc.1 automatic setup candidate

This candidate adds explicit terms review, pinned public downloads, isolated local Model E conversion, fresh shader capture, exact V762 transforms, progress, cancellation, installed dependency reuse and source activation rollback. The public installer still contains no provider, model pack, weight file or compiled override. The existing 0.3.1 release is unchanged.

Offline download/archive, consent, lifecycle, rollback and RPC tests pass. The original capture helper compiled and passed host numeric fixtures and seven negative CLI checks. Bootstrap and synthetic integration tests cover fresh prefixes, partial overrides, required final RGB checks and blocking failures. Typechecking and the existing frontend safety tests pass. These checks do not execute ARM64 conversion or establish GPU output correctness. Clean Odin setup from public inputs, exact fresh capture hashes, controller focus and full cancel/retry remain required before publishing this as a working automatic setup release. The non-root backend requirement must also be checked against the installed Decky service.

The parent's private HDR diagnostic observed black RGB output despite successful dispatch and fence checks. A separate private reducer candidate improved synthetic output, but remains outside this release and is not a verified Witcher fix. Successful API calls, finite pixels and matching prepared files must not be presented as functional image validation. Known Witcher flashing remains unresolved. No private diagnostic data accompanies this candidate.

HelixSR Decky Armada 0.2.1 passed the original Odin installation and closed-game toggle checks: 47 package files matched, settings survived, and PRAGMATA/Witcher provider hashes and Steam launch readback passed. The independently installed PRAGMATA LSFG helper was retained. Version 0.3.0 subsequently installed and loaded. Version 0.3.1 keeps managed DX12 games visible during safety review. The new interface and gameplay acceptance remain separate checks.

The 0.3.0 interface uses a detected-DX12 list, actionable status, one enable toggle, conditional executable/renderer setup, Settings and Advanced troubleshooting. Managed records excluded from suggestions remain accessible for restoration. Launch operations use an in-flight lock, fresh running status, exact readback and pending receipts. Configuration preservation follows the latest Steam Deck fixes.

## Gameplay evidence

PRAGMATA has historical physical gameplay and combined LSFG 2x confirmation. Two earlier automatic cold starts activated 2x after 20.47 and 18.94 seconds. These are session observations, not measured FPS gains or proof for the new plugin build.

Witcher 3 DX12 uses its direct FSR provider route. Helix V762 flashed black textures with AO off, FSR Quality, a 30 FPS cap and LSFG off. The matched original FSR run was physically clean. A reboot retest was interrupted by an OS update. Witcher remains unaccepted until fresh same-scene visual testing succeeds. Its saved LSFG profile starts Off; live Off-to-2x behavior still needs confirmation. Earlier thermal cutoffs occurred at 1100 MHz; the intended showcase setting is 967 MHz with automatic fans.

## Remaining Odin checks

1. Load the current candidate, check controller focus, DX12-only suggestions, existing records, source preservation and disabled actions while running.
2. With games closed, verify toggles and interrupted launch repair, including exact readback and the independent PRAGMATA helper.
3. Physically accept Witcher's image with Helix alone before testing LSFG Off-to-2x. Record sustained behavior, temperatures and pacing at the intended underclock.
4. Cold-launch PRAGMATA after the new toggle cycle, including a reboot launch, and confirm image, helper activation and live LSFG controls.
5. Check full removal/restoration without disturbing independent LSFG, saves or shader caches.

Stellar Blade and Android GameHub, DeckDroid and GameNative remain unverified. This plugin targets Armada Linux.

## Public preview limits

The free public experimental releases contain plugin code and generic source tools only. The separate source-only V762 kit reproduces four override hashes from held runtime dumps, but a clean ordinary-user workflow from official assets to matching dumps is still missing. The current public packages passed manifest and full-history review; complete gameplay acceptance and the ordinary-user extraction workflow remain outstanding. The author's permission for a free unofficial adaptation does not grant redistribution rights to third-party network assets.

The public 0.3.1 installer preserves the exact runtime code bytes from the installed candidate (source baseline 2ac296be4047c21401ed62719339ab4d5e7ceab8). Only release documentation and provenance metadata were refreshed for publication. The installed candidate SHA is 6f2ee74d290fdc79234607865e59aff0749099c907e0c04b1e403551f2cfff9a; the public archive has a separate recorded digest. Source and checksums accompany the release.
