#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "user32.lib")
int main() {
  LoadLibraryW(L".\\xinput1_3.dll");
  Sleep(2000);
  WNDCLASSW wc{}; wc.lpfnWndProc = DefWindowProcW; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"t";
  RegisterClassW(&wc);
  HWND w = CreateWindowW(L"t", L"t", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, nullptr, nullptr, wc.hInstance, nullptr);
  DXGI_SWAP_CHAIN_DESC sd{}; sd.BufferCount = 2; sd.BufferDesc.Width = 64; sd.BufferDesc.Height = 64;
  sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM; sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; sd.OutputWindow = w;
  sd.SampleDesc.Count = 1; sd.Windowed = TRUE; sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
  IDXGISwapChain* sc; ID3D11Device* d; ID3D11DeviceContext* c;
  HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &sd, &sc, &d, nullptr, &c);
  printf("swapchain %08lX\n", hr);
  LARGE_INTEGER f, a, b; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&a);
  for (int i = 0; i < 2000; ++i) sc->Present(0, 0);
  QueryPerformanceCounter(&b);
  double s = (b.QuadPart - a.QuadPart) / (double)f.QuadPart;
  printf("2000 fotogramas en %.2f s = %.1f FPS\n", s, 2000 / s);
}
