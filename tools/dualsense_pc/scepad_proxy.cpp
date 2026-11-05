// ReForge DualSense · libScePad.dll de reemplazo (God of War y otros juegos de PC con la librería de Sony).
//
// La librería de Sony de algunos juegos solo ve el DualSense por cable. Esta DLL:
//   * Pasa todas las llamadas a la librería original (renombrada a libScePad_sony.dll).
//   * Si la original no ve el mando (p. ej. por Bluetooth), lee el DualSense directamente por HID y se lo
//     entrega al juego en el mismo formato (botones, sticks, L2/R2, panel táctil), y aplica la vibración
//     y la barra de luz que pide el juego.
//   * Añade gatillos adaptativos (L2 apuntar, R2 con "clic", vibración del gatillo con golpes fuertes),
//     por USB o Bluetooth.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <hidpi.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#pragma comment(lib, "hid.lib")
#pragma comment(lib, "setupapi.lib")
// funciones que pasan tal cual a la librería original
#pragma comment(linker, "/export:scePadClose=libScePad_sony.scePadClose,@1")
#pragma comment(linker, "/export:scePadGetContainerIdInformation=libScePad_sony.scePadGetContainerIdInformation,@2")
#pragma comment(linker, "/export:scePadGetControllerInformation=libScePad_sony.scePadGetControllerInformation,@3")
#pragma comment(linker, "/export:scePadGetHandle=libScePad_sony.scePadGetHandle,@5")
#pragma comment(linker, "/export:scePadGetJackState=libScePad_sony.scePadGetJackState,@6")
#pragma comment(linker, "/export:scePadGetParticularMode=libScePad_sony.scePadGetParticularMode,@7")
#pragma comment(linker, "/export:scePadGetTriggerEffectState=libScePad_sony.scePadGetTriggerEffectState,@8")
#pragma comment(linker, "/export:scePadInit=libScePad_sony.scePadInit,@9")
#pragma comment(linker, "/export:scePadIsSupportedAudioFunction=libScePad_sony.scePadIsSupportedAudioFunction,@10")
#pragma comment(linker, "/export:scePadOpen=libScePad_sony.scePadOpen,@11")
#pragma comment(linker, "/export:scePadResetOrientation=libScePad_sony.scePadResetOrientation,@15")
#pragma comment(linker, "/export:scePadSetAngularVelocityDeadbandState=libScePad_sony.scePadSetAngularVelocityDeadbandState,@16")
#pragma comment(linker, "/export:scePadSetAudioOutPath=libScePad_sony.scePadSetAudioOutPath,@17")
#pragma comment(linker, "/export:scePadSetMotionSensorState=libScePad_sony.scePadSetMotionSensorState,@19")
#pragma comment(linker, "/export:scePadSetParticularMode=libScePad_sony.scePadSetParticularMode,@20")
#pragma comment(linker, "/export:scePadSetTiltCorrectionState=libScePad_sony.scePadSetTiltCorrectionState,@21")
#pragma comment(linker, "/export:scePadSetTriggerEffect=libScePad_sony.scePadSetTriggerEffect,@22")
#pragma comment(linker, "/export:scePadSetVibrationMode=libScePad_sony.scePadSetVibrationMode,@24")
#pragma comment(linker, "/export:scePadSetVolumeGain=libScePad_sony.scePadSetVolumeGain,@25")

namespace {

std::wstring g_dir;
FILE* g_log = nullptr;
std::mutex g_log_m;

void Log(const char* fmt, ...) {
  std::lock_guard<std::mutex> l(g_log_m);
  if (!g_log) g_log = _wfopen((g_dir + L"\\reforge_dualsense.log").c_str(), L"w");
  if (!g_log) return;
  SYSTEMTIME t;
  GetLocalTime(&t);
  fprintf(g_log, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
  va_list ap;
  va_start(ap, fmt);
  vfprintf(g_log, fmt, ap);
  va_end(ap);
  fputc('\n', g_log);
  fflush(g_log);
}

int IniInt(const wchar_t* key, int def) {
  return (int)GetPrivateProfileIntW(L"dualsense", key, def, (g_dir + L"\\reforge_dualsense.ini").c_str());
}

struct Config {
  bool triggers = true, direct = true;
  int intensity = 100;
  int l2_start = 3, l2_strength = 4;
  int r2_start = 4, r2_strength = 5, r2_aim_strength = 7;
  int hit_freq = 28;
} g_cfg;

// ---------------------------------------------------------------------------- efectos de gatillo
using Effect = std::array<uint8_t, 11>;
Effect EffOff() { Effect e{}; e[0] = 0x05; return e; }
Effect Zones(uint8_t mode, int pos, int val) {
  Effect e{};
  uint32_t v = (uint32_t)((val - 1) & 7), z = 0;
  uint16_t a = 0;
  for (int i = pos; i < 10; ++i) { z |= v << (3 * i); a |= (uint16_t)(1 << i); }
  e[0] = mode; e[1] = a & 0xFF; e[2] = a >> 8;
  e[3] = z & 0xFF; e[4] = (z >> 8) & 0xFF; e[5] = (z >> 16) & 0xFF; e[6] = (z >> 24) & 0xFF;
  return e;
}
Effect EffFeedback(int pos, int s) { return s <= 0 ? EffOff() : Zones(0x21, pos, s); }
Effect EffVibration(int pos, int amp, int freq) {
  if (amp <= 0) return EffOff();
  Effect e = Zones(0x26, pos, amp);
  e[9] = (uint8_t)freq;
  return e;
}
Effect EffWeapon(int start, int end, int s) {
  if (s <= 0) return EffOff();
  Effect e{};
  uint16_t z = (uint16_t)((1 << start) | (1 << end));
  e[0] = 0x25; e[1] = z & 0xFF; e[2] = z >> 8; e[3] = (uint8_t)((s - 1) & 7);
  return e;
}
int Scale(int s) { return s <= 0 ? 0 : std::max(1, std::min(8, (s * g_cfg.intensity + 50) / 100)); }

uint32_t Crc32(const uint8_t* d, size_t n, uint32_t crc) {
  for (size_t i = 0; i < n; ++i) {
    crc ^= d[i];
    for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
  }
  return crc;
}

// ---------------------------------------------------------------------------------- estado común
// botones en el formato de la librería de Sony
enum : uint32_t {
  B_SHARE = 0x1, B_L3 = 0x2, B_R3 = 0x4, B_OPTIONS = 0x8, B_UP = 0x10, B_RIGHT = 0x20, B_DOWN = 0x40,
  B_LEFT = 0x80, B_L2 = 0x100, B_R2 = 0x200, B_L1 = 0x400, B_R1 = 0x800, B_TRIANGLE = 0x1000,
  B_CIRCLE = 0x2000, B_CROSS = 0x4000, B_SQUARE = 0x8000, B_TOUCH = 0x100000,
};

struct Pad {
  bool ok = false;      // hay datos frescos del DualSense por HID
  uint32_t buttons = 0;
  uint8_t lx = 128, ly = 128, rx = 128, ry = 128, l2 = 0, r2 = 0;
  uint8_t touch_n = 0;
  uint16_t tx[2] = {}, ty[2] = {};
  uint8_t tid[2] = {};
};
std::mutex g_pad_m;
Pad g_pad;
std::atomic<bool> g_sony_sees_pad{false};   // la librería original sí ve el mando (USB)
std::atomic<uint8_t> g_vib_big{0}, g_vib_small{0};
std::atomic<uint8_t> g_lr{0}, g_lg{60}, g_lb{200};
std::atomic<ULONGLONG> g_last_hit{0};
std::atomic<int> g_hit_strength{0};
std::atomic<unsigned> g_reads{0}, g_filled{0}, g_vibes{0};

// ------------------------------------------------------------------------------------ HID directo
struct Dev {
  HANDLE h = INVALID_HANDLE_VALUE, hw = INVALID_HANDLE_VALUE;
  bool bt = false;
  USHORT in_len = 0, out_len = 0;
  uint8_t seq = 0;
};

bool OpenDS(Dev& d) {
  GUID hid;
  HidD_GetHidGuid(&hid);
  HDEVINFO set = SetupDiGetClassDevsW(&hid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (set == INVALID_HANDLE_VALUE) return false;
  bool ok = false;
  SP_DEVICE_INTERFACE_DATA ifd{sizeof(ifd)};
  for (DWORD i = 0; !ok && SetupDiEnumDeviceInterfaces(set, nullptr, &hid, i, &ifd); ++i) {
    DWORD need = 0;
    SetupDiGetDeviceInterfaceDetailW(set, &ifd, nullptr, 0, &need, nullptr);
    std::vector<uint8_t> buf(need);
    auto* det = (SP_DEVICE_INTERFACE_DETAIL_DATA_W*)buf.data();
    det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(set, &ifd, det, need, nullptr, nullptr)) continue;
    HANDLE h = CreateFileW(det->DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
    if (h == INVALID_HANDLE_VALUE) continue;
    HIDD_ATTRIBUTES at{sizeof(at)};
    if (HidD_GetAttributes(h, &at) && at.VendorID == 0x054C && (at.ProductID == 0x0CE6 || at.ProductID == 0x0DF2)) {
      PHIDP_PREPARSED_DATA pp = nullptr;
      HIDP_CAPS caps{};
      if (HidD_GetPreparsedData(h, &pp)) {
        HidP_GetCaps(pp, &caps);
        HidD_FreePreparsedData(pp);
      }
      if (caps.UsagePage == 0x01 && (caps.Usage == 0x05 || caps.Usage == 0x04)) {
        d.h = h;
        d.hw = CreateFileW(det->DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
        if (d.hw == INVALID_HANDLE_VALUE) d.hw = h;
        d.bt = caps.InputReportByteLength != 64;
        d.in_len = caps.InputReportByteLength;
        d.out_len = caps.OutputReportByteLength;
        if (d.bt) {  // leer la calibración activa los informes completos por Bluetooth
          uint8_t feat[64] = {0x05};
          HidD_GetFeature(h, feat, 41);
        }
        ok = true;
        Log("DualSense %s abierto directamente (entrada %u, salida %u)", d.bt ? "Bluetooth" : "USB", d.in_len,
            d.out_len);
        break;
      }
    }
    CloseHandle(h);
  }
  SetupDiDestroyDeviceInfoList(set);
  return ok;
}

bool Write(Dev& d, const uint8_t* rep, DWORD len) {
  OVERLAPPED ov{};
  ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  DWORD w = 0;
  BOOL ok = WriteFile(d.hw, rep, len, &w, &ov);
  if (!ok && GetLastError() == ERROR_IO_PENDING) {
    if (WaitForSingleObject(ov.hEvent, 250) == WAIT_OBJECT_0) {
      ok = GetOverlappedResult(d.hw, &ov, &w, FALSE);
    } else {
      CancelIoEx(d.hw, &ov);
      GetOverlappedResult(d.hw, &ov, &w, TRUE);
      ok = FALSE;
    }
  }
  CloseHandle(ov.hEvent);
  return ok != FALSE;
}

// full = también vibración y barra de luz (cuando somos nosotros quienes manejamos el mando)
bool SendOutput(Dev& d, const Effect& l2, const Effect& r2, bool full) {
  uint8_t c[47] = {};
  c[0] = 0x04 | 0x08;
  if (full) {
    c[0] |= 0x01 | 0x02;
    c[1] = 0x04 | 0x10;
    c[2] = g_vib_small;  // motor derecho (alta frecuencia)
    c[3] = g_vib_big;    // motor izquierdo
    c[38] = 0x04 | 0x02;
    c[41] = 0x02;
    c[43] = 0x04;        // LED de jugador 1
    c[44] = g_lr;
    c[45] = g_lg;
    c[46] = g_lb;
  }
  memcpy(c + 10, r2.data(), 11);
  memcpy(c + 21, l2.data(), 11);
  if (!d.bt) {
    uint8_t rep[64] = {};
    rep[0] = 0x02;
    memcpy(rep + 1, c, sizeof(c));
    return Write(d, rep, std::max<DWORD>(48, d.out_len));
  }
  uint8_t rep[78] = {};
  rep[0] = 0x31;
  rep[1] = (uint8_t)(d.seq << 4);
  d.seq = (d.seq + 1) & 15;
  rep[2] = 0x10;
  memcpy(rep + 3, c, sizeof(c));
  uint8_t seed = 0xA2;
  uint32_t crc = ~Crc32(rep, 74, Crc32(&seed, 1, 0xFFFFFFFF));
  memcpy(rep + 74, &crc, 4);
  return Write(d, rep, 78);
}

void Parse(const uint8_t* p, bool simple) {
  Pad pad;
  pad.ok = true;
  uint8_t b0, b1, b2;
  pad.lx = p[0];
  pad.ly = p[1];
  pad.rx = p[2];
  pad.ry = p[3];
  if (simple) {
    b0 = p[4]; b1 = p[5]; b2 = p[6]; pad.l2 = p[7]; pad.r2 = p[8];
  } else {
    pad.l2 = p[4]; pad.r2 = p[5]; b0 = p[7]; b1 = p[8]; b2 = p[9];
    // panel táctil: 2 dedos a partir del byte 32 (bit 7 = sin tocar; 12 bits X, 12 bits Y)
    for (int f = 0; f < 2; ++f) {
      const uint8_t* t = p + 32 + f * 4;
      if (!(t[0] & 0x80)) {
        int n = pad.touch_n++;
        pad.tid[n] = t[0] & 0x7F;
        pad.tx[n] = (uint16_t)(t[1] | ((t[2] & 0x0F) << 8));
        pad.ty[n] = (uint16_t)((t[2] >> 4) | (t[3] << 4));
      }
    }
  }
  static const uint32_t hat[9] = {B_UP, B_UP | B_RIGHT, B_RIGHT, B_DOWN | B_RIGHT, B_DOWN, B_DOWN | B_LEFT, B_LEFT,
                                  B_UP | B_LEFT, 0};
  uint32_t w = hat[std::min(8, b0 & 0x0F)];
  if (b0 & 0x10) w |= B_SQUARE;
  if (b0 & 0x20) w |= B_CROSS;
  if (b0 & 0x40) w |= B_CIRCLE;
  if (b0 & 0x80) w |= B_TRIANGLE;
  if (b1 & 0x01) w |= B_L1;
  if (b1 & 0x02) w |= B_R1;
  if (b1 & 0x04) w |= B_L2;
  if (b1 & 0x08) w |= B_R2;
  if (b1 & 0x10) w |= B_SHARE;
  if (b1 & 0x20) w |= B_OPTIONS;
  if (b1 & 0x40) w |= B_L3;
  if (b1 & 0x80) w |= B_R3;
  if (b2 & 0x02) w |= B_TOUCH;
  pad.buttons = w;
  std::lock_guard<std::mutex> l(g_pad_m);
  g_pad = pad;
}

DWORD WINAPI PadThread(void*) {
  Sleep(500);
  for (;;) {
    Dev d;
    if (!OpenDS(d)) {
      { std::lock_guard<std::mutex> l(g_pad_m); g_pad.ok = false; }
      Sleep(2000);
      continue;
    }
    std::vector<uint8_t> buf(std::max<int>(d.in_len, 80));
    OVERLAPPED ov{};
    ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    Effect last_l2{}, last_r2{};
    uint8_t last_vb = 255, last_vs = 255, last_c[3] = {1, 1, 1};
    ULONGLONG last_send = 0, last_stats = GetTickCount64();
    int fails = 0;
    for (;;) {
      DWORD got = 0;
      ResetEvent(ov.hEvent);
      BOOL ok = ReadFile(d.h, buf.data(), d.in_len, &got, &ov);
      if (!ok && GetLastError() == ERROR_IO_PENDING) {
        if (WaitForSingleObject(ov.hEvent, 50) == WAIT_OBJECT_0) {
          ok = GetOverlappedResult(d.h, &ov, &got, FALSE);
        } else {
          CancelIoEx(d.h, &ov);
          GetOverlappedResult(d.h, &ov, &got, TRUE);
          ok = TRUE;
          got = 0;
        }
      }
      if (!ok) {
        if (++fails > 10) {
          Log("Se perdió la conexión directa con el DualSense (error %lu)", GetLastError());
          break;
        }
        Sleep(10);
        continue;
      }
      fails = 0;
      if (got > 10) {
        if (buf[0] == 0x01 && !d.bt) Parse(buf.data() + 1, false);
        else if (buf[0] == 0x31) Parse(buf.data() + 2, false);
        else if (buf[0] == 0x01) Parse(buf.data() + 1, true);
      }
      // salida
      ULONGLONG now = GetTickCount64();
      int l2, r2;
      {
        std::lock_guard<std::mutex> l(g_pad_m);
        l2 = g_pad.l2;
        r2 = g_pad.r2;
      }
      bool full = !g_sony_sees_pad;
      Effect el2 = EffOff(), er2 = EffOff();
      if (g_cfg.triggers && g_cfg.intensity > 0) {
        bool aiming = l2 > 90;
        bool hit = now - g_last_hit < 150 && r2 > 40;
        el2 = EffFeedback(g_cfg.l2_start, Scale(g_cfg.l2_strength));
        er2 = hit ? EffVibration(std::max(0, g_cfg.r2_start - 1), Scale(std::max(3, g_hit_strength.load())), g_cfg.hit_freq)
                  : EffWeapon(g_cfg.r2_start, std::min(8, g_cfg.r2_start + 2),
                              Scale(aiming ? g_cfg.r2_aim_strength : g_cfg.r2_strength));
      }
      uint8_t vb = g_vib_big, vs = g_vib_small, c0 = g_lr, c1 = g_lg, c2 = g_lb;
      bool changed = el2 != last_l2 || er2 != last_r2 ||
                     (full && (vb != last_vb || vs != last_vs || c0 != last_c[0] || c1 != last_c[1] || c2 != last_c[2]));
      if (changed || now - last_send > 300) {
        SendOutput(d, el2, er2, full);
        last_l2 = el2; last_r2 = er2; last_vb = vb; last_vs = vs;
        last_c[0] = c0; last_c[1] = c1; last_c[2] = c2;
        last_send = now;
      }
      if (now - last_stats > 60000) {
        last_stats = now;
        Log("Juego: %u lecturas (%u entregadas por ReForge), %u vibraciones; la librería de Sony %s el mando",
            (unsigned)g_reads, (unsigned)g_filled, (unsigned)g_vibes, g_sony_sees_pad ? "ve" : "no ve");
      }
    }
    CloseHandle(ov.hEvent);
    if (d.hw != d.h) CloseHandle(d.hw);
    CloseHandle(d.h);
    { std::lock_guard<std::mutex> l(g_pad_m); g_pad.ok = false; }
    Sleep(1000);
  }
}

// ------------------------------------------------------------------------- funciones interceptadas
using PFN_Read = int(__cdecl*)(int, void*, int);
using PFN_ReadState = int(__cdecl*)(int, void*);
using PFN_Ptr = int(__cdecl*)(int, const void*);
using PFN_H = int(__cdecl*)(int);
using PFN_Type = int(__cdecl*)(int, void*);
HMODULE g_sony = nullptr;
PFN_Read g_read = nullptr;
PFN_ReadState g_read_state = nullptr;
PFN_Ptr g_set_vib = nullptr, g_set_light = nullptr;
PFN_H g_reset_light = nullptr;
PFN_Type g_get_type = nullptr;

void Sony() {
  if (g_sony) return;
  g_sony = LoadLibraryW((g_dir + L"\\libScePad_sony.dll").c_str());
  if (!g_sony) {
    Log("No encuentro libScePad_sony.dll (la librería original)");
    return;
  }
  g_read = (PFN_Read)GetProcAddress(g_sony, "scePadRead");
  g_read_state = (PFN_ReadState)GetProcAddress(g_sony, "scePadReadState");
  g_set_vib = (PFN_Ptr)GetProcAddress(g_sony, "scePadSetVibration");
  g_set_light = (PFN_Ptr)GetProcAddress(g_sony, "scePadSetLightBar");
  g_reset_light = (PFN_H)GetProcAddress(g_sony, "scePadResetLightBar");
  g_get_type = (PFN_Type)GetProcAddress(g_sony, "scePadGetControllerType");
}

constexpr size_t kPadDataSize = 0x78;  // ScePadData
std::atomic<uint64_t> g_ts{0};

// Completa un ScePadData con el mando leído por ReForge si la librería original no lo ve.
void Fix(uint8_t* p) {
  g_reads++;
  bool connected = p[76] != 0;
  g_sony_sees_pad = connected;
  if (connected || !g_cfg.direct) return;
  Pad pad;
  {
    std::lock_guard<std::mutex> l(g_pad_m);
    pad = g_pad;
  }
  if (!pad.ok) return;
  memcpy(p + 0, &pad.buttons, 4);
  p[4] = pad.lx; p[5] = pad.ly; p[6] = pad.rx; p[7] = pad.ry;
  p[8] = pad.l2; p[9] = pad.r2;
  // panel táctil: ScePadTouchData en 52 (touchNum, 3 reservados, 4 reservados, 2 toques de 8 bytes)
  memset(p + 52, 0, 24);
  p[52] = pad.touch_n;
  for (int i = 0; i < pad.touch_n; ++i) {
    uint8_t* t = p + 60 + i * 8;
    memcpy(t, &pad.tx[i], 2);
    memcpy(t + 2, &pad.ty[i], 2);
    t[4] = pad.tid[i];
  }
  p[76] = 1;  // conectado
  uint64_t ts = (g_ts += 4000);
  memcpy(p + 80, &ts, 8);
  p[104] = 1;  // número de conexiones
  g_filled++;
}

}  // namespace

extern "C" {
__declspec(dllexport) int __cdecl scePadRead(int handle, void* data, int num) {
  Sony();
  if (!g_read) return -1;
  int n = g_read(handle, data, num);
  if (data && num > 0) {
    if (n <= 0 && !g_sony_sees_pad) {
      // la original no tiene datos: entregamos uno nuestro
      memset(data, 0, kPadDataSize);
      ((uint8_t*)data)[24 + 3] = 0x3F;  // orientación w = 1.0
      ((uint8_t*)data)[24 + 2] = 0x80;
      n = 1;
    }
    if (n > 0) Fix((uint8_t*)data);
  }
  return n;
}
__declspec(dllexport) int __cdecl scePadReadState(int handle, void* data) {
  Sony();
  if (!g_read_state) return -1;
  int r = g_read_state(handle, data);
  if (data) {
    Fix((uint8_t*)data);
    if (r < 0 && ((uint8_t*)data)[76]) r = 0;
  }
  return r;
}
// ScePadVibrationParam: motor grande, motor pequeño
__declspec(dllexport) int __cdecl scePadSetVibration(int handle, const void* param) {
  Sony();
  if (param) {
    const uint8_t* v = (const uint8_t*)param;
    g_vib_big = v[0];
    g_vib_small = v[1];
    int strong = std::max(v[0], v[1]);
    if (strong > 110) {
      g_last_hit = GetTickCount64();
      g_hit_strength = 1 + strong * 8 / 256;
    }
    g_vibes++;
  }
  int r = g_set_vib ? g_set_vib(handle, param) : -1;
  return g_sony_sees_pad ? r : 0;
}
// ScePadLightBarParam: r, g, b
__declspec(dllexport) int __cdecl scePadSetLightBar(int handle, const void* param) {
  Sony();
  if (param) {
    const uint8_t* c = (const uint8_t*)param;
    g_lr = c[0]; g_lg = c[1]; g_lb = c[2];
  }
  int r = g_set_light ? g_set_light(handle, param) : -1;
  return g_sony_sees_pad ? r : 0;
}
__declspec(dllexport) int __cdecl scePadResetLightBar(int handle) {
  Sony();
  g_lr = 0; g_lg = 60; g_lb = 200;
  int r = g_reset_light ? g_reset_light(handle) : -1;
  return g_sony_sees_pad ? r : 0;
}
__declspec(dllexport) int __cdecl scePadGetControllerType(int handle, void* out) {
  Sony();
  int r = g_get_type ? g_get_type(handle, out) : -1;
  static int logged = 0;
  if (logged++ < 5) Log("scePadGetControllerType -> %d (valor %d)", r, out ? *(int*)out : -999);
  return r;
}
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    DisableThreadLibraryCalls(inst);
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(inst, path, MAX_PATH);
    g_dir = path;
    g_dir = g_dir.substr(0, g_dir.find_last_of(L"\\/"));
    g_cfg.triggers = IniInt(L"adaptive_triggers", 1) != 0;
    g_cfg.direct = IniInt(L"direct_input", 1) != 0;
    g_cfg.intensity = std::max(0, std::min(100, IniInt(L"trigger_intensity", 100)));
    g_cfg.l2_start = std::max(0, std::min(9, IniInt(L"l2_start", 3)));
    g_cfg.l2_strength = std::max(0, std::min(8, IniInt(L"l2_strength", 4)));
    g_cfg.r2_start = std::max(2, std::min(7, IniInt(L"r2_start", 4)));
    g_cfg.r2_strength = std::max(0, std::min(8, IniInt(L"r2_strength", 5)));
    g_cfg.r2_aim_strength = std::max(0, std::min(8, IniInt(L"r2_aim_strength", 7)));
    g_cfg.hit_freq = std::max(1, std::min(255, IniInt(L"r2_hit_frequency", 28)));
    Log("ReForge DualSense 2 (libScePad): gatillos=%d, lectura directa=%d", g_cfg.triggers, g_cfg.direct);
    CloseHandle(CreateThread(nullptr, 0, PadThread, nullptr, 0, nullptr));
  }
  return TRUE;
}
