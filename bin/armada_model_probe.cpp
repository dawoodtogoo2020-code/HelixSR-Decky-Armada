// Copyright (c) 2026 Blackheart909
// SPDX-License-Identifier: MIT
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
//
// Original game-free FFX/D3D12 capture trigger. It never examines module bytes,
// extracts shaders or implements private instrumentation. Output readback emits
// bounded RGB numerical aggregates only, never pixels or image files.
// Runtime shader capture is independently configured by VKD3D_SHADER_DUMP_PATH.
// Arguments: absolute Windows bundle directory; absolute NEW NDJSON report file.
// Compile against unmodified FidelityFX SDK v1.1.4 headers, commit
// c6efa6bf7f2027b3ec94f28578bb5965eabb9e55 (retain their AMD MIT notices):
// x86_64-w64-mingw32-g++ armada_model_probe.cpp -o armada_model_probe.exe
//   -std=c++17 -O0 -static -municode -Wall -Wextra -Werror
//   -I<pinnedincludeRoot> -ld3d12 -ldxgi -ldxguid -lole32
// A successful report proves only these two bounded analytic dispatches.
// It does not establish gameplay, image quality, performance, or compatibility.

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0602
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#ifdef __clang__
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wswitch"
#endif
#include <ffx_upscale.h>
#include <dx12/ffx_api_dx12.h>
#ifdef __clang__
#pragma clang diagnostic pop
#endif
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <limits>
#include <iomanip>
#include <locale>
#include <sstream>
#include <string>
#include <utility>

static_assert(sizeof(void*) == 8, "64-bit Windows ABI required");
static_assert(sizeof(FfxApiResource) == 48, "FFX resource ABI changed");
static_assert(sizeof(ffxDispatchDescUpscale) == 432, "FFX dispatch ABI changed");
static_assert(offsetof(ffxDispatchDescUpscale, output) == 312, "FFX output ABI changed");
static_assert(offsetof(ffxDispatchDescUpscale, reset) == 408, "FFX reset ABI changed");
static_assert(static_cast<unsigned>(DXGI_FORMAT_R9G9B9E5_SHAREDEXP) == 67,
              "Unexpected output DXGI format");

namespace {
constexpr UINT RW = 752, RH = 424, DW = 1280, DH = 720;
constexpr DWORD WaitMs = 15000;
constexpr std::size_t ReportLimit = 16 * 1024;
constexpr UINT64 UploadLimit = 32 * 1024 * 1024;
std::atomic<unsigned> errors{0}, warnings{0};

void message(uint32_t type, const wchar_t*) noexcept {
    // Never log callback text: it may contain user paths or provider internals.
    if (type == FFX_API_MESSAGE_TYPE_ERROR) errors.fetch_add(1);
    else warnings.fetch_add(1);
}
struct Failure { const char* stage; std::int64_t code; };
void need(bool value, const char* stage) {
    if (!value) throw Failure{stage, -1};
}
void hr(HRESULT value, const char* stage) {
    if (FAILED(value)) throw Failure{stage, static_cast<std::int64_t>(value)};
}
void ffx(ffxReturnCode_t value, const char* stage) {
    if (value != FFX_API_RETURN_OK) throw Failure{stage, value};
}
template<class T> class Com {
    T* value = nullptr;
public:
    Com() = default;
    Com(const Com&) = delete;
    Com& operator=(const Com&) = delete;
    ~Com() { if (value) value->Release(); }
    T* get() const noexcept { return value; }
    void abandon() noexcept { value = nullptr; }
    T* operator->() const noexcept { return value; }
    T** put() noexcept {
        if (value) value->Release();
        value = nullptr;
        return &value;
    }
};
class Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
public:
    Handle() = default;
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    ~Handle() { if (valid()) CloseHandle(value); }
    bool valid() const noexcept { return value && value != INVALID_HANDLE_VALUE; }
    HANDLE get() const noexcept { return value; }
    void abandon() noexcept { value = INVALID_HANDLE_VALUE; }
    void set(HANDLE h) noexcept {
        if (valid()) CloseHandle(value);
        value = h;
    }
};
class Module {
public:
    HMODULE value = nullptr;
    Module() = default;
    Module(const Module&) = delete;
    Module& operator=(const Module&) = delete;
    ~Module() { if (value) FreeLibrary(value); }
    void abandon() noexcept { value = nullptr; }
    template<class T> T function(const char* name) const {
        FARPROC raw = GetProcAddress(value, name);
        need(raw != nullptr, "provider_export");
        static_assert(sizeof(T) == sizeof(raw), "Function pointer ABI mismatch");
        T result{};
        std::memcpy(&result, &raw, sizeof(result));
        return result;
    }
};
class DllSearch {
    DLL_DIRECTORY_COOKIE cookie = nullptr;
public:
    DllSearch() = default;
    DllSearch(const DllSearch&) = delete;
    DllSearch& operator=(const DllSearch&) = delete;
    ~DllSearch() { if (cookie) RemoveDllDirectory(cookie); }
    void abandon() noexcept { cookie = nullptr; }
    void restrictTo(const std::wstring& bundle) {
        // USER_DIRS contains only our added directory in this fresh helper process.
        // Application directory, current directory and PATH are excluded.
        need(SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32 |
                                      LOAD_LIBRARY_SEARCH_USER_DIRS) != 0, "dll_search_policy");
        cookie = AddDllDirectory(bundle.c_str());
        need(cookie != nullptr, "dll_bundle_search");
    }
};
std::wstring path(const wchar_t* input, bool directory) {
    need(input != nullptr, "path");
    const std::size_t n = wcsnlen(input, 241);
    need(n >= 3 && n <= 240, "path_length");
    std::wstring s(input, n);
    for (auto& c : s) if (c == L'/') c = L'\\';
    need(((s[0] >= L'A' && s[0] <= L'Z') ||
          (s[0] >= L'a' && s[0] <= L'z')) && s[1] == L':' && s[2] == L'\\',
         "drive_absolute_path");
    if (directory && s.size() > 3 && s.back() == L'\\') s.pop_back();
    need(directory || (s.size() > 3 && s.back() != L'\\'), "report_filename");
    std::size_t start = 3;
    for (std::size_t i = 3; i <= s.size(); ++i) {
        if (i < s.size()) {
            const wchar_t c = s[i];
            need(c >= 32 && c != L':' && c != L'"' && c != L'<' && c != L'>' &&
                 c != L'|' && c != L'?' && c != L'*', "path_character");
        }
        if (i == s.size() || s[i] == L'\\') {
            if (s.size() == 3 && directory) break;
            need(i > start, "path_component");
            const std::wstring part = s.substr(start, i - start);
            need(part != L"." && part != L".." && part.back() != L'.' &&
                 part.back() != L' ', "path_component");
            // Avoid DOS device aliases even when a suffix is supplied.
            std::wstring stem = part.substr(0, part.find(L'.'));
            for (auto& c : stem) if (c >= L'a' && c <= L'z') c -= L'a' - L'A';
            const bool numbered = stem.size() == 4 && stem[3] >= L'1' && stem[3] <= L'9' &&
                (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT");
            need(stem != L"CON" && stem != L"PRN" && stem != L"AUX" &&
                 stem != L"NUL" && !numbered, "device_path");
            start = i + 1;
        }
    }
    return s;
}
void regular(const std::wstring& s, bool directory) {
    const DWORD a = GetFileAttributesW(s.c_str());
    need(a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_REPARSE_POINT) &&
         ((a & FILE_ATTRIBUTE_DIRECTORY) != 0) == directory, "bundle_file_type");
}
class WorkingDirectory {
    std::wstring saved;
    bool changed = false;
public:
    explicit WorkingDirectory(const std::wstring& bundle) {
        const DWORD count = GetCurrentDirectoryW(0, nullptr);
        need(count > 0 && count <= 32768, "current_directory");
        saved.resize(count);
        const DWORD got = GetCurrentDirectoryW(count, &saved[0]);
        need(got > 0 && got < count, "current_directory");
        saved.resize(got);
        need(SetCurrentDirectoryW(bundle.c_str()) != 0, "bundle_directory");
        changed = true;
    }
    ~WorkingDirectory() { if (changed) SetCurrentDirectoryW(saved.c_str()); }
};
bool isHelix(const char* name) {
    if (!name) return false;
    // Bounded comparison only. Provider-owned names are neither stored nor logged.
    const std::size_t n = strnlen(name, 96);
    if (n == 96) return false;
    for (std::size_t i = 0; i + 7 <= n; ++i) {
        const char* word = "helixsr";
        bool match = true;
        for (std::size_t j = 0; j < 7; ++j) {
            char c = name[i + j];
            if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
            if (c != word[j]) match = false;
        }
        if (match) return true;
    }
    return false;
}

// RGB9E5 has unsigned 9-bit mantissas and a shared 5-bit exponent, no alpha.
std::array<double, 3> decodeRGB9E5(uint32_t packed) noexcept {
    const int exponent = static_cast<int>(packed >> 27) - 24;
    return {{std::ldexp(static_cast<double>(packed & 511u), exponent),
             std::ldexp(static_cast<double>((packed >> 9) & 511u), exponent),
             std::ldexp(static_cast<double>((packed >> 18) & 511u), exponent)}};
}
struct RGBStats {
    uint64_t count = 0;
    uint64_t structureCount = 0;
    double structureX = 0, structureY = 0, structureXX = 0, structureYY = 0, structureXY = 0;
    bool finite = true, nonblack = false;
    std::array<double, 3> low{{0, 0, 0}}, high{{0, 0, 0}}, mean{{0, 0, 0}}, m2{{0, 0, 0}};
    void add(const std::array<double, 3>& rgb) noexcept {
        for (double value : rgb) if (!std::isfinite(value)) { finite = false; return; }
        ++count;
        for (unsigned c = 0; c < 3; ++c) {
            if (count == 1) low[c] = high[c] = rgb[c];
            low[c] = (std::min)(low[c], rgb[c]);
            high[c] = (std::max)(high[c], rgb[c]);
            nonblack = nonblack || rgb[c] != 0;
            const double delta = rgb[c] - mean[c];
            mean[c] += delta / static_cast<double>(count);
            m2[c] += delta * (rgb[c] - mean[c]);
        }
    }
    bool constant() const noexcept {
        return count == 0 || (low[0] == high[0] && low[1] == high[1] && low[2] == high[2]);
    }
    bool valid() const noexcept { return count > 0 && finite && nonblack && !constant(); }
    void structure(const std::array<double, 3>& rgb, double expected) noexcept {
        for (double value : rgb) if (!std::isfinite(value)) return;
        const double luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
        ++structureCount;
        structureX += expected; structureY += luminance;
        structureXX += expected * expected; structureYY += luminance * luminance;
        structureXY += expected * luminance;
    }
    double correlation() const noexcept {
        const double n = static_cast<double>(structureCount);
        const double vx = n * structureXX - structureX * structureX;
        const double vy = n * structureYY - structureY * structureY;
        if (vx <= 0 || vy <= 0) return 0;
        const double result = (n * structureXY - structureX * structureY) / std::sqrt(vx * vy);
        return (std::max)(-1.0, (std::min)(1.0, result));
    }
};
RGBStats scanRGB9E5(const unsigned char* bytes, std::size_t offset, std::size_t pitch,
                    UINT width, UINT height) noexcept {
    RGBStats stats;
    for (UINT y = 0; y < height; ++y) {
        const auto* row = bytes + offset + static_cast<std::size_t>(y) * pitch;
        for (UINT x = 0; x < width; ++x) {
            uint32_t packed = 0;
            std::memcpy(&packed, row + static_cast<std::size_t>(x) * 4, 4);
            const auto rgb = decodeRGB9E5(packed);
            stats.add(rgb);
            // Diagnostic only: map output pixel centers to the known input checker.
            // No target-calibrated acceptance threshold is claimed. Omit edges where
            // jitter/reconstruction may mix cells (eight input pixels each side).
            if (width == DW && height == DH) {
                const UINT ix = static_cast<UINT>((static_cast<uint64_t>(x) * 2 + 1) * RW / (2 * DW));
                const UINT iy = static_cast<UINT>((static_cast<uint64_t>(y) * 2 + 1) * RH / (2 * DH));
                if (ix % 64 >= 8 && ix % 64 < 56 && iy % 64 >= 8 && iy % 64 < 56)
                    stats.structure(rgb, ((ix / 64 + iy / 64) & 1u) ? 1.0 : 0.0);
            }
        }
    }
    return stats;
}
bool numericSelfTest() noexcept {
    const uint32_t red = (16u << 27) | 256u; // exactly RGB (1,0,0)
    if (decodeRGB9E5(red) != std::array<double, 3>{{1, 0, 0}} ||
        decodeRGB9E5(1u)[0] != std::ldexp(1.0, -24) ||
        decodeRGB9E5(0xffffffffu)[2] != 65408.0) return false;
    // Nonzero offset and padded rows ensure padding is never treated as pixels.
    std::array<unsigned char, 48> bytes{};
    bytes.fill(255);
    auto fill = [&](uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
        const uint32_t values[] = {a, b, c, d};
        for (unsigned i = 0; i < 4; ++i)
            std::memcpy(bytes.data() + 8 + (i / 2) * 16 + (i % 2) * 4, &values[i], 4);
        return scanRGB9E5(bytes.data(), 8, 16, 2, 2);
    };
    const RGBStats black = fill(0, 0, 0, 0);
    const RGBStats constantRed = fill(red, red, red, red);
    const RGBStats structured = fill(0, red, 0, red);
    if (black.valid() || black.nonblack || !black.constant() || !black.finite ||
        constantRed.valid() || !constantRed.nonblack || !constantRed.constant() ||
        !structured.valid() || structured.count != 4 || structured.mean[0] != 0.5 ||
        structured.m2[0] / 4 != 0.25 || structured.high[0] != 1) return false;
    RGBStats alphaIgnored;
    const std::array<std::array<double, 4>, 2> rgba{{{{1, 0, 0, 0}}, {{1, 0, 0, 1}}}};
    for (const auto& pixel : rgba) alphaIgnored.add({{pixel[0], pixel[1], pixel[2]}});
    RGBStats nonfinite;
    nonfinite.add({{1, 0, 0}});
    nonfinite.add({{std::numeric_limits<double>::infinity(), 0, 0}});
    RGBStats ordered, reversed;
    for (unsigned i = 0; i < 4; ++i) {
        const double v = i & 1u;
        ordered.structure({{v, v, v}}, v);
        reversed.structure({{1 - v, 1 - v, 1 - v}}, v);
    }
    return !alphaIgnored.valid() && alphaIgnored.constant() && !nonfinite.finite && !nonfinite.valid() &&
        std::fabs(ordered.correlation() - 1) < 1e-12 && std::fabs(reversed.correlation() + 1) < 1e-12;
}

class Probe {
    DllSearch search;
    Module module; // Unload after contexts/resources and before removing the search directory.
    Com<IDXGIFactory4> factory;
    Com<IDXGIAdapter1> adapter;
    Com<ID3D12Device> device;
    Com<ID3D12CommandQueue> queue;
    Com<ID3D12CommandAllocator> allocator;
    Com<ID3D12GraphicsCommandList> list;
    Com<ID3D12Fence> fence;
    Com<ID3D12Resource> readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT readbackFootprint{};
    UINT64 readbackBytes = 0;
    Handle event;
    std::array<Com<ID3D12Resource>, 5> textures;
    std::array<Com<ID3D12Resource>, 4> uploads;
    PfnFfxCreateContext create = nullptr;
    PfnFfxDestroyContext destroy = nullptr;
    PfnFfxConfigure configure = nullptr;
    PfnFfxQuery query = nullptr;
    PfnFfxDispatch dispatch = nullptr;
    ffxContext context = nullptr;
    // The API requires create descriptors to remain live for the context lifetime.
    ffxCreateBackendDX12Desc backend{};
    ffxOverrideVersion overrideVersion{};
    ffxCreateContextDescUpscale contextDesc{};
    UINT64 fenceValue = 0;
    bool inFlight = false, cleaned = false;
    void healthy() { hr(device->GetDeviceRemovedReason(), "device_removed"); }
    void submit() {
        hr(list->Close(), "command_close");
        ID3D12CommandList* commands[] = {list.get()};
        queue->ExecuteCommandLists(1, commands);
        inFlight = true;
        ++fenceValue;
        hr(queue->Signal(fence.get(), fenceValue), "queue_signal");
        wait();
    }
    void wait() {
        healthy();
        const UINT64 completed = fence->GetCompletedValue();
        need(completed != std::numeric_limits<UINT64>::max(), "fence_device_removed");
        if (completed < fenceValue) {
            hr(fence->SetEventOnCompletion(fenceValue, event.get()), "fence_event");
            need(WaitForSingleObject(event.get(), WaitMs) == WAIT_OBJECT_0, "fence_wait");
            need(fence->GetCompletedValue() >= fenceValue, "fence_completion");
        }
        healthy();
        inFlight = false;
    }
    void begin() {
        hr(allocator->Reset(), "allocator_reset");
        hr(list->Reset(allocator.get(), nullptr), "command_reset");
    }
    void texture(unsigned slot, UINT w, UINT h, DXGI_FORMAT format, bool output) {
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = w; desc.Height = h;
        desc.DepthOrArraySize = 1; desc.MipLevels = 1;
        desc.Format = format; desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
        desc.Flags = output ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
        const D3D12_RESOURCE_STATES state = output ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS :
                                                                  D3D12_RESOURCE_STATE_COPY_DEST;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state,
             nullptr, IID_PPV_ARGS(textures[slot].put())), "texture_create");
    }
    void upload(unsigned slot, UINT bytesPerPixel) {
        const D3D12_RESOURCE_DESC desc = textures[slot]->GetDesc();
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};
        UINT rows = 0; UINT64 rowBytes = 0, total = 0;
        device->GetCopyableFootprints(&desc, 0, 1, 0, &fp, &rows, &rowBytes, &total);
        need(desc.Width <= RW && desc.Height <= RH && fp.Footprint.Depth == 1 &&
             rows == desc.Height && rowBytes == desc.Width * bytesPerPixel &&
             fp.Footprint.RowPitch >= rowBytes && total > 0 && total <= UploadLimit &&
             fp.Offset <= total && rows > 0 &&
             static_cast<UINT64>(rows - 1) * fp.Footprint.RowPitch + rowBytes <= total - fp.Offset,
             "upload_footprint");
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = total; buffer.Height = 1;
        buffer.DepthOrArraySize = 1; buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
             D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(uploads[slot].put())), "upload_create");
        void* mapped = nullptr;
        const D3D12_RANGE noRead{0, 0};
        hr(uploads[slot]->Map(0, &noRead, &mapped), "upload_map");
        if (!mapped) { uploads[slot]->Unmap(0, nullptr); throw Failure{"upload_map", -1}; }
        std::memset(mapped, 0, static_cast<std::size_t>(total));
        auto* bytes = static_cast<unsigned char*>(mapped);
        for (UINT y = 0; y < rows; ++y) {
            auto* row = bytes + static_cast<std::size_t>(fp.Offset) +
                        static_cast<std::size_t>(y) * fp.Footprint.RowPitch;
            for (UINT x = 0; x < static_cast<UINT>(desc.Width); ++x) {
                auto* pixel = row + static_cast<std::size_t>(x) * bytesPerPixel;
                if (slot == 0) {
                    // Exact IEEE binary16 constants, a static analytic HDR checker.
                    const bool bright = ((x / 64 + y / 64) & 1u) != 0;
                    const std::array<uint16_t, 4> rgba{{
                        static_cast<uint16_t>(bright ? 0x4000 : 0x3400), 0x3800, 0x3400, 0x3c00}};
                    std::memcpy(pixel, rgba.data(), sizeof(rgba));
                } else if (slot == 1 || slot == 3) {
                    const float value = slot == 1 ? 0.5f : 1.0f;
                    std::memcpy(pixel, &value, sizeof(value));
                } // Motion is already zero, in R16G16_FLOAT.
            }
        }
        const D3D12_RANGE written{0, static_cast<SIZE_T>(total)};
        uploads[slot]->Unmap(0, &written);
        D3D12_TEXTURE_COPY_LOCATION src{};
        src.pResource = uploads[slot].get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint = fp;
        D3D12_TEXTURE_COPY_LOCATION dst{};
        dst.pResource = textures[slot].get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = textures[slot].get();
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        list->ResourceBarrier(1, &barrier);
    }
    void createReadback() {
        const auto desc = textures[4]->GetDesc();
        UINT rows = 0; UINT64 rowBytes = 0;
        device->GetCopyableFootprints(&desc, 0, 1, 0, &readbackFootprint, &rows, &rowBytes, &readbackBytes);
        need(desc.Format == DXGI_FORMAT_R9G9B9E5_SHAREDEXP && desc.Width == DW && desc.Height == DH &&
             rows == DH && rowBytes == static_cast<UINT64>(DW) * 4 &&
             readbackFootprint.Footprint.Depth == 1 && readbackFootprint.Footprint.RowPitch >= rowBytes &&
             readbackBytes > 0 && readbackBytes <= UploadLimit && readbackFootprint.Offset <= readbackBytes &&
             static_cast<UINT64>(rows - 1) * readbackFootprint.Footprint.RowPitch + rowBytes <=
                 readbackBytes - readbackFootprint.Offset, "readback_footprint");
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = readbackBytes; buffer.Height = 1;
        buffer.DepthOrArraySize = 1; buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
             D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(readback.put())), "readback_create");
    }
    void copyOutput() {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = textures[4].get();
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        list->ResourceBarrier(1, &barrier);
        D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
        src.pResource = textures[4].get(); src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = readback.get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint = readbackFootprint;
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        std::swap(barrier.Transition.StateBefore, barrier.Transition.StateAfter);
        list->ResourceBarrier(1, &barrier);
    }
    void checkOutput(unsigned frame) {
        // Only map after submit() confirms fence completion and device health.
        void* mapped = nullptr;
        const D3D12_RANGE readRange{0, static_cast<SIZE_T>(readbackBytes)};
        hr(readback->Map(0, &readRange, &mapped), "readback_map");
        if (!mapped) { readback->Unmap(0, nullptr); throw Failure{"readback_map", -1}; }
        rgb[frame] = scanRGB9E5(static_cast<const unsigned char*>(mapped),
            static_cast<std::size_t>(readbackFootprint.Offset), readbackFootprint.Footprint.RowPitch, DW, DH);
        const D3D12_RANGE noWrite{0, 0};
        readback->Unmap(0, &noWrite);
        ++rgbFramesChecked;
    }
public:
    std::array<RGBStats, 2> rgb{};
    unsigned rgbFramesChecked = 0;
    bool rgbValidationPassed() const noexcept {
        return rgbFramesChecked == 2 && rgb[0].valid() && rgb[1].valid();
    }
    unsigned frames = 0;
    uint64_t providerVersion = 0;
    bool ran = false, destroyed = false, deviceHealthy = false, cleanupWaitOK = true;
    uint32_t destroyCode = FFX_API_RETURN_ERROR;
    ~Probe() { cleanup(); }
    void run(const std::wstring& bundle) {
        regular(bundle, true);
        std::wstring dll = bundle;
        if (dll.back() != L'\\') dll += L'\\';
        dll += L"amd_fidelityfx_dx12.dll";
        need(dll.size() <= 240, "provider_path_length");
        regular(dll, false);
        search.restrictTo(bundle);
        module.value = LoadLibraryExW(dll.c_str(), nullptr,
                                     LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
        need(module.value != nullptr, "provider_load");
        create = module.function<PfnFfxCreateContext>("ffxCreateContext");
        destroy = module.function<PfnFfxDestroyContext>("ffxDestroyContext");
        configure = module.function<PfnFfxConfigure>("ffxConfigure");
        query = module.function<PfnFfxQuery>("ffxQuery");
        dispatch = module.function<PfnFfxDispatch>("ffxDispatch");
        hr(CreateDXGIFactory1(IID_PPV_ARGS(factory.put())), "factory_create");
        bool found = false;
        for (UINT index = 0; index < 64; ++index) {
            const HRESULT result = factory->EnumAdapters1(index, adapter.put());
            if (result == DXGI_ERROR_NOT_FOUND) break;
            hr(result, "adapter_enumerate");
            DXGI_ADAPTER_DESC1 desc{};
            hr(adapter->GetDesc1(&desc), "adapter_description");
            if (desc.VendorId == 0x5143 && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) {
                found = true; break;
            }
        }
        need(found, "qualcomm_hardware_adapter");
        hr(D3D12CreateDevice(adapter.get(), D3D_FEATURE_LEVEL_12_0,
                            IID_PPV_ARGS(device.put())), "device_create");
        D3D12_FEATURE_DATA_D3D12_OPTIONS1 options{};
        hr(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1, &options,
                                      sizeof(options)), "wave_query");
        need(options.WaveOps && options.WaveLaneCountMin == 64 &&
             options.WaveLaneCountMax == 64, "physical_wave64_required");
        D3D12_COMMAND_QUEUE_DESC qdesc{};
        qdesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        hr(device->CreateCommandQueue(&qdesc, IID_PPV_ARGS(queue.put())), "queue_create");
        hr(device->CreateCommandAllocator(qdesc.Type, IID_PPV_ARGS(allocator.put())), "allocator_create");
        hr(device->CreateCommandList(0, qdesc.Type, allocator.get(), nullptr,
                                    IID_PPV_ARGS(list.put())), "command_create");
        hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(fence.put())), "fence_create");
        event.set(CreateEventW(nullptr, FALSE, FALSE, nullptr));
        need(event.valid(), "event_create");
        ffxConfigureDescGlobalDebug1 debug{};
        debug.header.type = FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG1;
        debug.fpMessage = message;
        debug.debugLevel = FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_ERRORS;
        ffx(configure(nullptr, &debug.header), "debug_configure");
        ffxQueryDescGetVersions versions{};
        versions.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
        versions.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
        versions.device = device.get();
        uint64_t count = 0;
        versions.outputCount = &count;
        ffx(query(nullptr, &versions.header), "version_count");
        need(count > 0 && count <= 16, "version_capacity");
        std::array<uint64_t, 16> ids{};
        std::array<const char*, 16> names{};
        const uint64_t capacity = count;
        versions.versionIds = ids.data(); versions.versionNames = names.data();
        ffx(query(nullptr, &versions.header), "version_query");
        need(count > 0 && count <= capacity, "version_result_count");
        unsigned matches = 0;
        for (uint64_t i = 0; i < count; ++i) {
            if (isHelix(names[static_cast<std::size_t>(i)])) {
                providerVersion = ids[static_cast<std::size_t>(i)]; ++matches;
            }
        }
        need(matches == 1 && providerVersion != 0, "helix_provider_selection");
        backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
        backend.device = device.get();
        overrideVersion.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
        overrideVersion.header.pNext = &backend.header;
        overrideVersion.versionId = providerVersion;
        contextDesc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
        contextDesc.header.pNext = &overrideVersion.header;
        contextDesc.flags = FFX_UPSCALE_ENABLE_HIGH_DYNAMIC_RANGE | FFX_UPSCALE_ENABLE_DEPTH_INVERTED |
                            FFX_UPSCALE_ENABLE_DEPTH_INFINITE;
        contextDesc.maxRenderSize = {RW, RH}; contextDesc.maxUpscaleSize = {DW, DH};
        contextDesc.fpMessage = message;
        ffx(create(&context, &contextDesc.header, nullptr), "context_create");
        need(context != nullptr, "context_nonnull");
        ffxQueryGetProviderVersion active{};
        active.header.type = FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
        ffx(query(&context, &active.header), "active_provider_query");
        need(active.versionId == providerVersion && isHelix(active.versionName), "active_provider");
        texture(0, RW, RH, DXGI_FORMAT_R16G16B16A16_FLOAT, false);
        texture(1, RW, RH, DXGI_FORMAT_R32_FLOAT, false);
        texture(2, RW, RH, DXGI_FORMAT_R16G16_FLOAT, false);
        texture(3, 1, 1, DXGI_FORMAT_R32_FLOAT, false);
        texture(4, DW, DH, DXGI_FORMAT_R9G9B9E5_SHAREDEXP, true);
        upload(0, 8); upload(1, 4); upload(2, 4); upload(3, 4);
        createReadback();
        submit();
        int32_t phases = 0;
        ffxQueryDescUpscaleGetJitterPhaseCount phase{};
        phase.header.type = FFX_API_QUERY_DESC_TYPE_UPSCALE_GETJITTERPHASECOUNT;
        phase.renderWidth = RW; phase.displayWidth = DW; phase.pOutPhaseCount = &phases;
        ffx(query(&context, &phase.header), "jitter_phase_query");
        need(phases > 0 && phases <= 4096, "jitter_phase_bounds");
        for (int32_t frame = 0; frame < 2; ++frame) {
            float jx = 0, jy = 0;
            ffxQueryDescUpscaleGetJitterOffset jitter{};
            jitter.header.type = FFX_API_QUERY_DESC_TYPE_UPSCALE_GETJITTEROFFSET;
            jitter.index = frame; jitter.phaseCount = phases;
            jitter.pOutX = &jx; jitter.pOutY = &jy;
            ffx(query(&context, &jitter.header), "jitter_offset_query");
            need(std::isfinite(jx) && std::isfinite(jy) && std::fabs(jx) <= 1 &&
                 std::fabs(jy) <= 1, "jitter_bounds");
            begin();
            ffxDispatchDescUpscale desc{};
            desc.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
            desc.commandList = list.get();
            desc.color = ffxApiGetResourceDX12(textures[0].get());
            desc.depth = ffxApiGetResourceDX12(textures[1].get());
            desc.motionVectors = ffxApiGetResourceDX12(textures[2].get());
            desc.exposure = ffxApiGetResourceDX12(textures[3].get());
            desc.reactive = ffxApiGetResourceDX12(nullptr);
            desc.transparencyAndComposition = ffxApiGetResourceDX12(nullptr);
            desc.output = ffxApiGetResourceDX12(textures[4].get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
            desc.jitterOffset = {jx, jy};
            desc.motionVectorScale = {static_cast<float>(RW), static_cast<float>(RH)};
            desc.renderSize = {RW, RH}; desc.upscaleSize = {DW, DH};
            desc.enableSharpening = false; desc.sharpness = 0;
            desc.frameTimeDelta = 16.666667f; desc.preExposure = 1;
            desc.reset = frame == 0;
            desc.cameraNear = 0.1f; desc.cameraFar = std::numeric_limits<float>::max();
            desc.cameraFovAngleVertical = 1.047f; desc.viewSpaceToMetersFactor = 1;
            ffx(dispatch(&context, &desc.header), "upscale_dispatch");
            D3D12_RESOURCE_BARRIER barrier{};
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barrier.UAV.pResource = textures[4].get();
            list->ResourceBarrier(1, &barrier);
            copyOutput();
            submit(); ++frames;
            checkOutput(static_cast<unsigned>(frame));
            need(errors.load() == 0, "provider_error_callback");
        }
        ran = true;
    }
    void cleanup() noexcept {
        if (cleaned) return;
        cleaned = true;
        if (inFlight && queue.get() && fence.get() && device.get() && event.valid()) {
            try {
                // Signal again if the original submission's Signal failed.
                ++fenceValue;
                hr(queue->Signal(fence.get(), fenceValue), "cleanup_signal");
                wait();
            } catch (...) { cleanupWaitOK = false; }
        }
        if (inFlight && !cleanupWaitOK && device.get() &&
            SUCCEEDED(device->GetDeviceRemovedReason())) {
            // A healthy but unresponsive queue may still reference every allocation.
            // Do not destroy its context, unload code or release resources underneath
            // that work. Keep this bounded set alive until the helper process exits;
            // OS process teardown is responsible for reclamation in this failure case.
            // The report remains failed and destruction is explicitly unconfirmed.
            context = nullptr;
            for (auto& resource : textures) resource.abandon();
            for (auto& resource : uploads) resource.abandon();
            readback.abandon();
            list.abandon(); allocator.abandon(); queue.abandon(); fence.abandon();
            device.abandon(); adapter.abandon(); factory.abandon(); event.abandon();
            module.abandon(); search.abandon();
            deviceHealthy = false;
            return;
        }
        if (context && destroy) {
            destroyCode = destroy(&context, nullptr);
            destroyed = destroyCode == FFX_API_RETURN_OK;
            context = nullptr; // One destruction attempt; never retry an unknown context.
        }
        deviceHealthy = device.get() && SUCCEEDED(device->GetDeviceRemovedReason());
    }
    bool passed() const noexcept {
        return ran && frames == 2 && destroyed && deviceHealthy && cleanupWaitOK && errors.load() == 0;
    }
};

std::string number(double value) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
    return stream.str();
}
void writeReport(HANDLE file, const Probe& probe, const char* stage, std::int64_t code) {
    // All text tokens originate in this source; no argument, DLL name or message is copied.
    std::string report =
        "{\"schema\":1,\"event\":\"probe\",\"provider\":\"HelixSR\",\"provider_version_id\":" +
        std::to_string(probe.providerVersion) + ",\"render\":[752,424],\"display\":[1280,720],\"output_dxgi_format\":67}\n" +
        "{\"event\":\"result\",\"passed\":" + (probe.passed() ? "true" : "false") +
        ",\"stage\":\"" + stage + "\",\"code\":" + std::to_string(code) +
        ",\"rgb_validation_passed\":" + (probe.rgbValidationPassed() ? "true" : "false") +
        ",\"rgb_frames_checked\":" + std::to_string(probe.rgbFramesChecked) +
        ",\"exposure\":\"unit\"" +
        ",\"dispatches_completed\":" + std::to_string(probe.frames) +
        ",\"error_callbacks\":" + std::to_string(errors.load()) +
        ",\"warning_callbacks\":" + std::to_string(warnings.load()) +
        ",\"destroy_ok\":" + (probe.destroyed ? "true" : "false") +
        ",\"destroy_code\":" + std::to_string(probe.destroyCode) +
        ",\"device_healthy\":" + (probe.deviceHealthy ? "true" : "false") +
        ",\"cleanup_wait_ok\":" + (probe.cleanupWaitOK ? "true" : "false") +
        ",\"gameplay_tested\":false,\"quality_tested\":false,\"performance_tested\":false}\n";
    for (unsigned frame = 0; frame < probe.rgbFramesChecked; ++frame) {
        const auto& stats = probe.rgb[frame];
        report += "{\"event\":\"rgb_validation\",\"frame\":" + std::to_string(frame) +
            ",\"pixels_checked\":" + std::to_string(stats.count) +
            ",\"finite\":" + (stats.finite ? "true" : "false") +
            ",\"nonblack\":" + (stats.nonblack ? "true" : "false") +
            ",\"spatially_constant\":" + (stats.constant() ? "true" : "false") +
            ",\"passed\":" + (stats.valid() ? "true" : "false") +
            ",\"checker_luminance_correlation\":" + number(stats.correlation()) +
            ",\"structure_pixels_checked\":" + std::to_string(stats.structureCount) +
            ",\"structure_acceptance_threshold\":null,\"structure_acceptance_enforced\":false";
        const char* names[] = {"r", "g", "b"};
        for (unsigned c = 0; c < 3; ++c) {
            report += ",\"" + std::string(names[c]) + "\":{\"min\":" + number(stats.low[c]) +
                ",\"max\":" + number(stats.high[c]) +
                ",\"range\":" + number(stats.high[c] - stats.low[c]) +
                ",\"mean\":" + number(stats.mean[c]) +
                ",\"variance\":" + number(stats.count ? stats.m2[c] / stats.count : 0) + "}";
        }
        report += "}\n";
    }
    need(report.size() <= ReportLimit, "report_size");
    DWORD written = 0;
    need(WriteFile(file, report.data(), static_cast<DWORD>(report.size()), &written, nullptr) != 0 &&
         written == report.size(), "report_write");
    need(FlushFileBuffers(file) != 0, "report_flush");
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc == 2 && std::wcscmp(argv[1], L"--numeric-self-test") == 0)
        return numericSelfTest() ? 0 : 1;
    if (argc != 3) return 2;
    Handle report;
    try {
        const std::wstring bundle = path(argv[1], true);
        const std::wstring output = path(argv[2], false);
        report.set(CreateFileW(output.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        need(report.valid(), "report_create_new");
        Probe probe;
        const char* stage = "completed";
        std::int64_t code = 0;
        try {
            WorkingDirectory cwd(bundle);
            try {
                probe.run(bundle);
            } catch (const Failure& failure) {
                stage = failure.stage; code = failure.code;
            } catch (...) {
                stage = "unexpected_exception"; code = -1;
            }
            // Destruction also occurs on failures before restoring the original directory.
            probe.cleanup();
        } catch (const Failure& failure) {
            stage = failure.stage; code = failure.code;
            probe.cleanup();
        } catch (...) {
            stage = "unexpected_exception"; code = -1;
            probe.cleanup();
        }
        if (std::strcmp(stage, "completed") == 0 && !probe.passed()) {
            stage = "final_validation"; code = -1;
        }
        writeReport(report.get(), probe, stage, code);
        return probe.passed() ? 0 : 1;
    } catch (...) {
        // No stdout, paths, private data or secondary report are emitted on I/O/argument failure.
        return 2;
    }
}
