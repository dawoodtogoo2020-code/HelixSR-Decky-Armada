# Capability helper

`wave_probe.cpp` is original MIT-licensed application code. It queries a Qualcomm D3D12 adapter's wave limits and native 16-bit capability and writes JSON; it contains no game shader, provider, network asset or GPU workload.

Build an x64 Windows PE with Clang and MinGW-w64 headers/libraries, matching the installed Wine/FEX route. A typical cross-build is `clang++ --target=x86_64-w64-windows-gnu -std=c++17 -O0 -static wave_probe.cpp -o wave_probe.exe -ld3d12 -ldxgi -lole32 -luuid`. Supply your toolchain's sysroot/library directories as required. The shipped binary was built with Clang 23.1.3; exact compiler or runtime versions can change its hash. An intentional rebuild needs an updated `PROBE_SHA` in `armada_host.py` and a new verified device capability test.

The MinGW-w64 runtime notices are included in `licenses/COPYING.MinGW-w64-runtime.txt`. The C++ source is included with the plugin for rebuilding. On Armada, Decky's x86 FEX process invokes native helpers through `/proc/self/root/usr/bin` to avoid guest filesystem mapping, then uses the ARM64 Proton runtime in a separate prefix.
