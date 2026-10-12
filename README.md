# HelixSR Decky Armada

Unofficial Blackheart909 adaptation of HelixSR Decky for Snapdragon Armada Linux. HelixSR is by lonewolf0622.

This 0.2.1 preview manages private, hash-pinned HelixSR 1.8.0 Model E V762 assets on eligible DX12 games. The plugin includes no provider, weights, network pack or compiled shader overrides. It verifies ARM64 Proton, Qualcomm wave64 capability, game state and recorded file ownership before installation.

The 0.2.1 fix preserves PRAGMATA's separately installed combined HelixSR/LSFG startup helper across Disable and Enable, verifies the pinned helper before reattaching it, and retains current user launch options. It is prepared and offline-tested; the installed Odin build is still 0.2.0. See [release status and remaining device tests](RELEASE_STATUS.md).

Read [the Armada installation guide](ARMADA_INSTALL.md) for setup, source requirements, safe disabling and limitations. PRAGMATA is the only personally tested title. The Witcher 3 and other games are unverified. Android launchers require separate integration.

Build with `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm build`, then `python scripts/package_armada.py`. The installer ZIP contains the Decky frontend, Python backend and our own source-backed capability helper. It does not prepare private network data. The complete public workflow for extracting V762 input dumps is still pending.

Forked from dawoodtogoo2020-code/HelixSR-Decky v0.1.18 (286726be63af6f3dea712db8ba2e2f4f71ee4967). The original plugin license and third-party notices are retained. Ordinary upstream package updates are disabled so they cannot silently replace V762.
