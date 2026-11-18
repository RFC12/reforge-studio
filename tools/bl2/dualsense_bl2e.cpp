// ReForge DualSense para juegos de PC con XInput (xinput1_3.dll de reemplazo).
//
// * Lee el DualSense / DualSense Edge directamente por HID (USB o Bluetooth) y lo presenta al juego
//   como mando XInput (jugador 1). Los demás mandos XInput siguen funcionando (jugadores 2-4).
// * Vibración del juego -> motores del DualSense.
// * Gatillos adaptativos: L2 con resistencia de apuntado, R2 con "punto de disparo" y vibración del
//   gatillo cuando el juego hace vibrar el mando al disparar.
// * Barra de luz y LED de jugador.
// * Texturas (iconos de botones): volcado de texturas pequeñas y sustitución por hash (D3D11), para
//   poner los iconos de PlayStation en lugar de los de Xbox.
//
// Configuración: reforge_dualsense.ini junto al .exe del juego.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <hidpi.h>
#include <d3d11.h>
#include <d3d9.h>
#include <wincodec.h>
#include <dxgi.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <mutex>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#pragma comment(lib, "hid.lib")
#pragma comment(lib, "setupapi.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "windowscodecs.lib")

// ------------------------------------------------------------------------------------------ XInput
#define XUSER_MAX_COUNT 4
#define XINPUT_GAMEPAD_DPAD_UP 0x0001
#define XINPUT_GAMEPAD_DPAD_DOWN 0x0002
#define XINPUT_GAMEPAD_DPAD_LEFT 0x0004
#define XINPUT_GAMEPAD_DPAD_RIGHT 0x0008
#define XINPUT_GAMEPAD_START 0x0010
#define XINPUT_GAMEPAD_BACK 0x0020
#define XINPUT_GAMEPAD_LEFT_THUMB 0x0040
#define XINPUT_GAMEPAD_RIGHT_THUMB 0x0080
#define XINPUT_GAMEPAD_LEFT_SHOULDER 0x0100
#define XINPUT_GAMEPAD_RIGHT_SHOULDER 0x0200
#define XINPUT_GAMEPAD_GUIDE 0x0400
#define XINPUT_GAMEPAD_A 0x1000
#define XINPUT_GAMEPAD_B 0x2000
#define XINPUT_GAMEPAD_X 0x4000
#define XINPUT_GAMEPAD_Y 0x8000

struct XINPUT_GAMEPAD {
  WORD wButtons;
  BYTE bLeftTrigger;
  BYTE bRightTrigger;
  SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY;
};
struct XINPUT_STATE {
  DWORD dwPacketNumber;
  XINPUT_GAMEPAD Gamepad;
};
struct XINPUT_VIBRATION {
  WORD wLeftMotorSpeed;
  WORD wRightMotorSpeed;
};
struct XINPUT_CAPABILITIES {
  BYTE Type, SubType;
  WORD Flags;
  XINPUT_GAMEPAD Gamepad;
  XINPUT_VIBRATION Vibration;
};
struct XINPUT_BATTERY_INFORMATION {
  BYTE BatteryType, BatteryLevel;
};
struct XINPUT_KEYSTROKE {
  WORD VirtualKey;
  WCHAR Unicode;
  WORD Flags;
  BYTE UserIndex, HidCode;
};

namespace {

// ------------------------------------------------------------------------------------- utilidades
std::wstring g_dir;  // carpeta del .exe del juego
FILE* g_log = nullptr;
std::mutex g_log_mutex;

void Log(const char* fmt, ...) {
  std::lock_guard<std::mutex> l(g_log_mutex);
  if (!g_log) {
    std::wstring p = g_dir + L"\\reforge_dualsense.log";
    g_log = _wfopen(p.c_str(), L"w");
    if (!g_log) return;
  }
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
  std::wstring p = g_dir + L"\\reforge_dualsense.ini";
  return (int)GetPrivateProfileIntW(L"dualsense", key, def, p.c_str());
}

struct Config {
  bool enabled = true;
  bool triggers = true;
  bool rumble = true;
  int intensity = 100;      // 0..100
  int l2_start = 3;         // 0..9: dónde empieza la resistencia de apuntado
  int l2_strength = 3;      // 1..8
  int r2_start = 4;         // punto de disparo (2..7)
  int r2_strength = 6;      // 1..8
  int r2_fire_freq = 32;    // Hz de la vibración del gatillo al disparar
  int lightbar_r = 0, lightbar_g = 80, lightbar_b = 255;
  int player_led = 1;
  bool lightbar_react = true;
  bool always_connected = true;  // el puesto 1 siempre aparece conectado
  bool guard_hooks = true;  // deshace interceptaciones de otros programas (Steam Input) sobre esta DLL
  bool others = false;      // otros mandos XInput como jugadores 2-4 (apagado: evita doble entrada con Steam Input)
  bool tex_dump = false;
  bool tex_swap = true;
  int fps_limit = 0;        // 0 = sin límite
  bool d3d9 = false;
  int hd_max_mb = 512;     // memoria máxima para texturas HD (DirectX 9)        // ganchos de texturas DirectX 9
  bool d3d11 = true;        // ganchos D3D11 (texturas, FPS); 0 en juegos DirectX 9
  bool perf_stats = true;
} g_cfg;

void LoadConfig() {
  g_cfg.enabled = IniInt(L"enabled", 1) != 0;
  g_cfg.triggers = IniInt(L"adaptive_triggers", 1) != 0;
  g_cfg.rumble = IniInt(L"rumble", 1) != 0;
  g_cfg.intensity = std::max(0, std::min(100, IniInt(L"trigger_intensity", 100)));
  g_cfg.l2_start = std::max(0, std::min(9, IniInt(L"l2_start", 3)));
  g_cfg.l2_strength = std::max(1, std::min(8, IniInt(L"l2_strength", 3)));
  g_cfg.r2_start = std::max(2, std::min(7, IniInt(L"r2_start", 4)));
  g_cfg.r2_strength = std::max(1, std::min(8, IniInt(L"r2_strength", 6)));
  g_cfg.r2_fire_freq = std::max(1, std::min(255, IniInt(L"r2_fire_frequency", 32)));
  g_cfg.lightbar_r = IniInt(L"lightbar_r", 0) & 255;
  g_cfg.lightbar_g = IniInt(L"lightbar_g", 80) & 255;
  g_cfg.lightbar_b = IniInt(L"lightbar_b", 255) & 255;
  g_cfg.player_led = IniInt(L"player_led", 1);
  g_cfg.lightbar_react = IniInt(L"lightbar_react", 1) != 0;
  g_cfg.others = IniInt(L"other_controllers", 0) != 0;
  g_cfg.always_connected = IniInt(L"always_connected", 1) != 0;
  g_cfg.guard_hooks = IniInt(L"guard_hooks", 1) != 0;
  g_cfg.tex_dump = IniInt(L"texture_dump", 0) != 0;
  g_cfg.tex_swap = IniInt(L"texture_swap", 1) != 0;
  g_cfg.d3d11 = IniInt(L"d3d11_hooks", 1) != 0;
  g_cfg.d3d9 = IniInt(L"d3d9_hooks", 0) != 0;
  g_cfg.hd_max_mb = std::max(0, std::min(3000, IniInt(L"hd_max_mb", 512)));
  g_cfg.fps_limit = std::max(0, std::min(1000, IniInt(L"fps_limit", 0)));
  g_cfg.perf_stats = IniInt(L"performance_log", 1) != 0;
}

// --------------------------------------------------------------------------------- XInput real
using PFN_GetState = DWORD(WINAPI*)(DWORD, XINPUT_STATE*);
using PFN_SetState = DWORD(WINAPI*)(DWORD, XINPUT_VIBRATION*);
using PFN_GetCaps = DWORD(WINAPI*)(DWORD, DWORD, XINPUT_CAPABILITIES*);
using PFN_Enable = void(WINAPI*)(BOOL);
using PFN_GetGuids = DWORD(WINAPI*)(DWORD, GUID*, GUID*);
using PFN_GetBattery = DWORD(WINAPI*)(DWORD, BYTE, XINPUT_BATTERY_INFORMATION*);
using PFN_GetKeystroke = DWORD(WINAPI*)(DWORD, DWORD, XINPUT_KEYSTROKE*);

struct Real {
  HMODULE mod = nullptr;
  PFN_GetState GetState = nullptr, GetStateEx = nullptr;
  PFN_SetState SetState = nullptr;
  PFN_GetCaps GetCaps = nullptr;
  PFN_Enable Enable = nullptr;
  PFN_GetGuids GetGuids = nullptr;
  PFN_GetBattery GetBattery = nullptr;
  PFN_GetKeystroke GetKeystroke = nullptr;
} g_real;
INIT_ONCE g_real_once = INIT_ONCE_STATIC_INIT;

BOOL CALLBACK LoadReal(PINIT_ONCE, PVOID, PVOID*) {
  wchar_t sys[MAX_PATH];
  GetSystemDirectoryW(sys, MAX_PATH);
  for (const wchar_t* n : {L"\\xinput1_3.dll", L"\\xinput1_4.dll", L"\\xinput9_1_0.dll"}) {
    std::wstring p = std::wstring(sys) + n;
    g_real.mod = LoadLibraryW(p.c_str());
    if (g_real.mod) break;
  }
  if (!g_real.mod) return TRUE;
  auto m = g_real.mod;
  g_real.GetState = (PFN_GetState)GetProcAddress(m, "XInputGetState");
  g_real.GetStateEx = (PFN_GetState)GetProcAddress(m, (LPCSTR)100);
  g_real.SetState = (PFN_SetState)GetProcAddress(m, "XInputSetState");
  g_real.GetCaps = (PFN_GetCaps)GetProcAddress(m, "XInputGetCapabilities");
  g_real.Enable = (PFN_Enable)GetProcAddress(m, "XInputEnable");
  g_real.GetGuids = (PFN_GetGuids)GetProcAddress(m, "XInputGetDSoundAudioDeviceGuids");
  g_real.GetBattery = (PFN_GetBattery)GetProcAddress(m, "XInputGetBatteryInformation");
  g_real.GetKeystroke = (PFN_GetKeystroke)GetProcAddress(m, "XInputGetKeystroke");
  return TRUE;
}
const Real& R() {
  InitOnceExecuteOnce(&g_real_once, LoadReal, nullptr, nullptr);
  return g_real;
}

// ------------------------------------------------------------------------------------- DualSense
uint32_t Crc32(const uint8_t* d, size_t n, uint32_t crc = 0xFFFFFFFF) {
  for (size_t i = 0; i < n; ++i) {
    crc ^= d[i];
    for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
  }
  return crc;
}

// Efectos de gatillo (codificación documentada por Nielk1 / comunidad de DualSense).
using Effect11 = std::array<uint8_t, 11>;

Effect11 EffOff() {
  Effect11 e{};
  e[0] = 0x05;
  return e;
}
Effect11 EffFeedback(int position, int strength) {
  if (strength <= 0) return EffOff();
  Effect11 e{};
  uint32_t force = (uint32_t)((strength - 1) & 7), zones = 0;
  uint16_t active = 0;
  for (int i = position; i < 10; ++i) {
    zones |= force << (3 * i);
    active |= (uint16_t)(1 << i);
  }
  e[0] = 0x21;
  e[1] = active & 0xFF;
  e[2] = active >> 8;
  e[3] = zones & 0xFF;
  e[4] = (zones >> 8) & 0xFF;
  e[5] = (zones >> 16) & 0xFF;
  e[6] = (zones >> 24) & 0xFF;
  return e;
}
Effect11 EffWeapon(int start, int end, int strength) {
  if (strength <= 0) return EffOff();
  Effect11 e{};
  uint16_t zones = (uint16_t)((1 << start) | (1 << end));
  e[0] = 0x25;
  e[1] = zones & 0xFF;
  e[2] = zones >> 8;
  e[3] = (uint8_t)((strength - 1) & 7);
  return e;
}
Effect11 EffVibration(int position, int amplitude, int frequency) {
  if (amplitude <= 0 || frequency <= 0) return EffOff();
  Effect11 e{};
  uint32_t amp = (uint32_t)((amplitude - 1) & 7), zones = 0;
  uint16_t active = 0;
  for (int i = position; i < 10; ++i) {
    zones |= amp << (3 * i);
    active |= (uint16_t)(1 << i);
  }
  e[0] = 0x26;
  e[1] = active & 0xFF;
  e[2] = active >> 8;
  e[3] = zones & 0xFF;
  e[4] = (zones >> 8) & 0xFF;
  e[5] = (zones >> 16) & 0xFF;
  e[6] = (zones >> 24) & 0xFF;
  e[9] = (uint8_t)frequency;
  return e;
}
int Scale(int strength) {  // intensidad global
  if (strength <= 0) return 0;
  int s = (strength * g_cfg.intensity + 50) / 100;
  return std::max(1, std::min(8, s));
}

struct DsState {
  std::atomic<bool> connected{false};
  std::mutex m;
  XINPUT_STATE state{};
  uint16_t buttons_ex = 0;  // incluye GUIDE
  // salida deseada
  uint8_t rumble_l = 0, rumble_r = 0;
  ULONGLONG last_fire = 0;
  std::atomic<bool> dirty{true};
} g_ds;

std::atomic<int> g_battery{10};
std::atomic<unsigned> g_rumble_calls{0}, g_rumble_max{0}, g_fire_events{0}, g_reads{0};
std::atomic<bool> g_real_pad0{false};  // hay un mando XInput real en el puesto 1 (p. ej. adaptador Magic NS 2)
std::atomic<bool> g_charging{false};

struct Device {
  HANDLE h = INVALID_HANDLE_VALUE;   // lectura
  HANDLE hw = INVALID_HANDLE_VALUE;  // escritura (handle aparte: cancelar una escritura no toca la lectura)
  bool bt = false;
  USHORT in_len = 0, out_len = 0;
  uint8_t seq = 0;
};

bool OpenDualSense(Device& d) {
  GUID hid;
  HidD_GetHidGuid(&hid);
  HDEVINFO set = SetupDiGetClassDevsW(&hid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
  if (set == INVALID_HANDLE_VALUE) return false;
  bool found = false;
  SP_DEVICE_INTERFACE_DATA ifd{sizeof(ifd)};
  for (DWORD i = 0; !found && SetupDiEnumDeviceInterfaces(set, nullptr, &hid, i, &ifd); ++i) {
    DWORD need = 0;
    SetupDiGetDeviceInterfaceDetailW(set, &ifd, nullptr, 0, &need, nullptr);
    std::vector<uint8_t> buf(need);
    auto* det = (SP_DEVICE_INTERFACE_DETAIL_DATA_W*)buf.data();
    det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
    if (!SetupDiGetDeviceInterfaceDetailW(set, &ifd, det, need, nullptr, nullptr)) continue;
    HANDLE h = CreateFileW(det->DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
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
        d.in_len = caps.InputReportByteLength;
        d.out_len = caps.OutputReportByteLength;
        d.bt = caps.InputReportByteLength != 64;
        found = true;
        Log("DualSense %s encontrado (PID %04X, entrada %u, salida %u)", d.bt ? "Bluetooth" : "USB", at.ProductID,
            d.in_len, d.out_len);
        if (d.bt) {  // leer la calibración activa el modo de informes completos (0x31)
          uint8_t feat[64] = {0x05};
          HidD_GetFeature(h, feat, 41);
        }
        break;
      }
    }
    CloseHandle(h);
  }
  SetupDiDestroyDeviceInfoList(set);
  return found;
}

bool WriteOut(Device& d, const uint8_t* rep, DWORD len) {
  OVERLAPPED ov{};
  ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  DWORD w = 0;
  BOOL ok = WriteFile(d.hw, rep, len, &w, &ov);
  if (!ok && GetLastError() == ERROR_IO_PENDING) {
    if (WaitForSingleObject(ov.hEvent, 200) == WAIT_OBJECT_0) {
      ok = GetOverlappedResult(d.hw, &ov, &w, FALSE);
    } else {
      CancelIoEx(d.hw, &ov);
      GetOverlappedResult(d.hw, &ov, &w, TRUE);  // esperar a que se cancele antes de liberar ov
      ok = FALSE;
    }
  }
  CloseHandle(ov.hEvent);
  static std::atomic<int> logged{0};
  if (!ok && logged++ < 5) Log("Envío al DualSense falló (error %lu)", GetLastError());
  if (ok && logged == 0) {
    logged = 100;
    Log("Envío al DualSense correcto (%lu bytes): gatillos, vibración y luz activos", len);
  }
  return ok != FALSE;
}

void SendOutput(Device& d, const Effect11& l2, const Effect11& r2, uint8_t ml, uint8_t mr, bool leds, uint8_t lr, uint8_t lg, uint8_t lb) {
  uint8_t c[47] = {};
  c[0] = 0x01 | 0x02 | 0x04 | 0x08;  // vibración compatible + selección hápticos + gatillo R + gatillo L
  c[1] = leds ? (0x04 | 0x10) : 0;   // barra de luz + LED de jugador
  c[2] = mr;                          // motor derecho (alta frecuencia)
  c[3] = ml;                          // motor izquierdo (baja frecuencia)
  memcpy(c + 10, r2.data(), 11);
  memcpy(c + 21, l2.data(), 11);
  c[38] = 0x04 | (leds ? 0x02 : 0);  // vibración compatible v2 (+ configuración de la barra de luz)
  if (leds) {
    c[41] = 0x02;
    c[42] = 0x00;
    static const uint8_t players[] = {0x00, 0x04, 0x0A, 0x15, 0x1B};
    c[43] = players[std::max(0, std::min(4, g_cfg.player_led))];
    c[44] = lr;
    c[45] = lg;
    c[46] = lb;
  }
  if (!d.bt) {
    uint8_t rep[64] = {};
    rep[0] = 0x02;
    memcpy(rep + 1, c, sizeof(c));
    WriteOut(d, rep, std::max<DWORD>(48, d.out_len));
  } else {
    uint8_t rep[78] = {};
    rep[0] = 0x31;
    rep[1] = (uint8_t)(d.seq << 4);
    d.seq = (d.seq + 1) & 15;
    rep[2] = 0x10;
    memcpy(rep + 3, c, sizeof(c));
    uint8_t seed = 0xA2;
    uint32_t crc = Crc32(&seed, 1);
    crc = ~Crc32(rep, 74, crc);
    memcpy(rep + 74, &crc, 4);
    WriteOut(d, rep, 78);
  }
}

SHORT Axis(uint8_t v, bool invert) {
  int x = ((int)v - 128) * 257;
  if (invert) x = -x - 1;
  return (SHORT)std::max(-32768, std::min(32767, x));
}

void Parse(const uint8_t* p, bool simple) {
  XINPUT_GAMEPAD g{};
  uint8_t b0, b1, b2, l2, r2;
  if (simple) {  // Bluetooth antes de activar el modo completo
    b0 = p[4];
    b1 = p[5];
    b2 = p[6];
    l2 = p[7];
    r2 = p[8];
  } else {
    l2 = p[4];
    r2 = p[5];
    b0 = p[7];
    b1 = p[8];
    b2 = p[9];
  }
  g.sThumbLX = Axis(p[0], false);
  g.sThumbLY = Axis(p[1], true);
  g.sThumbRX = Axis(p[2], false);
  g.sThumbRY = Axis(p[3], true);
  g.bLeftTrigger = l2;
  g.bRightTrigger = r2;
  WORD w = 0;
  static const WORD hat[9] = {
      XINPUT_GAMEPAD_DPAD_UP,
      XINPUT_GAMEPAD_DPAD_UP | XINPUT_GAMEPAD_DPAD_RIGHT,
      XINPUT_GAMEPAD_DPAD_RIGHT,
      XINPUT_GAMEPAD_DPAD_DOWN | XINPUT_GAMEPAD_DPAD_RIGHT,
      XINPUT_GAMEPAD_DPAD_DOWN,
      XINPUT_GAMEPAD_DPAD_DOWN | XINPUT_GAMEPAD_DPAD_LEFT,
      XINPUT_GAMEPAD_DPAD_LEFT,
      XINPUT_GAMEPAD_DPAD_UP | XINPUT_GAMEPAD_DPAD_LEFT,
      0};
  w |= hat[std::min(8, b0 & 0x0F)];
  if (b0 & 0x10) w |= XINPUT_GAMEPAD_X;  // cuadrado
  if (b0 & 0x20) w |= XINPUT_GAMEPAD_A;  // cruz
  if (b0 & 0x40) w |= XINPUT_GAMEPAD_B;  // círculo
  if (b0 & 0x80) w |= XINPUT_GAMEPAD_Y;  // triángulo
  if (b1 & 0x01) w |= XINPUT_GAMEPAD_LEFT_SHOULDER;
  if (b1 & 0x02) w |= XINPUT_GAMEPAD_RIGHT_SHOULDER;
  if (b1 & 0x10) w |= XINPUT_GAMEPAD_BACK;   // Create
  if (b1 & 0x20) w |= XINPUT_GAMEPAD_START;  // Options
  if (b1 & 0x40) w |= XINPUT_GAMEPAD_LEFT_THUMB;
  if (b1 & 0x80) w |= XINPUT_GAMEPAD_RIGHT_THUMB;
  if (b2 & 0x02) w |= XINPUT_GAMEPAD_BACK;   // clic del panel táctil = Select
  g.wButtons = w;
  if (!simple) {
    uint8_t bat = p[52];
    g_battery = bat & 0x0F;          // 0..10
    g_charging = (bat >> 4) == 1;
  }
  std::lock_guard<std::mutex> l(g_ds.m);
  if (memcmp(&g, &g_ds.state.Gamepad, sizeof(g)) != 0 || ((b2 & 1) != 0) != ((g_ds.buttons_ex & XINPUT_GAMEPAD_GUIDE) != 0)) {
    g_ds.state.Gamepad = g;
    g_ds.state.dwPacketNumber++;
  }
  g_ds.buttons_ex = w | ((b2 & 0x01) ? XINPUT_GAMEPAD_GUIDE : 0);
}

DWORD WINAPI HidThread(void*) {
  Sleep(300);
  for (;;) {
    Device d;
    if (!g_cfg.enabled || !OpenDualSense(d)) {
      g_ds.connected = false;
      Sleep(2000);
      continue;
    }
    g_ds.connected = true;
    g_ds.dirty = true;
    std::vector<uint8_t> buf(std::max<int>(d.in_len, 80));
    OVERLAPPED ov{};
    ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    Effect11 last_l2{}, last_r2{};
    uint8_t last_ml = 255, last_mr = 255;
    ULONGLONG last_send = 0;
    bool leds_sent = false;
    int fails = 0;
    uint8_t last_lr = 0, last_lg = 0, last_lb = 0;
    bool was_firing = false;
    ULONGLONG last_stats = GetTickCount64();
    for (;;) {
      DWORD got = 0;
      ResetEvent(ov.hEvent);
      BOOL ok = ReadFile(d.h, buf.data(), d.in_len, &got, &ov);
      if (!ok && GetLastError() == ERROR_IO_PENDING) {
        DWORD wr = WaitForSingleObject(ov.hEvent, 100);
        if (wr == WAIT_OBJECT_0) {
          ok = GetOverlappedResult(d.h, &ov, &got, FALSE);
        } else {
          CancelIoEx(d.h, &ov);
          GetOverlappedResult(d.h, &ov, &got, TRUE);
          ok = TRUE;
          got = 0;
        }
      }
      if (!ok) {
        DWORD err = GetLastError();
        if (err == ERROR_OPERATION_ABORTED && ++fails < 20) continue;
        if (++fails < 5 && err != ERROR_DEVICE_NOT_CONNECTED && err != ERROR_INVALID_HANDLE) {
          Sleep(20);
          continue;
        }
        Log("Lectura del DualSense falló (error %lu)", err);
        break;  // desconectado
      }
      fails = 0;
      if (got > 10) {
        if (buf[0] == 0x01 && !d.bt) Parse(buf.data() + 1, false);
        else if (buf[0] == 0x31) Parse(buf.data() + 2, false);
        else if (buf[0] == 0x01) Parse(buf.data() + 1, true);
      }
      // salida: gatillos + vibración
      ULONGLONG now = GetTickCount64();
      uint8_t ml, mr, r2v;
      ULONGLONG fire;
      {
        std::lock_guard<std::mutex> l(g_ds.m);
        ml = g_ds.rumble_l;
        mr = g_ds.rumble_r;
        fire = g_ds.last_fire;
        r2v = g_ds.state.Gamepad.bRightTrigger;
      }
      Effect11 l2 = EffOff(), r2 = EffOff();
      if (g_cfg.triggers && g_cfg.intensity > 0) {
        l2 = EffFeedback(g_cfg.l2_start, Scale(g_cfg.l2_strength));
        bool firing = now - fire < 180 && r2v > 40;
        if (firing && !was_firing) g_fire_events++;
        was_firing = firing;
        if (firing) {
          int amp = std::max(3, std::min(8, 1 + (std::max(ml, mr) * 8) / 255));
          r2 = EffVibration(std::max(0, g_cfg.r2_start - 1), Scale(amp), g_cfg.r2_fire_freq);
        } else {
          r2 = EffWeapon(g_cfg.r2_start, std::min(8, g_cfg.r2_start + 2), Scale(g_cfg.r2_strength));
        }
      }
      // barra de luz: color elegido; destello naranja con golpes fuertes (explosiones, daño);
      // rojo pulsante con batería baja
      uint8_t lr = (uint8_t)g_cfg.lightbar_r, lg = (uint8_t)g_cfg.lightbar_g, lb = (uint8_t)g_cfg.lightbar_b;
      if (now - last_stats > 30000) {
        last_stats = now;
        Log("Mando (%s): lecturas del juego %u, vibraciones %u (máx %u), disparos con gatillo vibrando %u, batería %d/10",
            g_ds.connected ? "DualSense directo" : (g_real_pad0 ? "mando XInput / adaptador" : "ninguno"),
            (unsigned)g_reads, (unsigned)g_rumble_calls, (unsigned)g_rumble_max, (unsigned)g_fire_events,
            (int)g_battery);
      }
      if (g_cfg.lightbar_react && ml > 150) {
        lr = 255; lg = 90; lb = 0;
      } else if (g_battery <= 1 && !g_charging) {
        bool on = (now / 600) & 1;
        lr = on ? 255 : 40; lg = 0; lb = 0;
      }
      if (!g_cfg.rumble) ml = mr = 0;
      bool color_changed = lr != last_lr || lg != last_lg || lb != last_lb;
      if (l2 != last_l2 || r2 != last_r2 || ml != last_ml || mr != last_mr || color_changed || now - last_send > 2000 || !leds_sent) {
        SendOutput(d, l2, r2, ml, mr, !leds_sent || color_changed || now - last_send > 2000, lr, lg, lb);
        last_lr = lr; last_lg = lg; last_lb = lb;
        leds_sent = true;
        last_l2 = l2;
        last_r2 = r2;
        last_ml = ml;
        last_mr = mr;
        last_send = now;
      }
    }
    CloseHandle(ov.hEvent);
    if (d.hw != d.h) CloseHandle(d.hw);
    CloseHandle(d.h);
    g_ds.connected = false;
    Log("DualSense desconectado");
    Sleep(500);
  }
}

// ------------------------------------------------------------------------------- texturas (D3D11)
using PFN_CreateTexture2D = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, const D3D11_TEXTURE2D_DESC*,
                                                         const D3D11_SUBRESOURCE_DATA*, ID3D11Texture2D**);
using PFN_CreateSRV = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, ID3D11Resource*,
                                                  const D3D11_SHADER_RESOURCE_VIEW_DESC*,
                                                  ID3D11ShaderResourceView**);
PFN_CreateTexture2D g_orig_tex = nullptr;
PFN_CreateSRV g_orig_srv = nullptr;
std::atomic<uint64_t> g_n_create_init{0}, g_n_create_empty{0}, g_n_update{0};
std::mutex g_tex_m;
std::set<uint64_t> g_dumped;
std::unordered_map<ID3D11Resource*, DXGI_FORMAT> g_replaced;
std::unordered_map<uint64_t, std::wstring> g_swaps;  // hash -> archivo .dds
std::vector<std::pair<uint64_t, std::wstring>> g_raw_swaps_pending;

// solo formatos en los que puede haber iconos de interfaz (con color y/o transparencia)
bool DumpWorthy(DXGI_FORMAT f) {
  switch (f) {
    case DXGI_FORMAT_BC1_UNORM: case DXGI_FORMAT_BC1_UNORM_SRGB: case DXGI_FORMAT_BC2_UNORM:
    case DXGI_FORMAT_BC2_UNORM_SRGB: case DXGI_FORMAT_BC3_UNORM: case DXGI_FORMAT_BC3_UNORM_SRGB:
    case DXGI_FORMAT_BC7_UNORM: case DXGI_FORMAT_BC7_UNORM_SRGB: case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    // máscaras de un canal: los iconos de botones suelen ser una forma blanca que el juego tiñe de color
    case DXGI_FORMAT_BC4_UNORM: case DXGI_FORMAT_R8_UNORM: case DXGI_FORMAT_A8_UNORM:
      return true;
    default:
      return false;
  }
}

uint64_t Fnv64(const uint8_t* p, size_t n) {
  uint64_t h = 1469598103934665603ull;
  for (size_t i = 0; i < n; ++i) {
    h ^= p[i];
    h *= 1099511628211ull;
  }
  return h;
}

UINT BitsPerPixel(DXGI_FORMAT f) {
  switch (f) {
    case DXGI_FORMAT_BC1_UNORM: case DXGI_FORMAT_BC1_UNORM_SRGB: case DXGI_FORMAT_BC4_UNORM:
    case DXGI_FORMAT_BC4_SNORM: case DXGI_FORMAT_BC1_TYPELESS: case DXGI_FORMAT_BC4_TYPELESS:
      return 4;
    case DXGI_FORMAT_BC2_UNORM: case DXGI_FORMAT_BC2_UNORM_SRGB: case DXGI_FORMAT_BC3_UNORM:
    case DXGI_FORMAT_BC3_UNORM_SRGB: case DXGI_FORMAT_BC5_UNORM: case DXGI_FORMAT_BC5_SNORM:
    case DXGI_FORMAT_BC7_UNORM: case DXGI_FORMAT_BC7_UNORM_SRGB: case DXGI_FORMAT_BC6H_UF16:
    case DXGI_FORMAT_BC6H_SF16: case DXGI_FORMAT_BC2_TYPELESS: case DXGI_FORMAT_BC3_TYPELESS:
    case DXGI_FORMAT_BC5_TYPELESS: case DXGI_FORMAT_BC7_TYPELESS: case DXGI_FORMAT_BC6H_TYPELESS:
      return 8;
    case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: case DXGI_FORMAT_B8G8R8A8_UNORM:
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: case DXGI_FORMAT_R8G8B8A8_TYPELESS: case DXGI_FORMAT_B8G8R8A8_TYPELESS:
      return 32;
    case DXGI_FORMAT_R8_UNORM: case DXGI_FORMAT_A8_UNORM:
      return 8 | 0x100;  // 1 byte por píxel (marcado para distinguir de BC de 8)
    default:
      return 0;
  }
}

size_t Mip0Size(const D3D11_TEXTURE2D_DESC* d, UINT* pitch_out, UINT* rows_out) {
  UINT bpp = BitsPerPixel(d->Format);
  if (!bpp) return 0;
  bool bc = (d->Format >= DXGI_FORMAT_BC1_TYPELESS && d->Format <= DXGI_FORMAT_BC5_SNORM) ||
            (d->Format >= DXGI_FORMAT_BC6H_TYPELESS && d->Format <= DXGI_FORMAT_BC7_UNORM_SRGB);
  UINT pitch, rows;
  if (bc) {
    pitch = std::max(1u, (d->Width + 3) / 4) * (bpp == 4 ? 8 : 16);
    rows = std::max(1u, (d->Height + 3) / 4);
  } else {
    pitch = d->Width * ((bpp & 0xFF) / 8);
    rows = d->Height;
  }
  *pitch_out = pitch;
  *rows_out = rows;
  return (size_t)pitch * rows;
}

uint64_t HashMip0(const D3D11_TEXTURE2D_DESC* d, const D3D11_SUBRESOURCE_DATA* s, std::vector<uint8_t>* copy) {
  UINT pitch, rows;
  size_t sz = Mip0Size(d, &pitch, &rows);
  if (!sz || !s || !s[0].pSysMem) return 0;
  std::vector<uint8_t> tmp;
  tmp.resize(sz);
  for (UINT r = 0; r < rows; ++r)
    memcpy(tmp.data() + (size_t)r * pitch, (const uint8_t*)s[0].pSysMem + (size_t)r * s[0].SysMemPitch, pitch);
  uint64_t h = Fnv64(tmp.data(), tmp.size()) ^ ((uint64_t)d->Width << 48) ^ ((uint64_t)d->Height << 32) ^ d->Format;
  if (copy) *copy = std::move(tmp);
  return h;
}

void WriteDump(uint64_t h, const D3D11_TEXTURE2D_DESC* d, const std::vector<uint8_t>& data) {
  std::wstring dir = g_dir + L"\\reforge_textures\\dump";
  CreateDirectoryW((g_dir + L"\\reforge_textures").c_str(), nullptr);
  CreateDirectoryW(dir.c_str(), nullptr);
  wchar_t name[64];
  swprintf(name, 64, L"\\%016llx.rftx", (unsigned long long)h);
  FILE* f = _wfopen((dir + name).c_str(), L"wb");
  if (!f) return;
  char hdr[96];
  int n = snprintf(hdr, sizeof(hdr), "RFTX2 %u %u %u %u %u\n", (unsigned)d->Format, d->Width, d->Height, d->MipLevels,
                   d->ArraySize);
  fwrite(hdr, 1, n, f);
  fwrite(data.data(), 1, data.size(), f);
  fclose(f);
}

// Sustituto: archivo DDS (DX10) con la misma o distinta codificación; se crea con sus propios datos.
bool LoadSwap(const std::wstring& path, D3D11_TEXTURE2D_DESC* desc, std::vector<uint8_t>* blob,
              std::vector<D3D11_SUBRESOURCE_DATA>* subs) {
  FILE* f = _wfopen(path.c_str(), L"rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  blob->resize(n);
  fread(blob->data(), 1, n, f);
  fclose(f);
  const uint8_t* p = blob->data();
  if (n < 148 || memcmp(p, "DDS ", 4) != 0 || memcmp(p + 84, "DX10", 4) != 0) return false;
  UINT h = *(const UINT*)(p + 12), w = *(const UINT*)(p + 16), mips = std::max(1u, *(const UINT*)(p + 28));
  DXGI_FORMAT fmt = *(const DXGI_FORMAT*)(p + 128);
  D3D11_TEXTURE2D_DESC nd = *desc;
  nd.Width = w;
  nd.Height = h;
  nd.MipLevels = mips;
  nd.ArraySize = 1;
  nd.Format = fmt;
  size_t off = 148;
  subs->clear();
  for (UINT m = 0; m < mips; ++m) {
    D3D11_TEXTURE2D_DESC md = nd;
    md.Width = std::max(1u, w >> m);
    md.Height = std::max(1u, h >> m);
    UINT pitch, rows;
    size_t sz = Mip0Size(&md, &pitch, &rows);
    if (!sz || off + sz > (size_t)n) return false;
    subs->push_back({p + off, pitch, 0});
    off += sz;
  }
  *desc = nd;
  return true;
}

// Imagen PNG/JPG de un pak, ya decodificada a RGBA (se hace al arrancar, fuera del hilo del juego).
struct PakImage {
  UINT w = 0, h = 0;
  std::vector<uint8_t> rgba;
};
std::unordered_map<uint64_t, PakImage> g_pak_images;
bool g_lazy_paks = false;                               // D3D9: las imágenes se decodifican al usarse
std::unordered_map<uint64_t, std::wstring> g_pak_files;  // huella -> PNG (modo perezoso)

bool DecodeImageWic(const std::wstring& path, PakImage* out) {
  IWICImagingFactory* f = nullptr;
  if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&f)))) return false;
  bool ok = false;
  IWICBitmapDecoder* dec = nullptr;
  IWICBitmapFrameDecode* fr = nullptr;
  IWICFormatConverter* cv = nullptr;
  if (SUCCEEDED(f->CreateDecoderFromFilename(path.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec)) &&
      SUCCEEDED(dec->GetFrame(0, &fr)) && SUCCEEDED(f->CreateFormatConverter(&cv)) &&
      SUCCEEDED(cv->Initialize(fr, GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0,
                               WICBitmapPaletteTypeCustom)) &&
      SUCCEEDED(cv->GetSize(&out->w, &out->h)) && out->w && out->h && out->w <= 4096 && out->h <= 4096) {
    out->rgba.resize((size_t)out->w * out->h * 4);
    ok = SUCCEEDED(cv->CopyPixels(nullptr, out->w * 4, (UINT)out->rgba.size(), out->rgba.data()));
  }
  if (cv) cv->Release();
  if (fr) fr->Release();
  if (dec) dec->Release();
  f->Release();
  return ok;
}

void ScanSwapFolder(const std::wstring& dir, int* n_dds, int* n_img) {
  WIN32_FIND_DATAW fd;
  HANDLE fh = FindFirstFileW((dir + L"*").c_str(), &fd);
  if (fh == INVALID_HANDLE_VALUE) return;
  do {
    if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
    unsigned long long h = 0;
    if (swscanf(fd.cFileName, L"%16llx", &h) != 1) continue;
    std::wstring name = fd.cFileName, ext = name.substr(name.find_last_of(L'.') + 1);
    for (auto& c : ext) c = towlower(c);
    if (ext == L"dds") {
      g_swaps[h] = dir + name;
      ++*n_dds;
    } else if ((ext == L"png" || ext == L"jpg" || ext == L"jpeg" || ext == L"bmp") && g_lazy_paks) {
      g_pak_files[h] = dir + name;
      ++*n_img;
    } else if (ext == L"png" || ext == L"jpg" || ext == L"jpeg" || ext == L"bmp") {
      PakImage im;
      if (DecodeImageWic(dir + name, &im)) {
        g_pak_images[h] = std::move(im);
        ++*n_img;
      }
    } else if (ext == L"raw") {
      g_raw_swaps_pending.emplace_back(h, dir + name);
    }
  } while (FindNextFileW(fh, &fd));
  FindClose(fh);
}

// Sustituciones: reforge_textures\swap (las que genera ReForge) y cada pak de reforge_paks\<nombre>\
// (activado salvo que su pak.ini diga enabled=0; los paks se aplican por orden alfabético, el último gana).
void LoadSwapIndex() {
  HRESULT co = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  int dds = 0, img = 0, paks = 0;
  ScanSwapFolder(g_dir + L"\\reforge_textures\\swap\\", &dds, &img);
  std::wstring root = g_dir + L"\\reforge_paks\\";
  WIN32_FIND_DATAW fd;
  HANDLE fh = FindFirstFileW((root + L"*").c_str(), &fd);
  std::vector<std::wstring> names;
  if (fh != INVALID_HANDLE_VALUE) {
    do {
      if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && fd.cFileName[0] != L'.') names.push_back(fd.cFileName);
    } while (FindNextFileW(fh, &fd));
    FindClose(fh);
  }
  std::sort(names.begin(), names.end());
  for (auto& n : names) {
    std::wstring dir = root + n + L"\\";
    if (!GetPrivateProfileIntW(L"pak", L"enabled", 1, (dir + L"pak.ini").c_str())) {
      Log("Pak desactivado: %ls", n.c_str());
      continue;
    }
    int d0 = dds, i0 = img;
    ScanSwapFolder(dir, &dds, &img);
    ++paks;
    Log("Pak cargado: %ls (%d imágenes)", n.c_str(), (dds - d0) + (img - i0));
  }
  if (SUCCEEDED(co)) CoUninitialize();
  Log("Texturas de sustitución: %d DDS + %d imágenes de %d paks", dds, img, paks);
}

HRESULT STDMETHODCALLTYPE HookCreateTexture2D(ID3D11Device* dev, const D3D11_TEXTURE2D_DESC* desc,
                                              const D3D11_SUBRESOURCE_DATA* init, ID3D11Texture2D** out) {
  if (init) g_n_create_init++; else g_n_create_empty++;
  if (desc && init && desc->ArraySize >= 1 && desc->Width <= 4096 && desc->Height <= 4096 &&
      (g_cfg.tex_dump || !g_swaps.empty() || !g_pak_images.empty())) {
    std::vector<uint8_t> copy;
    uint64_t h = HashMip0(desc, init, g_cfg.tex_dump ? &copy : nullptr);
    if (h) {
      auto pi = desc->ArraySize == 1 ? g_pak_images.find(h) : g_pak_images.end();
      if (pi != g_pak_images.end()) {
        D3D11_TEXTURE2D_DESC nd = *desc;
        bool srgb = desc->Format == DXGI_FORMAT_BC1_UNORM_SRGB || desc->Format == DXGI_FORMAT_BC2_UNORM_SRGB ||
                    desc->Format == DXGI_FORMAT_BC3_UNORM_SRGB || desc->Format == DXGI_FORMAT_BC7_UNORM_SRGB ||
                    desc->Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB || desc->Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        nd.Format = srgb ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
        nd.Width = pi->second.w;
        nd.Height = pi->second.h;
        nd.MipLevels = 1;
        nd.MiscFlags &= ~D3D11_RESOURCE_MISC_GENERATE_MIPS;
        D3D11_SUBRESOURCE_DATA sd{pi->second.rgba.data(), pi->second.w * 4, 0};
        HRESULT hr = g_orig_tex(dev, &nd, &sd, out);
        if (SUCCEEDED(hr) && out && *out) {
          std::lock_guard<std::mutex> l(g_tex_m);
          g_replaced[*out] = nd.Format;
          static int shown = 0;
          if (shown++ < 100) Log("Pak aplicado: %016llx (%ux%u)", (unsigned long long)h, nd.Width, nd.Height);
          return hr;
        }
      }
      auto it = desc->ArraySize == 1 ? g_swaps.find(h) : g_swaps.end();
      if (it != g_swaps.end()) {
        D3D11_TEXTURE2D_DESC nd = *desc;
        std::vector<uint8_t> blob;
        std::vector<D3D11_SUBRESOURCE_DATA> subs;
        if (LoadSwap(it->second, &nd, &blob, &subs)) {
          HRESULT hr = g_orig_tex(dev, &nd, subs.data(), out);
          if (SUCCEEDED(hr) && out && *out) {
            std::lock_guard<std::mutex> l(g_tex_m);
            g_replaced[*out] = nd.Format;
            return hr;
          }
        }
      } else if (g_cfg.tex_dump && desc->Width <= 4096 && desc->Height <= 4096 && DumpWorthy(desc->Format)) {
        bool fresh;
        {
          std::lock_guard<std::mutex> l(g_tex_m);
          fresh = g_dumped.insert(h).second && g_dumped.size() < 60000;
        }
        if (fresh) WriteDump(h, desc, copy);
      }
    }
  }
  return g_orig_tex(dev, desc, init, out);
}

HRESULT STDMETHODCALLTYPE HookCreateSRV(ID3D11Device* dev, ID3D11Resource* res, const D3D11_SHADER_RESOURCE_VIEW_DESC* desc,
                                        ID3D11ShaderResourceView** out) {
  if (desc && res) {
    DXGI_FORMAT fmt = DXGI_FORMAT_UNKNOWN;
    {
      std::lock_guard<std::mutex> l(g_tex_m);
      auto it = g_replaced.find(res);
      if (it != g_replaced.end()) fmt = it->second;
    }
    if (fmt != DXGI_FORMAT_UNKNOWN && desc->Format != fmt) {
      D3D11_SHADER_RESOURCE_VIEW_DESC nd = *desc;
      nd.Format = fmt;
      if (nd.ViewDimension == D3D11_SRV_DIMENSION_TEXTURE2D) {
        nd.Texture2D.MostDetailedMip = 0;
        nd.Texture2D.MipLevels = (UINT)-1;
      }
      return g_orig_srv(dev, res, &nd, out);
    }
  }
  return g_orig_srv(dev, res, desc, out);
}

// --- subidas posteriores (texturas por streaming: se crean vacías y se rellenan con UpdateSubresource)
using PFN_Update = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, const D3D11_BOX*,
                                             const void*, UINT, UINT);
PFN_Update g_orig_update = nullptr;
std::unordered_map<uint64_t, std::wstring> g_raw_swaps;  // hash de un nivel -> .raw (mismo formato)
std::unordered_map<ID3D11Resource*, uint32_t> g_group;   // textura -> grupo (para enlazar sus niveles)
std::atomic<uint32_t> g_group_next{1};

void HookUpdateImpl(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT sub, const D3D11_BOX* box, const void* src,
                    UINT row_pitch, UINT depth_pitch) {
  g_n_update++;
  if (!src || box || !dst || (!g_cfg.tex_dump && g_raw_swaps.empty())) {
    g_orig_update(ctx, dst, sub, box, src, row_pitch, depth_pitch);
    return;
  }
  D3D11_RESOURCE_DIMENSION dim;
  dst->GetType(&dim);
  if (dim != D3D11_RESOURCE_DIMENSION_TEXTURE2D) {
    g_orig_update(ctx, dst, sub, box, src, row_pitch, depth_pitch);
    return;
  }
  D3D11_TEXTURE2D_DESC td;
  ((ID3D11Texture2D*)dst)->GetDesc(&td);
  UINT mips = std::max(1u, td.MipLevels);
  UINT mip = sub % mips, slice = sub / mips;
  D3D11_TEXTURE2D_DESC md = td;
  md.Width = std::max(1u, td.Width >> mip);
  md.Height = std::max(1u, td.Height >> mip);
  UINT pitch, rows;
  size_t sz = Mip0Size(&md, &pitch, &rows);
  if (!sz || slice != 0 || td.Width > 2048 || td.Height > 2048) {
    g_orig_update(ctx, dst, sub, box, src, row_pitch, depth_pitch);
    return;
  }
  std::vector<uint8_t> tmp(sz);
  for (UINT r = 0; r < rows; ++r)
    memcpy(tmp.data() + (size_t)r * pitch, (const uint8_t*)src + (size_t)r * row_pitch, pitch);
  uint64_t h = Fnv64(tmp.data(), tmp.size()) ^ ((uint64_t)md.Width << 48) ^ ((uint64_t)md.Height << 32) ^ td.Format;
  auto it = g_raw_swaps.find(h);
  if (it != g_raw_swaps.end()) {
    FILE* f = _wfopen(it->second.c_str(), L"rb");
    if (f) {
      std::vector<uint8_t> rep(sz);
      size_t got = fread(rep.data(), 1, sz, f);
      fclose(f);
      if (got == sz) {
        g_orig_update(ctx, dst, sub, box, rep.data(), pitch, depth_pitch);
        return;
      }
    }
  }
  if (g_cfg.tex_dump && td.Width <= 1024 && td.Height <= 1024) {
    uint32_t grp;
    bool fresh;
    {
      std::lock_guard<std::mutex> l(g_tex_m);
      auto gi = g_group.find(dst);
      if (gi == g_group.end()) gi = g_group.emplace(dst, g_group_next++).first;
      grp = gi->second;
      fresh = g_dumped.insert(h).second && g_dumped.size() < 60000;
    }
    if (fresh) {
      std::wstring dir = g_dir + L"\\reforge_textures\\dump_stream";
      CreateDirectoryW((g_dir + L"\\reforge_textures").c_str(), nullptr);
      CreateDirectoryW(dir.c_str(), nullptr);
      wchar_t name[64];
      swprintf(name, 64, L"\\%016llx.rftx", (unsigned long long)h);
      FILE* f = _wfopen((dir + name).c_str(), L"wb");
      if (f) {
        char hdr[128];
        int n = snprintf(hdr, sizeof(hdr), "RFTX3 %u %u %u %u %u %u %u\n", (unsigned)td.Format, md.Width, md.Height,
                         mip, mips, grp, td.Width);
        fwrite(hdr, 1, n, f);
        fwrite(tmp.data(), 1, tmp.size(), f);
        fclose(f);
      }
    }
  }
  g_orig_update(ctx, dst, sub, box, src, row_pitch, depth_pitch);
}
void STDMETHODCALLTYPE HookUpdate(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT sub, const D3D11_BOX* box,
                                  const void* src, UINT row_pitch, UINT depth_pitch) {
  HookUpdateImpl(ctx, dst, sub, box, src, row_pitch, depth_pitch);
}

void LoadRawSwaps() {
  for (auto& p : g_raw_swaps_pending) g_raw_swaps[p.first] = p.second;
  std::wstring dir = g_dir + L"\\reforge_textures\\swap\\";
  WIN32_FIND_DATAW fd;
  HANDLE fh = FindFirstFileW((dir + L"*.raw").c_str(), &fd);
  if (fh == INVALID_HANDLE_VALUE) return;
  do {
    unsigned long long h = 0;
    if (swscanf(fd.cFileName, L"%16llx", &h) == 1) g_raw_swaps[h] = dir + fd.cFileName;
  } while (FindNextFileW(fh, &fd));
  FindClose(fh);
  Log("Niveles de textura de sustitución (streaming): %zu", g_raw_swaps.size());
}

// ------------------------------------------------------------------------------ rendimiento (Present)
// Mide el tiempo de cada fotograma (FPS medio, 1 % bajo, peor fotograma) y, si se pide, limita los FPS
// con precisión (ideal con G-SYNC / FreeSync: unos FPS por debajo de la frecuencia del monitor).
using PFN_Present = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);
PFN_Present g_orig_present = nullptr;
LARGE_INTEGER g_qpf{};
LONGLONG g_last_present = 0, g_next_frame = 0, g_stats_start = 0;
std::vector<float> g_frames;
HANDLE g_timer = nullptr;

void WaitUntil(LONGLONG target) {
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  LONGLONG left = target - now.QuadPart;
  if (left <= 0) return;
  double ms = left * 1000.0 / g_qpf.QuadPart;
  if (ms > 2.0 && g_timer) {  // dormir casi todo con un temporizador de alta resolución
    LARGE_INTEGER due;
    due.QuadPart = -(LONGLONG)((ms - 1.5) * 10000.0);
    SetWaitableTimer(g_timer, &due, 0, nullptr, nullptr, FALSE);
    WaitForSingleObject(g_timer, INFINITE);
  }
  do {  // y el último milisegundo, en espera activa
    YieldProcessor();
    QueryPerformanceCounter(&now);
  } while (now.QuadPart < target);
}

HRESULT STDMETHODCALLTYPE HookPresent(IDXGISwapChain* sc, UINT sync, UINT flags) {
  LARGE_INTEGER now;
  if (g_cfg.fps_limit > 0 && !(flags & DXGI_PRESENT_TEST)) {
    LONGLONG period = g_qpf.QuadPart / g_cfg.fps_limit;
    QueryPerformanceCounter(&now);
    if (g_next_frame == 0 || now.QuadPart - g_next_frame > period * 4) g_next_frame = now.QuadPart;
    WaitUntil(g_next_frame);
    g_next_frame += period;
  }
  HRESULT hr = g_orig_present(sc, sync, flags);
  if (g_cfg.perf_stats && !(flags & DXGI_PRESENT_TEST)) {
    QueryPerformanceCounter(&now);
    if (g_last_present) g_frames.push_back((float)((now.QuadPart - g_last_present) * 1000.0 / g_qpf.QuadPart));
    g_last_present = now.QuadPart;
    if (!g_stats_start) g_stats_start = now.QuadPart;
    if (now.QuadPart - g_stats_start > g_qpf.QuadPart * 30 && g_frames.size() > 30) {
      std::vector<float> f = g_frames;
      double sum = 0;
      for (float x : f) sum += x;
      std::sort(f.begin(), f.end());
      float p99 = f[(size_t)(f.size() * 0.99)], worst = f.back();
      size_t n1 = std::max<size_t>(1, f.size() / 100);
      double low = 0;
      for (size_t i = f.size() - n1; i < f.size(); ++i) low += f[i];
      low /= n1;
      int hitches = 0;
      for (float x : g_frames) hitches += x > 50.0f;
      Log("Rendimiento: %.0f FPS de media, 1%% bajo %.0f FPS, peor fotograma %.1f ms, tirones (>50 ms) %d",
          1000.0 * f.size() / sum, 1000.0 / low, worst, hitches);
      (void)p99;
      g_frames.clear();
      g_stats_start = now.QuadPart;
    }
  }
  return hr;
}

LRESULT CALLBACK DummyWndProc(HWND h, UINT m, WPARAM w, LPARAM l) { return DefWindowProcW(h, m, w, l); }

void HookPresentVtable() {
  if (!g_cfg.perf_stats && g_cfg.fps_limit <= 0) return;
  QueryPerformanceFrequency(&g_qpf);
  g_timer = CreateWaitableTimerExW(nullptr, nullptr, 0x00000002 /*HIGH_RESOLUTION*/, TIMER_ALL_ACCESS);
  if (!g_timer) g_timer = CreateWaitableTimerW(nullptr, FALSE, nullptr);
  WNDCLASSW wc{};
  wc.lpfnWndProc = DummyWndProc;
  wc.hInstance = GetModuleHandleW(nullptr);
  wc.lpszClassName = L"ReForgeDualSenseDummy";
  RegisterClassW(&wc);
  HWND wnd = CreateWindowW(wc.lpszClassName, L"", WS_OVERLAPPEDWINDOW, 0, 0, 8, 8, nullptr, nullptr, wc.hInstance, nullptr);
  DXGI_SWAP_CHAIN_DESC sd{};
  sd.BufferCount = 1;
  sd.BufferDesc.Width = 8;
  sd.BufferDesc.Height = 8;
  sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
  sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
  sd.OutputWindow = wnd;
  sd.SampleDesc.Count = 1;
  sd.Windowed = TRUE;
  IDXGISwapChain* sc = nullptr;
  ID3D11Device* dev = nullptr;
  ID3D11DeviceContext* ctx = nullptr;
  HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
                                             D3D11_SDK_VERSION, &sd, &sc, &dev, nullptr, &ctx);
  if (FAILED(hr) || !sc) {
    Log("Rendimiento: no se pudo crear la cadena de prueba (%08X)", (unsigned)hr);
    return;
  }
  void** vt = *(void***)sc;
  DWORD old;
  if (VirtualProtect(&vt[8], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
    g_orig_present = (PFN_Present)vt[8];
    vt[8] = (void*)&HookPresent;
    VirtualProtect(&vt[8], sizeof(void*), old, &old);
    Log("Rendimiento: medidor listo (límite de FPS: %d)", g_cfg.fps_limit);
  }
  // los objetos de prueba se quedan vivos para que la tabla parcheada no se descargue
}

// --------------------------------------------------------------------- texturas DirectX 9 (juegos antiguos)
// Los juegos D3D9 rellenan sus texturas con LockRect/UnlockRect. Al desbloquear el nivel 0 se calcula su
// huella; si hay una imagen de un pak con esa huella se escribe encima (recodificada al formato de la
// textura: DXT1/DXT3/DXT5/ARGB) antes de que el juego la suba a la gráfica. Los niveles menores de la
// misma textura reciben la imagen reducida.
using PFN_Lock9 = HRESULT(STDMETHODCALLTYPE*)(IDirect3DTexture9*, UINT, D3DLOCKED_RECT*, const RECT*, DWORD);
using PFN_Unlock9 = HRESULT(STDMETHODCALLTYPE*)(IDirect3DTexture9*, UINT);
PFN_Lock9 g_orig_lock9 = nullptr;
PFN_Unlock9 g_orig_unlock9 = nullptr;
struct Locked9 { void* bits; INT pitch; };
std::mutex g_t9_m;
std::unordered_map<uint64_t, Locked9> g_locked9;                         // (textura, nivel) -> memoria
std::unordered_map<IDirect3DTexture9*, std::pair<uint64_t, UINT>> g_swapped9;  // textura -> (huella, ancho)
std::atomic<uint64_t> g_n9_unlock{0}, g_n9_swapped{0};

const D3DFORMAT kDXT1 = (D3DFORMAT)MAKEFOURCC('D', 'X', 'T', '1');
const D3DFORMAT kDXT3 = (D3DFORMAT)MAKEFOURCC('D', 'X', 'T', '3');
const D3DFORMAT kDXT5 = (D3DFORMAT)MAKEFOURCC('D', 'X', 'T', '5');

// tamaño de fila y número de filas de un nivel; 0 si el formato no se maneja
size_t Level9Size(D3DFORMAT f, UINT w, UINT h, UINT* pitch, UINT* rows) {
  if (f == kDXT1 || f == kDXT3 || f == kDXT5) {
    *pitch = std::max(1u, (w + 3) / 4) * (f == kDXT1 ? 8 : 16);
    *rows = std::max(1u, (h + 3) / 4);
  } else if (f == D3DFMT_A8R8G8B8 || f == D3DFMT_X8R8G8B8) {
    *pitch = w * 4; *rows = h;
  } else if (f == D3DFMT_A8 || f == D3DFMT_L8) {
    *pitch = w; *rows = h;
  } else if (f == D3DFMT_A8L8) {
    *pitch = w * 2; *rows = h;
  } else {
    return 0;
  }
  return (size_t)*pitch * *rows;
}

// --- codificador DXT sencillo (caja de color por bloque), suficiente para iconos
uint16_t To565(int r, int g, int b) {
  return (uint16_t)(((r * 31 + 127) / 255) << 11 | ((g * 63 + 127) / 255) << 5 | ((b * 31 + 127) / 255));
}
void From565(uint16_t c, int* o) {
  o[0] = ((c >> 11) & 31) * 255 / 31; o[1] = ((c >> 5) & 63) * 255 / 63; o[2] = (c & 31) * 255 / 31;
}
void EncodeColorBlock(const uint8_t px[16][4], bool dxt1, uint8_t* out) {
  bool punch = false;
  int mn[3] = {255, 255, 255}, mx[3] = {0, 0, 0};
  for (int i = 0; i < 16; ++i) {
    if (dxt1 && px[i][3] < 128) { punch = true; continue; }
    for (int c = 0; c < 3; ++c) { mn[c] = std::min(mn[c], (int)px[i][c]); mx[c] = std::max(mx[c], (int)px[i][c]); }
  }
  if (mn[0] > mx[0]) { mn[0] = mn[1] = mn[2] = mx[0] = mx[1] = mx[2] = 0; }
  for (int c = 0; c < 3; ++c) {  // recorte de 1/16 para un mejor ajuste
    int in = (mx[c] - mn[c]) >> 4;
    mn[c] = std::min(255, mn[c] + in); mx[c] = std::max(0, mx[c] - in);
  }
  uint16_t c0 = To565(mx[0], mx[1], mx[2]), c1 = To565(mn[0], mn[1], mn[2]);
  bool three = punch;
  if (three) { if (c0 > c1) std::swap(c0, c1); }
  else if (c0 < c1) std::swap(c0, c1);
  int p[4][3];
  From565(c0, p[0]); From565(c1, p[1]);
  int ncol = 4;
  if (!three && c0 == c1) {
    for (int c = 0; c < 3; ++c) p[2][c] = p[3][c] = p[0][c];
  } else if (three) {
    for (int c = 0; c < 3; ++c) p[2][c] = (p[0][c] + p[1][c]) / 2;
    ncol = 3;
  } else {
    for (int c = 0; c < 3; ++c) { p[2][c] = (2 * p[0][c] + p[1][c]) / 3; p[3][c] = (p[0][c] + 2 * p[1][c]) / 3; }
  }
  uint32_t bits = 0;
  for (int i = 0; i < 16; ++i) {
    int best = 0;
    if (three && px[i][3] < 128) {
      best = 3;
    } else {
      int bd = INT_MAX;
      for (int k = 0; k < ncol; ++k) {
        int d = 0;
        for (int c = 0; c < 3; ++c) { int e = px[i][c] - p[k][c]; d += e * e; }
        if (d < bd) { bd = d; best = k; }
      }
    }
    bits |= (uint32_t)best << (2 * i);
  }
  memcpy(out, &c0, 2); memcpy(out + 2, &c1, 2); memcpy(out + 4, &bits, 4);
}
void EncodeAlpha5(const uint8_t px[16][4], uint8_t* out) {
  int a0 = 0, a1 = 255;
  for (int i = 0; i < 16; ++i) { a0 = std::max(a0, (int)px[i][3]); a1 = std::min(a1, (int)px[i][3]); }
  uint64_t bits = 0;
  int pal[8];
  if (a0 == a1) {
    if (a0 < 255) a0++; else a1--;
  }
  pal[0] = a0; pal[1] = a1;
  for (int k = 0; k < 6; ++k) pal[2 + k] = ((6 - k) * a0 + (k + 1) * a1) / 7;
  for (int i = 0; i < 16; ++i) {
    int best = 0, bd = INT_MAX;
    for (int k = 0; k < 8; ++k) { int d = std::abs(px[i][3] - pal[k]); if (d < bd) { bd = d; best = k; } }
    bits |= (uint64_t)best << (3 * i);
  }
  out[0] = (uint8_t)a0; out[1] = (uint8_t)a1;
  for (int k = 0; k < 6; ++k) out[2 + k] = (uint8_t)(bits >> (8 * k));
}

// Reduce/amplía la imagen RGBA del pak a w×h (promedio por caja / vecino más cercano)
std::vector<uint8_t> Resample(const PakImage& im, UINT w, UINT h) {
  if (im.w == w && im.h == h) return im.rgba;
  std::vector<uint8_t> out((size_t)w * h * 4);
  for (UINT y = 0; y < h; ++y)
    for (UINT x = 0; x < w; ++x) {
      UINT x0 = x * im.w / w, x1 = std::max(x0 + 1, (x + 1) * im.w / w);
      UINT y0 = y * im.h / h, y1 = std::max(y0 + 1, (y + 1) * im.h / h);
      unsigned s[4] = {}, n = 0, sa = 0;
      for (UINT yy = y0; yy < y1; ++yy)
        for (UINT xx = x0; xx < x1; ++xx) {
          const uint8_t* q = &im.rgba[((size_t)yy * im.w + xx) * 4];
          for (int c = 0; c < 3; ++c) s[c] += q[c] * q[3];  // color ponderado por alfa
          sa += q[3]; s[3] += q[3]; ++n;
        }
      uint8_t* o = &out[((size_t)y * w + x) * 4];
      for (int c = 0; c < 3; ++c) o[c] = (uint8_t)(sa ? s[c] / sa : 0);
      o[3] = (uint8_t)(s[3] / n);
    }
  return out;
}

bool Encode9(const std::vector<uint8_t>& rgba, UINT w, UINT h, D3DFORMAT f, uint8_t* dst, INT dpitch) {
  if (f == D3DFMT_A8R8G8B8 || f == D3DFMT_X8R8G8B8) {
    for (UINT y = 0; y < h; ++y) {
      uint8_t* o = dst + (size_t)y * dpitch;
      for (UINT x = 0; x < w; ++x) {
        const uint8_t* q = &rgba[((size_t)y * w + x) * 4];
        o[x * 4 + 0] = q[2]; o[x * 4 + 1] = q[1]; o[x * 4 + 2] = q[0]; o[x * 4 + 3] = q[3];
      }
    }
    return true;
  }
  if (f == D3DFMT_A8) {
    for (UINT y = 0; y < h; ++y)
      for (UINT x = 0; x < w; ++x) dst[(size_t)y * dpitch + x] = rgba[((size_t)y * w + x) * 4 + 3];
    return true;
  }
  if (f != kDXT1 && f != kDXT3 && f != kDXT5) return false;
  UINT bw = std::max(1u, (w + 3) / 4), bh = std::max(1u, (h + 3) / 4);
  for (UINT by = 0; by < bh; ++by)
    for (UINT bx = 0; bx < bw; ++bx) {
      uint8_t px[16][4];
      for (int i = 0; i < 16; ++i) {
        UINT x = std::min(w - 1, bx * 4 + (i & 3)), y = std::min(h - 1, by * 4 + (i >> 2));
        memcpy(px[i], &rgba[((size_t)y * w + x) * 4], 4);
      }
      uint8_t* o = dst + (size_t)by * dpitch + bx * (f == kDXT1 ? 8 : 16);
      if (f == kDXT1) {
        EncodeColorBlock(px, true, o);
      } else {
        if (f == kDXT5) {
          EncodeAlpha5(px, o);
        } else {
          for (int i = 0; i < 8; ++i) o[i] = (uint8_t)((px[2 * i][3] * 15 + 127) / 255 | ((px[2 * i + 1][3] * 15 + 127) / 255) << 4);
        }
        EncodeColorBlock(px, false, o + 8);
      }
    }
  return true;
}

HRESULT STDMETHODCALLTYPE HookLock9(IDirect3DTexture9* t, UINT level, D3DLOCKED_RECT* lr, const RECT* rect, DWORD flags) {
  HRESULT hr = g_orig_lock9(t, level, lr, rect, flags);
  if (SUCCEEDED(hr) && lr && !rect && !(flags & D3DLOCK_READONLY)) {
    std::lock_guard<std::mutex> l(g_t9_m);
    g_locked9[(uint64_t)(uintptr_t)t << 5 | level] = {lr->pBits, lr->Pitch};
  }
  return hr;
}

// --- imágenes de paks en modo perezoso (se decodifican al encontrar su textura; las pequeñas se guardan)
std::mutex g_pak9_m;
const PakImage* GetPak9(uint64_t h, PakImage* scratch) {
  {
    std::lock_guard<std::mutex> l(g_pak9_m);
    auto it = g_pak_images.find(h);
    if (it != g_pak_images.end()) return &it->second;
  }
  auto f = g_pak_files.find(h);
  if (f == g_pak_files.end()) return nullptr;
  HRESULT co = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  bool ok = DecodeImageWic(f->second, scratch);
  if (SUCCEEDED(co)) CoUninitialize();
  if (!ok) return nullptr;
  if ((size_t)scratch->w * scratch->h <= 512 * 512) {  // se reutilizan para los niveles menores
    std::lock_guard<std::mutex> l(g_pak9_m);
    return &(g_pak_images[h] = std::move(*scratch));
  }
  return scratch;
}

// --- texturas en alta resolución: textura nueva (más grande) que se pone en lugar de la original
using PFN_SetTexture9 = HRESULT(STDMETHODCALLTYPE*)(IDirect3DDevice9*, DWORD, IDirect3DBaseTexture9*);
using PFN_UpdateTexture9 = HRESULT(STDMETHODCALLTYPE*)(IDirect3DDevice9*, IDirect3DBaseTexture9*, IDirect3DBaseTexture9*);
PFN_SetTexture9 g_orig_settex9 = nullptr;
PFN_UpdateTexture9 g_orig_updtex9 = nullptr;
std::unordered_map<IDirect3DBaseTexture9*, IDirect3DTexture9*> g_hd9;  // original -> versión HD
std::atomic<size_t> g_hd9_count{0};
std::atomic<uint64_t> g_hd9_bytes{0}, g_n9_hd{0};
std::once_flag g_dev9_once;

HRESULT STDMETHODCALLTYPE HookSetTexture9(IDirect3DDevice9* dev, DWORD stage, IDirect3DBaseTexture9* tex) {
  if (tex && g_hd9_count) {
    std::lock_guard<std::mutex> l(g_t9_m);
    auto it = g_hd9.find(tex);
    if (it != g_hd9.end()) tex = it->second;
  }
  return g_orig_settex9(dev, stage, tex);
}
// si el juego rellena una textura de sistema y la copia a la gráfica, la copia también usa la versión HD
HRESULT STDMETHODCALLTYPE HookUpdateTexture9(IDirect3DDevice9* dev, IDirect3DBaseTexture9* src, IDirect3DBaseTexture9* dst) {
  if (src && dst && g_hd9_count) {
    std::lock_guard<std::mutex> l(g_t9_m);
    auto it = g_hd9.find(src);
    auto old = g_hd9.find(dst);
    if (old != g_hd9.end() && (it == g_hd9.end() || old->second != it->second)) {
      old->second->Release();
      g_hd9.erase(old);
    }
    if (it != g_hd9.end() && !g_hd9.count(dst)) {
      it->second->AddRef();
      g_hd9[dst] = it->second;
    }
    g_hd9_count = g_hd9.size();
  }
  return g_orig_updtex9(dev, src, dst);
}

void HookDevice9(IDirect3DDevice9* dev) {
  std::call_once(g_dev9_once, [dev] {
    void** vt = *(void***)dev;
    DWORD old;
    if (VirtualProtect(&vt[31], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
      g_orig_updtex9 = (PFN_UpdateTexture9)vt[31];
      vt[31] = (void*)&HookUpdateTexture9;
      VirtualProtect(&vt[31], sizeof(void*), old, &old);
    }
    if (VirtualProtect(&vt[65], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
      g_orig_settex9 = (PFN_SetTexture9)vt[65];
      vt[65] = (void*)&HookSetTexture9;
      VirtualProtect(&vt[65], sizeof(void*), old, &old);
    }
    Log("D3D9: texturas en alta resolución listas en el dispositivo del juego");
  });
}

void DropHd9(IDirect3DBaseTexture9* t) {
  std::lock_guard<std::mutex> l(g_t9_m);
  auto it = g_hd9.find(t);
  if (it != g_hd9.end()) {
    it->second->Release();
    g_hd9.erase(it);
    g_hd9_count = g_hd9.size();
  }
}

std::unordered_map<uint64_t, IDirect3DTexture9*> g_hd9_cache;  // huella -> versión HD (la caché guarda una referencia)

void MapHd9(IDirect3DTexture9* t, IDirect3DTexture9* hd) {  // con g_t9_m tomado
  auto it = g_hd9.find(t);
  if (it != g_hd9.end()) it->second->Release();
  hd->AddRef();
  g_hd9[t] = hd;
  g_hd9_count = g_hd9.size();
}

bool UseCachedHd9(IDirect3DTexture9* t, uint64_t h) {
  std::lock_guard<std::mutex> l(g_t9_m);
  auto c = g_hd9_cache.find(h);
  if (c == g_hd9_cache.end()) return false;
  MapHd9(t, c->second);
  return true;
}

bool MakeHd9(IDirect3DTexture9* t, uint64_t h, const PakImage& im, D3DFORMAT orig_fmt) {
  if (g_hd9_bytes > (uint64_t)g_cfg.hd_max_mb << 20) return false;
  IDirect3DDevice9* dev = nullptr;
  if (FAILED(t->GetDevice(&dev)) || !dev) return false;
  HookDevice9(dev);
  // comprimida como la original (DXT1/DXT5): 4-8 veces menos memoria que sin comprimir
  D3DFORMAT fmt = D3DFMT_A8R8G8B8;
  if (im.w % 4 == 0 && im.h % 4 == 0) fmt = orig_fmt == kDXT1 ? kDXT1 : kDXT5;
  UINT levels = 1;
  while ((im.w >> levels) >= 4 && (im.h >> levels) >= 4) ++levels;
  if (t->GetLevelCount() == 1) levels = 1;  // la original no tiene mipmaps (interfaz): tampoco la HD
  IDirect3DTexture9* hd = nullptr;
  HRESULT hr = dev->CreateTexture(im.w, im.h, levels, 0, fmt, D3DPOOL_MANAGED, &hd, nullptr);
  if (FAILED(hr) && fmt != D3DFMT_A8R8G8B8) {
    fmt = D3DFMT_A8R8G8B8;
    hr = dev->CreateTexture(im.w, im.h, levels, 0, fmt, D3DPOOL_MANAGED, &hd, nullptr);
  }
  dev->Release();
  if (FAILED(hr) || !hd) return false;
  uint64_t bytes = 0;
  for (UINT lv = 0; lv < levels; ++lv) {
    UINT w = std::max(1u, im.w >> lv), hh = std::max(1u, im.h >> lv);
    D3DLOCKED_RECT lr;
    if (FAILED(g_orig_lock9(hd, lv, &lr, nullptr, 0))) break;
    Encode9(lv ? Resample(im, w, hh) : im.rgba, w, hh, fmt, (uint8_t*)lr.pBits, lr.Pitch);
    g_orig_unlock9(hd, lv);
    UINT pitch, rows;
    bytes += Level9Size(fmt, w, hh, &pitch, &rows);
  }
  std::lock_guard<std::mutex> l(g_t9_m);
  g_hd9_cache[h] = hd;  // la referencia de la creación queda en la caché
  MapHd9(t, hd);
  g_hd9_bytes += bytes;
  return true;
}

HRESULT STDMETHODCALLTYPE HookUnlock9(IDirect3DTexture9* t, UINT level) {
  g_n9_unlock++;
  Locked9 lk{};
  bool have = false;
  {
    std::lock_guard<std::mutex> l(g_t9_m);
    auto it = g_locked9.find((uint64_t)(uintptr_t)t << 5 | level);
    if (it != g_locked9.end()) { lk = it->second; have = true; g_locked9.erase(it); }
  }
  D3DSURFACE_DESC d{};
  if (have && lk.bits && SUCCEEDED(t->GetLevelDesc(level, &d)) && d.Width <= 4096 && d.Height <= 4096) {
    UINT pitch, rows;
    size_t sz = Level9Size(d.Format, d.Width, d.Height, &pitch, &rows);
    if (sz && level == 0) {
      std::vector<uint8_t> tmp(sz);
      for (UINT r = 0; r < rows; ++r) memcpy(tmp.data() + (size_t)r * pitch, (uint8_t*)lk.bits + (size_t)r * lk.pitch, pitch);
      uint64_t h = Fnv64(tmp.data(), tmp.size()) ^ ((uint64_t)d.Width << 48) ^ ((uint64_t)d.Height << 32) ^ (uint32_t)d.Format;
      DropHd9(t);  // la textura cambia de contenido (o es otra en la misma dirección)
      PakImage scratch;
      bool cached;
      {
        std::lock_guard<std::mutex> l(g_t9_m);
        cached = g_hd9_cache.count(h) != 0;
      }
      const PakImage* pi = (cached || (g_pak_files.empty() && g_pak_images.empty())) ? nullptr : GetPak9(h, &scratch);
      bool done = false;
      if (UseCachedHd9(t, h)) {
        done = true;
        {
          std::lock_guard<std::mutex> l(g_t9_m);
          g_swapped9.erase(t);
        }
      } else if (pi && (pi->w > d.Width || pi->h > d.Height)) {
        done = MakeHd9(t, h, *pi, d.Format);
        if (done) {
          g_n9_hd++;
          static int shown = 0;
          if (shown++ < 60) Log("HD (D3D9): %016llx %ux%u -> %ux%u", (unsigned long long)h, d.Width, d.Height, pi->w, pi->h);
        }
        {
          std::lock_guard<std::mutex> l(g_t9_m);
          g_swapped9.erase(t);
        }
      } else if (pi && Encode9(Resample(*pi, d.Width, d.Height), d.Width, d.Height, d.Format, (uint8_t*)lk.bits, lk.pitch)) {
        done = true;
        {
          std::lock_guard<std::mutex> l(g_t9_m);
          g_swapped9[t] = {h, d.Width};
        }
        g_n9_swapped++;
        static int shown = 0;
        if (shown++ < 100) Log("Pak aplicado (D3D9): %016llx (%ux%u)", (unsigned long long)h, d.Width, d.Height);
      }
      if (!done) {
        {
          std::lock_guard<std::mutex> l(g_t9_m);
          g_swapped9.erase(t);
        }
        if (g_cfg.tex_dump && d.Width >= 8 && d.Height >= 8 && d.Width <= 2048 && d.Height <= 2048) {
          bool fresh;
          {
            std::lock_guard<std::mutex> l(g_tex_m);
            fresh = g_dumped.insert(h).second && g_dumped.size() < 60000;
          }
          if (fresh) {
            std::wstring dir = g_dir + L"\\reforge_textures\\dump9";
            CreateDirectoryW((g_dir + L"\\reforge_textures").c_str(), nullptr);
            CreateDirectoryW(dir.c_str(), nullptr);
            wchar_t name[64];
            swprintf(name, 64, L"\\%016llx.rftx", (unsigned long long)h);
            if (GetFileAttributesW((dir + name).c_str()) == INVALID_FILE_ATTRIBUTES) {
              FILE* f = _wfopen((dir + name).c_str(), L"wb");
              if (f) {
                char hdr[96];
                int n = snprintf(hdr, sizeof(hdr), "RFTX9 %u %u %u %u\n", (unsigned)d.Format, d.Width, d.Height,
                                 t->GetLevelCount());
                fwrite(hdr, 1, n, f);
                fwrite(tmp.data(), 1, tmp.size(), f);
                fclose(f);
              }
            }
          }
        }
      }
    } else if (sz && level > 0) {
      std::pair<uint64_t, UINT> sw{0, 0};
      {
        std::lock_guard<std::mutex> l(g_t9_m);
        auto it = g_swapped9.find(t);
        if (it != g_swapped9.end()) sw = it->second;
      }
      D3DSURFACE_DESC d0{};
      if (sw.first && SUCCEEDED(t->GetLevelDesc(0, &d0)) && d0.Width == sw.second) {
        PakImage scratch;
        const PakImage* pi = GetPak9(sw.first, &scratch);
        if (pi) Encode9(Resample(*pi, d.Width, d.Height), d.Width, d.Height, d.Format, (uint8_t*)lk.bits, lk.pitch);
      }
    }
  }
  return g_orig_unlock9(t, level);
}

DWORD WINAPI D3D9Thread(void*) {
  g_lazy_paks = true;
  if (g_cfg.tex_swap) LoadSwapIndex();
  if (!g_cfg.tex_dump && g_pak_images.empty() && g_pak_files.empty()) {
    Log("D3D9: sin paks de imágenes ni volcado; no se instalan ganchos");
    return 0;
  }
  HMODULE m = LoadLibraryW(L"d3d9.dll");
  using PFN_Create9 = IDirect3D9*(WINAPI*)(UINT);
  auto create = m ? (PFN_Create9)GetProcAddress(m, "Direct3DCreate9") : nullptr;
  IDirect3D9* d3d = create ? create(D3D_SDK_VERSION) : nullptr;
  if (!d3d) {
    Log("D3D9: no se pudo iniciar Direct3D 9");
    return 0;
  }
  WNDCLASSW wc{};
  wc.lpfnWndProc = DummyWndProc;
  wc.hInstance = GetModuleHandleW(nullptr);
  wc.lpszClassName = L"ReForgeDummy9";
  RegisterClassW(&wc);
  HWND wnd = CreateWindowExW(0, wc.lpszClassName, L"", WS_OVERLAPPED, 0, 0, 8, 8, nullptr, nullptr, wc.hInstance, nullptr);
  D3DPRESENT_PARAMETERS pp{};
  pp.Windowed = TRUE;
  pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
  pp.BackBufferFormat = D3DFMT_UNKNOWN;
  pp.BackBufferWidth = pp.BackBufferHeight = 8;
  pp.hDeviceWindow = wnd;
  IDirect3DDevice9* dev = nullptr;
  HRESULT hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_NULLREF, wnd,
                                 D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE, &pp, &dev);
  if (FAILED(hr) || !dev)
    hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, wnd,
                           D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE, &pp, &dev);
  IDirect3DTexture9* tex = nullptr;
  if (SUCCEEDED(hr) && dev) dev->CreateTexture(4, 4, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr);
  if (!tex) {
    Log("D3D9: no se pudo crear la textura de prueba (%08X)", (unsigned)hr);
  } else {
    void** vt = *(void***)tex;
    DWORD old;
    if (VirtualProtect(&vt[19], sizeof(void*) * 2, PAGE_EXECUTE_READWRITE, &old)) {
      g_orig_lock9 = (PFN_Lock9)vt[19];
      g_orig_unlock9 = (PFN_Unlock9)vt[20];
      vt[19] = (void*)&HookLock9;
      vt[20] = (void*)&HookUnlock9;
      VirtualProtect(&vt[19], sizeof(void*) * 2, old, &old);
      Log("D3D9: gancho de texturas listo (volcado=%d, imágenes de paks=%zu)", g_cfg.tex_dump, g_pak_files.size());
    }
    tex->Release();
  }
  // la tabla parcheada vive en d3d9.dll (que el juego mantiene cargada); el dispositivo de prueba se libera
  if (dev) dev->Release();
  d3d->Release();
  DestroyWindow(wnd);
  for (int i = 0; i < 20; ++i) {
    Sleep(30000);
    Log("D3D9: %llu texturas desbloqueadas, %llu sustituidas, %llu en HD (%llu MB, %zu distintas)", (unsigned long long)g_n9_unlock,
        (unsigned long long)g_n9_swapped, (unsigned long long)g_n9_hd, (unsigned long long)(g_hd9_bytes >> 20),
        g_hd9_cache.size());
  }
  return 0;
}

DWORD WINAPI TextureThread(void*) {
  HookPresentVtable();
  if (!g_cfg.tex_dump && !g_cfg.tex_swap) return 0;
  if (g_cfg.tex_swap) {
    LoadSwapIndex();
    LoadRawSwaps();
  }
  if (!g_cfg.tex_dump && g_swaps.empty() && g_raw_swaps.empty() && g_pak_images.empty()) return 0;
  ID3D11Device* dev = nullptr;
  D3D_FEATURE_LEVEL fl;
  HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &dev,
                                 &fl, nullptr);
  if (FAILED(hr) || !dev) {
    Log("No se pudo crear el dispositivo D3D11 de prueba (%08X)", (unsigned)hr);
    return 0;
  }
  void** vt = *(void***)dev;
  DWORD old;
  if (VirtualProtect(&vt[5], sizeof(void*) * 3, PAGE_EXECUTE_READWRITE, &old)) {
    g_orig_tex = (PFN_CreateTexture2D)vt[5];
    g_orig_srv = (PFN_CreateSRV)vt[7];
    vt[5] = (void*)&HookCreateTexture2D;
    vt[7] = (void*)&HookCreateSRV;
    VirtualProtect(&vt[5], sizeof(void*) * 3, old, &old);
    Log("Texturas: gancho D3D11 listo (volcado=%d, sustituciones=%zu)", g_cfg.tex_dump, g_swaps.size());
  }
  ID3D11DeviceContext* ctx = nullptr;
  dev->GetImmediateContext(&ctx);
  if (ctx) {
    void** cvt = *(void***)ctx;
    if (VirtualProtect(&cvt[48], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
      g_orig_update = (PFN_Update)cvt[48];
      cvt[48] = (void*)&HookUpdate;
      VirtualProtect(&cvt[48], sizeof(void*), old, &old);
      Log("Texturas: gancho de subidas (UpdateSubresource) listo");
    }
  }
  if (g_cfg.tex_dump) {
    for (int i = 0; i < 40; ++i) {  // estadística para saber cómo carga el juego sus texturas
      Sleep(15000);
      Log("Texturas: creadas con datos %llu, vacías %llu, subidas %llu", (unsigned long long)g_n_create_init,
          (unsigned long long)g_n_create_empty, (unsigned long long)g_n_update);
    }
  }
  // el dispositivo de prueba se queda vivo: liberar el último objeto podría descargar la tabla parcheada
  return 0;
}

}  // namespace

// ----------------------------------------------------------------------------------- exportadas
// Reparto de puestos:
//  * DualSense conectado directamente (USB/Bluetooth): es el jugador 1; los demás mandos XInput, si se
//    permiten (other_controllers), pasan a 2-4.
//  * Sin DualSense directo (p. ej. a través de un adaptador como el Magic NS 2, que se presenta como mando de
//    Xbox): los mandos XInput reales pasan tal cual, en sus puestos. Solo si el puesto 1 está vacío se muestra
//    un mando en reposo (always_connected), para que el juego lo registre desde el principio.
static bool DirectDS() { return g_cfg.enabled && g_ds.connected; }

static DWORD GetStateImpl(DWORD idx, XINPUT_STATE* st, bool ex) {
  if (!st) return ERROR_BAD_ARGUMENTS;
  g_reads++;
  const Real& r = R();
  auto fn = ex && r.GetStateEx ? r.GetStateEx : r.GetState;
  if (DirectDS()) {
    if (idx == 0) {
      std::lock_guard<std::mutex> l(g_ds.m);
      *st = g_ds.state;
      if (ex) st->Gamepad.wButtons = g_ds.buttons_ex;
      return ERROR_SUCCESS;
    }
    if (!g_cfg.others) return ERROR_DEVICE_NOT_CONNECTED;
    return fn ? fn(idx - 1, st) : ERROR_DEVICE_NOT_CONNECTED;
  }
  DWORD res = fn ? fn(idx, st) : ERROR_DEVICE_NOT_CONNECTED;
  if (res == ERROR_SUCCESS) {
    if (idx == 0) g_real_pad0 = true;
    return res;
  }
  if (idx == 0) {
    g_real_pad0 = false;
    if (g_cfg.enabled && g_cfg.always_connected) {
      memset(st, 0, sizeof(*st));
      return ERROR_SUCCESS;
    }
  }
  return res;
}

extern "C" {
DWORD WINAPI XInputGetState(DWORD idx, XINPUT_STATE* st) { return GetStateImpl(idx, st, false); }
DWORD WINAPI XInputGetStateEx(DWORD idx, XINPUT_STATE* st) { return GetStateImpl(idx, st, true); }

DWORD WINAPI XInputSetState(DWORD idx, XINPUT_VIBRATION* v) {
  const Real& r = R();
  if (DirectDS()) {
    if (idx == 0) {
      if (v) {
        std::lock_guard<std::mutex> l(g_ds.m);
        g_ds.rumble_l = (uint8_t)(v->wLeftMotorSpeed >> 8);
        g_ds.rumble_r = (uint8_t)(v->wRightMotorSpeed >> 8);
        if (v->wRightMotorSpeed > 0x0800 || v->wLeftMotorSpeed > 0x1000) g_ds.last_fire = GetTickCount64();
        g_rumble_calls++;
        g_rumble_max = std::max<unsigned>(g_rumble_max, std::max(v->wLeftMotorSpeed, v->wRightMotorSpeed));
      }
      return ERROR_SUCCESS;
    }
    if (!g_cfg.others) return ERROR_DEVICE_NOT_CONNECTED;
    return r.SetState ? r.SetState(idx - 1, v) : ERROR_DEVICE_NOT_CONNECTED;
  }
  DWORD res = r.SetState ? r.SetState(idx, v) : ERROR_DEVICE_NOT_CONNECTED;
  if (res != ERROR_SUCCESS && idx == 0 && g_cfg.enabled && g_cfg.always_connected) return ERROR_SUCCESS;
  return res;
}

static void FakeCaps(XINPUT_CAPABILITIES* caps) {
  memset(caps, 0, sizeof(*caps));
  caps->Type = 1;      // XINPUT_DEVTYPE_GAMEPAD
  caps->SubType = 1;   // XINPUT_DEVSUBTYPE_GAMEPAD
  caps->Gamepad.wButtons = 0xF3FF;
  caps->Gamepad.bLeftTrigger = caps->Gamepad.bRightTrigger = 0xFF;
  caps->Gamepad.sThumbLX = caps->Gamepad.sThumbLY = caps->Gamepad.sThumbRX = caps->Gamepad.sThumbRY = (SHORT)0xFFC0;
  caps->Vibration.wLeftMotorSpeed = caps->Vibration.wRightMotorSpeed = 0xFF;
}
DWORD WINAPI XInputGetCapabilities(DWORD idx, DWORD flags, XINPUT_CAPABILITIES* caps) {
  if (!caps) return ERROR_BAD_ARGUMENTS;
  const Real& r = R();
  if (DirectDS()) {
    if (idx == 0) {
      FakeCaps(caps);
      return ERROR_SUCCESS;
    }
    if (!g_cfg.others) return ERROR_DEVICE_NOT_CONNECTED;
    return r.GetCaps ? r.GetCaps(idx - 1, flags, caps) : ERROR_DEVICE_NOT_CONNECTED;
  }
  DWORD res = r.GetCaps ? r.GetCaps(idx, flags, caps) : ERROR_DEVICE_NOT_CONNECTED;
  if (res != ERROR_SUCCESS && idx == 0 && g_cfg.enabled && g_cfg.always_connected) {
    FakeCaps(caps);
    return ERROR_SUCCESS;
  }
  return res;
}

void WINAPI XInputEnable(BOOL enable) {
  const Real& r = R();
  if (r.Enable) r.Enable(enable);
}

DWORD WINAPI XInputGetDSoundAudioDeviceGuids(DWORD idx, GUID* a, GUID* b) {
  const Real& r = R();
  if (g_ds.connected && idx == 0) {
    if (a) *a = GUID{};
    if (b) *b = GUID{};
    return ERROR_SUCCESS;
  }
  return r.GetGuids ? r.GetGuids(g_ds.connected ? idx - 1 : idx, a, b) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputGetBatteryInformation(DWORD idx, BYTE type, XINPUT_BATTERY_INFORMATION* info) {
  if (g_ds.connected && idx == 0) {
    if (info) {
      int b = g_battery;
      info->BatteryType = g_charging ? 1 : 3;  // 1 = con cable/cargando, 3 = NiMH (recargable)
      info->BatteryLevel = (BYTE)(b >= 7 ? 3 : b >= 4 ? 2 : b >= 2 ? 1 : 0);
    }
    return ERROR_SUCCESS;
  }
  const Real& r = R();
  return r.GetBattery ? r.GetBattery(g_ds.connected ? idx - 1 : idx, type, info) : ERROR_DEVICE_NOT_CONNECTED;
}

DWORD WINAPI XInputGetKeystroke(DWORD idx, DWORD res, XINPUT_KEYSTROKE* ks) {
  const Real& r = R();
  if (g_ds.connected && idx == 0) return ERROR_EMPTY;
  return r.GetKeystroke ? r.GetKeystroke(g_ds.connected ? idx - 1 : idx, res, ks) : ERROR_EMPTY;
}

DWORD WINAPI XInputWaitForGuideButton(DWORD, DWORD, void*) { return ERROR_DEVICE_NOT_CONNECTED; }
DWORD WINAPI XInputCancelGuideButtonWait(DWORD) { return ERROR_DEVICE_NOT_CONNECTED; }
DWORD WINAPI XInputPowerOffController(DWORD) { return ERROR_SUCCESS; }
}


// ----------------------------------------------------------------- protección frente a interceptaciones
// Steam Input (y otros) interceptan las funciones XInput del juego para darle su mando virtual; entonces el
// juego deja de hablar con esta DLL. Se vigila el inicio de nuestras funciones y la tabla de importaciones
// del juego, y se deshace la interceptación.
namespace {
struct Guarded { const char* name; void* fn; uint8_t orig[16]; };
Guarded g_guarded[] = {
    {"XInputGetState", (void*)&XInputGetState, {}},       {"XInputSetState", (void*)&XInputSetState, {}},
    {"XInputGetCapabilities", (void*)&XInputGetCapabilities, {}}, {"XInputGetStateEx", (void*)&XInputGetStateEx, {}},
};
HMODULE g_self = nullptr;

int FixGameImports() {
  HMODULE exe = GetModuleHandleW(nullptr);
  auto* dos = (IMAGE_DOS_HEADER*)exe;
  auto* nt = (IMAGE_NT_HEADERS*)((uint8_t*)exe + dos->e_lfanew);
  auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
  if (!dir.VirtualAddress) return 0;
  int fixed = 0;
  for (auto* imp = (IMAGE_IMPORT_DESCRIPTOR*)((uint8_t*)exe + dir.VirtualAddress); imp->Name; ++imp) {
    const char* dll = (const char*)exe + imp->Name;
    if (_stricmp(dll, "xinput1_3.dll") != 0) continue;
    auto* thunk = (IMAGE_THUNK_DATA*)((uint8_t*)exe + imp->FirstThunk);
    auto* orig = imp->OriginalFirstThunk ? (IMAGE_THUNK_DATA*)((uint8_t*)exe + imp->OriginalFirstThunk) : nullptr;
    for (int i = 0; thunk[i].u1.Function; ++i) {
      FARPROC want = nullptr;
      if (orig) {
        if (IMAGE_SNAP_BY_ORDINAL(orig[i].u1.Ordinal))
          want = GetProcAddress(g_self, (LPCSTR)(uintptr_t)IMAGE_ORDINAL(orig[i].u1.Ordinal));
        else
          want = GetProcAddress(g_self, ((IMAGE_IMPORT_BY_NAME*)((uint8_t*)exe + orig[i].u1.AddressOfData))->Name);
      }
      if (!want || (FARPROC)thunk[i].u1.Function == want) continue;
      DWORD old;
      if (VirtualProtect(&thunk[i].u1.Function, sizeof(void*), PAGE_READWRITE, &old)) {
        thunk[i].u1.Function = (uintptr_t)want;
        VirtualProtect(&thunk[i].u1.Function, sizeof(void*), old, &old);
        ++fixed;
      }
    }
  }
  return fixed;
}

DWORD WINAPI GuardThread(void*) {
  for (int it = 0;; ++it) {
    Sleep(it < 600 ? 500 : 3000);
    for (auto& g : g_guarded) {
      if (memcmp(g.fn, g.orig, sizeof(g.orig)) == 0) continue;
      DWORD old;
      if (VirtualProtect(g.fn, sizeof(g.orig), PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(g.fn, g.orig, sizeof(g.orig));
        VirtualProtect(g.fn, sizeof(g.orig), old, &old);
        FlushInstructionCache(GetCurrentProcess(), g.fn, sizeof(g.orig));
        static int shown = 0;
        if (shown++ < 20) Log("Otro programa (probablemente Steam Input) interceptó %s: deshecho, el juego vuelve a usar el DualSense", g.name);
      }
    }
    int n = FixGameImports();
    static int shown_iat = 0;
    if (n && shown_iat++ < 20) Log("Importaciones XInput del juego redirigidas por otro programa (%d): restauradas", n);
  }
}
}  // namespace

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    DisableThreadLibraryCalls(inst);
    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    g_dir = exe;
    g_dir = g_dir.substr(0, g_dir.find_last_of(L"\\/"));
    LoadConfig();
    Log("ReForge DualSense 1.0 (activado=%d, gatillos=%d, volcado de texturas=%d)", g_cfg.enabled, g_cfg.triggers,
        g_cfg.tex_dump);
    g_self = inst;
    for (auto& g : g_guarded) memcpy(g.orig, g.fn, sizeof(g.orig));
    if (g_cfg.guard_hooks) CloseHandle(CreateThread(nullptr, 0, GuardThread, nullptr, 0, nullptr));
    CloseHandle(CreateThread(nullptr, 0, HidThread, nullptr, 0, nullptr));
    if (g_cfg.d3d11) CloseHandle(CreateThread(nullptr, 0, TextureThread, nullptr, 0, nullptr));
    if (g_cfg.d3d9) CloseHandle(CreateThread(nullptr, 0, D3D9Thread, nullptr, 0, nullptr));
  }
  return TRUE;
}

#ifdef DS_STANDALONE
// Prueba de gatillos: probar_gatillos.exe — recorre los efectos para comprobar que el mando los recibe.
int main() {
  SetConsoleOutputCP(65001);
  wchar_t exe[MAX_PATH];
  GetModuleFileNameW(nullptr, exe, MAX_PATH);
  g_dir = exe;
  g_dir = g_dir.substr(0, g_dir.find_last_of(L"\\/"));
  LoadConfig();
  Device d;
  if (!OpenDualSense(d)) {
    printf("No encuentro el DualSense. Conéctalo por cable USB o Bluetooth al PC (no por el adaptador) y vuelve a abrir.\n");
    system("pause");
    return 1;
  }
  printf("DualSense %s conectado. Mantén L2 y R2 a medio apretar y aprieta despacio durante cada prueba.\n\n",
         d.bt ? "Bluetooth" : "USB");
  struct Step { const char* name; Effect11 l2, r2; uint8_t ml, mr, r, g, b; } steps[] = {
      {"1/6 Resistencia continua en ambos gatillos (L2 y R2 duros)", EffFeedback(0, 8), EffFeedback(0, 8), 0, 0, 255, 255, 255},
      {"2/6 Apuntado (L2 suave desde la mitad)", EffFeedback(3, 3), EffOff(), 0, 0, 0, 80, 255},
      {"3/6 Gatillo de arma en R2 (resiste y luego 'clic')", EffOff(), EffWeapon(4, 6, 8), 0, 0, 0, 255, 0},
      {"4/6 R2 vibrando como un arma automática", EffOff(), EffVibration(2, 8, 30), 0, 0, 255, 120, 0},
      {"5/6 Vibración de los motores (izquierdo fuerte, derecho suave)", EffOff(), EffOff(), 255, 60, 255, 0, 0},
      {"6/6 Todo apagado", EffOff(), EffOff(), 0, 0, 0, 80, 255},
  };
  for (auto& s : steps) {
    printf("%s ...\n", s.name);
    ULONGLONG t0 = GetTickCount64();
    while (GetTickCount64() - t0 < 6000) {
      SendOutput(d, s.l2, s.r2, s.ml, s.mr, true, s.r, s.g, s.b);
      Sleep(250);
    }
  }
  printf("\nListo. Dime qué pruebas notaste (por número).\n");
  if (d.hw != d.h) CloseHandle(d.hw);
  CloseHandle(d.h);
  system("pause");
  return 0;
}
#endif
