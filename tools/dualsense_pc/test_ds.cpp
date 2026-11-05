// Prueba: carga xinput1_3.dll (la de ReForge) desde esta carpeta, comprueba las exportaciones,
// lee el mando y prueba el gancho de texturas D3D11 (volcado).
#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#pragma comment(lib, "d3d11.lib")
struct XS { DWORD p; WORD b; BYTE lt, rt; SHORT lx, ly, rx, ry; };
struct XV { WORD l, r; };
int main() {
  HMODULE m = LoadLibraryW(L".\\xinput1_3.dll");
  if (!m) { printf("no carga %lu\n", GetLastError()); return 1; }
  auto gs = (DWORD(WINAPI*)(DWORD, XS*))GetProcAddress(m, "XInputGetState");
  auto ss = (DWORD(WINAPI*)(DWORD, XV*))GetProcAddress(m, "XInputSetState");
  auto gx = (DWORD(WINAPI*)(DWORD, XS*))GetProcAddress(m, (LPCSTR)100);
  printf("exportaciones: %p %p %p\n", gs, ss, gx);
  Sleep(1500);
  for (int i = 0; i < 4; ++i) { XS s{}; DWORD r = gs(i, &s); printf("mando %d -> %lu botones %04X LT %u RT %u LX %d\n", i, r, s.b, s.lt, s.rt, s.lx); }
  XV v{0x8000, 0x8000}; printf("vibración -> %lu\n", ss(0, &v)); Sleep(300); v = {0, 0}; ss(0, &v);
  Sleep(1500);  // el gancho D3D11 se instala en segundo plano
  ID3D11Device* dev = nullptr; D3D_FEATURE_LEVEL fl;
  HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, nullptr);
  printf("dispositivo %08lX\n", hr);
  static unsigned px[64 * 64];
  for (int i = 0; i < 64 * 64; ++i) px[i] = 0xFF00A000 | (i & 255);
  D3D11_TEXTURE2D_DESC d{}; d.Width = 64; d.Height = 64; d.MipLevels = 1; d.ArraySize = 1; d.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
  d.SampleDesc.Count = 1; d.Usage = D3D11_USAGE_DEFAULT; d.BindFlags = D3D11_BIND_SHADER_RESOURCE;
  D3D11_SUBRESOURCE_DATA s{px, 64 * 4, 0}; ID3D11Texture2D* t = nullptr;
  hr = dev->CreateTexture2D(&d, &s, &t); printf("textura %08lX\n", hr);
  ID3D11ShaderResourceView* v2 = nullptr; hr = dev->CreateShaderResourceView(t, nullptr, &v2); printf("vista %08lX\n", hr);
  return 0;
}
