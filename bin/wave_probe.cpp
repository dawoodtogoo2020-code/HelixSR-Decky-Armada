// Original, read-only D3D12 adapter capability query. No shader or workload.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <cstdio>
#include <string>

static FILE* report = stdout;

static std::string json_escape(const std::string& value) {
    std::string result;
    for (unsigned char c : value) {
        switch (c) {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if (c < 0x20) {
                char out[7]; std::snprintf(out, sizeof(out), "\\u%04x", c); result += out;
            } else result += static_cast<char>(c);
        }
    }
    return result;
}

static std::string utf8(const wchar_t* input) {
    int size = WideCharToMultiByte(CP_UTF8, 0, input, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string output(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, input, -1, output.data(), size, nullptr, nullptr);
    output.pop_back();
    return output;
}

static int error(const char* stage, HRESULT hr, int code, bool device_created = false) {
    std::fprintf(report, "{\"ok\":false,\"stage\":\"%s\",\"hresult\":\"0x%08lx\",\"d3d12_device_created\":%s,\"vkd3d_identity_verified\":false}\n",
                 stage, static_cast<unsigned long>(hr), device_created ? "true" : "false");
    std::fflush(report);
    return code;
}

int main(int argc, char** argv) {
    if (argc > 2) return error("usage_optional_output_file", E_INVALIDARG, 10);
    if (argc == 2) {
        report = std::fopen(argv[1], "wb");
        if (!report) {
            report = stdout;
            return error("output_file_open", HRESULT_FROM_WIN32(GetLastError()), 11);
        }
    }
    IDXGIFactory1* factory = nullptr;
    HRESULT hr = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
    if (FAILED(hr)) return error("CreateDXGIFactory1", hr, 2);

    IDXGIAdapter1* selected = nullptr;
    DXGI_ADAPTER_DESC1 desc{};
    for (UINT index = 0; ; ++index) {
        IDXGIAdapter1* adapter = nullptr;
        hr = factory->EnumAdapters1(index, &adapter);
        if (hr == DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(hr)) { factory->Release(); return error("EnumAdapters1", hr, 3); }
        DXGI_ADAPTER_DESC1 candidate{};
        hr = adapter->GetDesc1(&candidate);
        if (FAILED(hr)) { adapter->Release(); factory->Release(); return error("GetDesc1", hr, 4); }
        if (candidate.VendorId == 0x5143 && !(candidate.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) {
            selected = adapter; desc = candidate; break;
        }
        adapter->Release();
    }
    factory->Release();
    if (!selected) return error("Qualcomm_adapter_missing", DXGI_ERROR_NOT_FOUND, 5);

    ID3D12Device* device = nullptr;
    hr = D3D12CreateDevice(selected, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device));
    selected->Release();
    if (FAILED(hr)) return error("D3D12CreateDevice", hr, 6);

    D3D12_FEATURE_DATA_D3D12_OPTIONS1 wave{};
    hr = device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1, &wave, sizeof(wave));
    if (FAILED(hr)) { device->Release(); return error("D3D12_OPTIONS1", hr, 7, true); }
    D3D12_FEATURE_DATA_D3D12_OPTIONS4 options4{};
    hr = device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS4, &options4, sizeof(options4));
    if (FAILED(hr)) { device->Release(); return error("D3D12_OPTIONS4", hr, 8, true); }
    device->Release();

    const bool supported = wave.WaveOps && wave.WaveLaneCountMin == 64 &&
                           wave.WaveLaneCountMax == 64 && options4.Native16BitShaderOpsSupported;
    std::string name = json_escape(utf8(desc.Description));
    std::fprintf(report, "{\"ok\":%s,\"vendor_id\":%u,\"device_id\":%u,\"description\":\"%s\","
                 "\"wave_ops\":%s,\"wave_min\":%u,\"wave_max\":%u,\"native16\":%s,"
                 "\"d3d12_device_created\":true,\"vkd3d_identity_verified\":false,\"reason\":\"%s\"}\n",
                 supported ? "true" : "false", desc.VendorId, desc.DeviceId, name.c_str(),
                 wave.WaveOps ? "true" : "false", wave.WaveLaneCountMin,
                 wave.WaveLaneCountMax, options4.Native16BitShaderOpsSupported ? "true" : "false",
                 supported ? "supported" : "requires_exact_wave64_and_native16");
    std::fflush(report);
    return supported ? 0 : 9;
}
