#include <windows.h>
#include <cstdio>
struct XS { DWORD p; WORD b; BYTE lt, rt; SHORT lx, ly, rx, ry; };
int main() {
  HMODULE m = LoadLibraryW(L".\\xinput1_3.dll");
  auto gs = (DWORD(WINAPI*)(DWORD, XS*))GetProcAddress(m, "XInputGetState");
  DWORD last = 0; int changes = 0;
  for (int i = 0; i < 200; ++i) {  // 20 s
    XS s{}; DWORD r = gs(0, &s);
    if (s.p != last) { ++changes; last = s.p; if (changes < 15) printf("t=%d r=%lu pkt=%lu b=%04X LT=%u RT=%u LX=%d LY=%d\n", i, r, s.p, s.b, s.lt, s.rt, s.lx, s.ly); }
    Sleep(100);
  }
  printf("cambios=%d\n", changes);
}
