"""Menú Guía de ReForge para los proyectos del SDK 0.11 (API `rex::app::TitleApp`).

El SDK 0.11 cambió la API de aplicación (no hay `ReXApp` ni los diálogos de ImGui de 0.10), así que la
extensión de 0.10 no compila ahí. Este módulo genera una versión propia y más pequeña, montada sobre lo que
sí ofrece 0.11:

* `rex::ui::DialogBase` + `IUISystem::AddDialog` para la ventana (ImGui lo dibuja el propio SDK).
* `TitleRuntime::SetAudioPaused` para el silencio al instante.
* `TitleRuntime::GetAchievementManager` para la lista de logros.
* `IInputSystem::GetState` para el botón Guía del mando (y la tecla Inicio del teclado).

Lo que el runtime no cambia en caliente (fotogramas, escala de resolución, idioma) se guarda en
`reforge_menu.ini`, el mismo formato que la extensión de 0.10: ReForge lo aplica al arrancar el juego.
"""

SOURCE = r"""// ReForge Studio: menú Guía para proyectos del SDK 0.11 (generado; no editar a mano).
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <windows.h>
#include <imgui.h>

#include <rex/app/app.h>
#include <rex/hid/input_system.h>
#include <rex/kernel/title_runtime.h>
#include <rex/title.h>
#include <rex/ui/ui_system.h>
#include <rex/xam/achievement_manager.h>

namespace reforge {

namespace {

constexpr u16 kPadUp = 0x0001, kPadDown = 0x0002, kPadLeft = 0x0004, kPadRight = 0x0008;
constexpr u16 kPadStart = 0x0010, kPadA = 0x1000, kPadB = 0x2000, kPadGuide = 0x0400;

const char* const kFpsNames[] = {"30 FPS con VSync", "60 FPS con VSync", "Sin límite"};
const char* const kFpsKeys[] = {"30", "60", "unlimited"};
const char* const kLanguageNames[] = {"English", "日本語", "Deutsch", "Français", "Español", "Italiano",
                                      "한국어", "中文", "Português", "Polski", "Русский", "Türkçe"};

std::string Trim(std::string s) {
  const char* ws = " \t\r\n\"";
  s.erase(0, s.find_first_not_of(ws));
  const auto end = s.find_last_not_of(ws);
  s.erase(end == std::string::npos ? 0 : end + 1);
  return s;
}

std::filesystem::path IniPath() {
  wchar_t buf[MAX_PATH] = {};
  GetModuleFileNameW(nullptr, buf, MAX_PATH);
  return std::filesystem::path(buf).parent_path() / "reforge_menu.ini";
}

struct Prefs {
  bool show_fps = true;
  int fps_mode = -1;          // -1 = el de ReForge · 0 = 30 · 1 = 60 · 2 = sin límite
  int resolution_scale = 0;   // 0 = la de ReForge
  int mute = -1;              // -1 = el de ReForge · 0 = con sonido · 1 = silenciado
  int language = 0;           // 0 = el de ReForge
  bool loaded = false;
};

Prefs& GetPrefs() {
  static Prefs prefs;
  if (!prefs.loaded) {
    prefs.loaded = true;
    std::ifstream file(IniPath());
    std::string line;
    while (std::getline(file, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos || line.empty() || line[0] == '#') continue;
      const std::string key = Trim(line.substr(0, eq)), val = Trim(line.substr(eq + 1));
      if (key == "show_fps") prefs.show_fps = (val == "1");
      else if (key == "accent") continue;
      else if (key == "fps_mode") prefs.fps_mode = (val == "30") ? 0 : (val == "60" ? 1 : (val == "unlimited" ? 2 : -1));
      else if (key == "resolution_scale") prefs.resolution_scale = std::clamp(std::atoi(val.c_str()), 0, 3);
      else if (key == "mute") prefs.mute = (val == "1") ? 1 : 0;
      else if (key == "language") prefs.language = std::clamp(std::atoi(val.c_str()), 0, 12);
    }
  }
  return prefs;
}

void SavePrefs() {
  const Prefs& p = GetPrefs();
  std::string other;
  {  // conserva las claves que escribe la extensión de 0.10 (color de acento, notificaciones…)
    std::ifstream in(IniPath());
    std::string line;
    while (std::getline(in, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos) continue;
      const std::string key = Trim(line.substr(0, eq));
      if (key.empty() || key[0] == '#' || key == "show_fps" || key == "fps_mode" ||
          key == "resolution_scale" || key == "mute" || key == "language")
        continue;
      other += line + "\n";
    }
  }
  std::ofstream f(IniPath(), std::ios::trunc);
  f << "# Ajustes elegidos en el menú Guía del juego (botón Xbox/PS)\n"
    << "show_fps = " << (p.show_fps ? 1 : 0) << "\n";
  if (p.fps_mode >= 0) f << "fps_mode = " << kFpsKeys[std::clamp(p.fps_mode, 0, 2)] << "\n";
  if (p.resolution_scale > 0) f << "resolution_scale = " << std::clamp(p.resolution_scale, 1, 3) << "\n";
  if (p.mute >= 0) f << "mute = " << (p.mute == 1 ? 1 : 0) << "\n";
  if (p.language > 0) f << "language = " << std::clamp(p.language, 1, 12) << "\n";
  f << other;
}

// Texto del aviso flotante (lo que acabas de cambiar).
struct Status {
  std::string text;
  double until = 0.0;
};

}  // namespace

class GuideMenu final : public rex::ui::DialogBase {
 public:
  GuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title) : app_(app), title_(title) {
    Prefs& p = GetPrefs();
    if (p.mute == 1) title_.SetAudioPaused(true);   // silenciado en una partida anterior
    selected_[tab_] = 0;
  }

  bool NeedsContinuousPaint() const override { return true; }
  bool WantsExclusiveInput() const override { return open_; }

  bool Draw(ImGuiIO& io) override {
    const double now = ImGui::GetTime();
    ReadInput();
    if (GetPrefs().show_fps) {
      ImGui::GetForegroundDrawList()->AddText(ImVec2(12, 10), IM_COL32(25, 211, 162, 235),
                                              (std::to_string(static_cast<int>(io.Framerate + 0.5f)) + " FPS").c_str());
    }
    if (status_.until > now && !status_.text.empty()) DrawStatus(io, now);
    if (!open_) return true;
    DrawWindow(io);
    return true;
  }

 private:
  // ---------------------------------------------------------------- entrada (mando y teclado)
  void ReadInput() {
    u16 pressed = 0;
    if (auto pad = app_.GetInput().GetState(0); pad.has_value()) {
      const u16 now = pad->state.buttons;
      pressed = static_cast<u16>(now & ~last_buttons_);
      last_buttons_ = now;
    }
    static bool home_down = false;
    const bool home = ImGui::IsKeyDown(ImGuiKey_Home);
    if (home && !home_down) pressed |= kPadGuide;
    home_down = home;

    if (pressed & kPadGuide) {           // botón PS/Xbox del mando o tecla Inicio
      open_ = !open_;
      if (!open_) SavePrefs();
      return;
    }
    if (!open_) return;
    if (pressed & kPadB) {
      open_ = false;
      SavePrefs();
      return;
    }
    if (pressed & kPadUp) Select(-1, 0);
    if (pressed & kPadDown) Select(1, 0);
    if (pressed & kPadLeft) Select(0, -1);
    if (pressed & kPadRight) Select(0, 1);
    if (pressed & kPadA) Activate();
  }

  void Select(int row_delta, int value_delta) {
    if (row_delta) {
      const int count = ItemCount();
      selected_[tab_] = (selected_[tab_] + row_delta + count) % count;
    }
    if (value_delta) Change(selected_[tab_], value_delta);
  }

  void Activate() { Change(selected_[tab_], 1); }

  void Change(int item, int dir) {
    Prefs& p = GetPrefs();
    if (tab_ == kGraphics) {
      if (item == 0) {
        p.fps_mode = (p.fps_mode < 0 ? 0 : (p.fps_mode + 3 + dir) % 3);
        status_ = {"Fotogramas: " + std::string(kFpsNames[p.fps_mode]) + " · se aplica al reiniciar", 0.0};
      } else if (item == 1) {
        const int cur = p.resolution_scale > 0 ? p.resolution_scale : 1;
        p.resolution_scale = std::clamp(cur + dir, 1, 3);
        status_ = {"Escala de resolución: " + std::to_string(p.resolution_scale) + "× · se aplica al reiniciar", 0.0};
      } else {
        p.show_fps = !p.show_fps;
        status_ = {p.show_fps ? "Contador de FPS activado" : "Contador de FPS desactivado", 0.0};
      }
    } else if (tab_ == kSettings) {
      if (item == 0) {
        const bool mute = !(p.mute == 1);
        p.mute = mute ? 1 : 0;
        title_.SetAudioPaused(mute);      // al instante, sin reiniciar
        status_ = {mute ? "Juego silenciado" : "Sonido activado", 0.0};
      } else {
        const int cur = p.language > 0 ? p.language : 5;
        p.language = (cur + dir + 12 - 1) % 12 + 1;
        status_ = {"Idioma del juego: " + std::string(kLanguageNames[p.language - 1]) + " · se aplica al reiniciar", 0.0};
      }
    } else {
      const int count = static_cast<int>(Achievements().size());
      if (count) list_scroll_ = (list_scroll_ + dir + count) % count;
    }
    status_.until = ImGui::GetTime() + 3.0;
    SavePrefs();
  }

  int ItemCount() const {
    if (tab_ == kGraphics) return 3;
    if (tab_ == kSettings) return 2;
    return std::max(1, static_cast<int>(Achievements().size()));
  }

  const std::vector<rex::Achievement>& Achievements() const {
    if (!achievements_loaded_) {
      achievements_loaded_ = true;
      try {
        achievements_ = title_.GetAchievementManager().ListAchievements();
      } catch (...) {
        achievements_.clear();
      }
      unlocked_ = 0;
      for (const auto& a : achievements_)
        if (a.unlocked) ++unlocked_;
    }
    return achievements_;
  }

  // ---------------------------------------------------------------- dibujo
  void DrawWindow(ImGuiIO& io) {
    const Prefs& p = GetPrefs();
    ImGui::SetNextWindowSize(ImVec2(620, 430), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.35f), ImGuiCond_FirstUseEver,
                            ImVec2(0.5f, 0.5f));
    if (!ImGui::Begin("ReForge · Guía (botón PS / Inicio)", nullptr,
                      ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings)) {
      ImGui::End();
      return;
    }
    const char* tabs[] = {"Gráficos", "Ajustes", "Logros"};
    for (int i = 0; i < 3; ++i) {
      if (i) ImGui::SameLine();
      const bool on = (tab_ == i);
      if (on) ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.10f, 0.83f, 0.64f, 1.0f));
      if (ImGui::Button(tabs[i])) {
        tab_ = i;
        selected_[tab_] = 0;
      }
      if (on) ImGui::PopStyleColor();
    }
    ImGui::Separator();
    if (tab_ == kGraphics) {
      Row(0, "Fotogramas", p.fps_mode < 0 ? "El de ReForge" : kFpsNames[p.fps_mode]);
      Row(1, "Escala de resolución", std::to_string(p.resolution_scale > 0 ? p.resolution_scale : 1) + "×");
      Row(2, "Contador de FPS", p.show_fps ? "Sí" : "No");
      ImGui::Spacing();
      ImGui::TextDisabled("El mando se come la ventana mientras el menú está abierto.\n"
                          "Lo que el runtime no cambia en caliente se aplica al reiniciar.");
    } else if (tab_ == kSettings) {
      Row(0, "Silenciar el juego", p.mute == 1 ? "Sí" : "No");
      Row(1, "Idioma del juego", kLanguageNames[std::clamp(p.language > 0 ? p.language : 5, 1, 12) - 1]);
      ImGui::Spacing();
      ImGui::TextDisabled("El silencio se aplica al momento. El idioma, al reiniciar el juego.");
    } else {
      const auto& list = Achievements();
      ImGui::Text("%d de %d logros", unlocked_, static_cast<int>(list.size()));
      ImGui::BeginChild("logros", ImVec2(0, 0), ImGuiChildFlags_None);
      for (const auto& a : list) {
        ImGui::TextColored(a.unlocked ? ImVec4(0.10f, 0.83f, 0.64f, 1.0f) : ImVec4(0.55f, 0.60f, 0.65f, 1.0f),
                           "%s %s (%u G)", a.unlocked ? "★" : "·", a.label.c_str(), a.gamerscore);
        if (!a.description.empty()) ImGui::TextDisabled("   %s", a.GetDescription().c_str());
      }
      ImGui::EndChild();
    }
    ImGui::End();
  }

  void Row(int index, const char* name, const std::string& value) {
    const bool on = (selected_[tab_] == index);
    ImGui::PushStyleColor(ImGuiCol_Button, on ? ImVec4(0.10f, 0.83f, 0.64f, 1.0f) : ImVec4(0.15f, 0.18f, 0.21f, 1.0f));
    const std::string label = std::string(name) + "   " + value;
    if (ImGui::Button((label + "##r" + std::to_string(index)).c_str(), ImVec2(-1, 34))) {
      selected_[tab_] = index;
      Change(index, 1);
    }
    ImGui::PopStyleColor();
  }

  void DrawStatus(ImGuiIO& io, double now) {
    const float w = 420.0f;
    const ImVec2 pos(io.DisplaySize.x * 0.5f - w * 0.5f, io.DisplaySize.y - 90.0f);
    ImGui::GetForegroundDrawList()->AddRectFilled(pos, ImVec2(pos.x + w, pos.y + 46),
                                                  IM_COL32(20, 24, 28, 235), 8.0f);
    ImGui::GetForegroundDrawList()->AddText(ImVec2(pos.x + 16, pos.y + 14), IM_COL32(25, 211, 162, 255),
                                            status_.text.c_str());
  }

  enum Tab { kGraphics, kSettings, kAchievements };
  rex::app::App& app_;
  rex::kernel::TitleRuntime& title_;
  int tab_ = kGraphics;
  int selected_[3] = {0, 0, 0};
  bool open_ = false;
  u16 last_buttons_ = 0;
  int list_scroll_ = 0;
  mutable bool achievements_loaded_ = false;
  mutable int unlocked_ = 0;
  mutable std::vector<rex::Achievement> achievements_;
  Status status_{};
};

void InstallGuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title) {
  app.GetUI().AddDialog(std::make_unique<GuideMenu>(app, title));
}

}  // namespace reforge
"""

BLOCK_BEGIN = "  // >>> ReForge Studio: menú Guía (no editar este bloque)"
BLOCK_END = "  // <<< ReForge Studio menú Guía"
BLOCK = (f"{BLOCK_BEGIN}\n"
         "  rex::Result<void> OnTitleLaunch(rex::kernel::TitleRuntime& title) override {\n"
         "    reforge::InstallGuideMenu(*this, title);\n"
         "    return rex::app::TitleApp::OnTitleLaunch(title);\n"
         "  }\n"
         f"{BLOCK_END}\n")

DECL = ("// >>> ReForge Studio: menú Guía (no editar este bloque)\n"
        "namespace reforge {\n"
        "void InstallGuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title);\n"
        "}  // namespace reforge\n"
        "// <<< ReForge Studio menú Guía\n")

SOURCE_NAME = "reforge_menu.cpp"


def _write_if_changed(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def applies(root):
    """¿Es un proyecto del SDK 0.11 (API `rex::app::TitleApp`) con `src/main.cpp`?"""
    import os
    main = os.path.join(root, "src", "main.cpp")
    try:
        with open(main, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return False
    return "REX_TITLE_APP" in txt or "rex::app::TitleApp" in txt


def remove(root):
    """Quita el menú Guía de un proyecto 0.11 (vuelve al comportamiento normal del SDK)."""
    import os
    import re

    changes = []
    src = os.path.join(root, "src")
    for name, label in ((SOURCE_NAME, f"src/{SOURCE_NAME}"),
                        ("main.cpp", "src/main.cpp"), (os.path.join("..", "CMakeLists.txt"), "CMakeLists.txt")):
        path = os.path.normpath(os.path.join(src, name))
        try:
            txt = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if name == SOURCE_NAME:
            try:
                os.remove(path)
                changes.append(label)
            except OSError:
                pass
            continue
        new = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n", lambda _m: "", txt, flags=re.S)
        # la declaración de InstallGuideMenu tiene su propio bloque
        new = re.sub(r"// >>> ReForge Studio: menú Guía \(no editar este bloque\)\n(?:.*?\n)*?// <<< ReForge Studio menú Guía\n\n?",
                     "", new)
        new = new.replace(f" src/{SOURCE_NAME}", "")
        if new != txt:
            _write_if_changed(path, new)
            changes.append(label)
    return changes


def ensure(root):
    """Genera/actualiza el menú Guía de 0.11. Devuelve la lista de archivos cambiados (vacía si ya estaba)."""
    import os
    import re

    changes = []
    src = os.path.join(root, "src")
    main = os.path.join(src, "main.cpp")
    cml = os.path.join(root, "CMakeLists.txt")
    if not (os.path.isfile(main) and os.path.isfile(cml)) or not applies(root):
        return changes
    if _write_if_changed(os.path.join(src, SOURCE_NAME), SOURCE):
        changes.append(f"src/{SOURCE_NAME}")

    txt = open(main, encoding="utf-8").read()
    orig = txt
    if "InstallGuideMenu" not in txt.split("class ")[0]:
        anchor = re.search(r"^(#include[^\n]*\n)(?!#include)", txt, re.M)
        if anchor:      # la declaración va tras el último #include
            last = None
            for last in re.finditer(r"^#include[^\n]*\n", txt, re.M):
                pass
            if last:
                txt = txt[:last.end()] + "\n" + DECL + txt[last.end():]
    if BLOCK_BEGIN in txt:
        txt = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n", lambda _m: BLOCK, txt, flags=re.S)
    else:
        m = re.search(r"(class\s+\w+\s*:\s*public\s+rex::app::TitleApp\s*\{\s*\n\s*public:\s*\n)", txt)
        if m:
            txt = txt[:m.end()] + BLOCK + "\n" + txt[m.end():]
    if txt != orig:
        _write_if_changed(main, txt)
        changes.append("src/main.cpp")

    build = open(cml, encoding="utf-8").read()
    if f"src/{SOURCE_NAME}" not in build:
        # Los proyectos 0.11 meten las fuentes del host en <PROYECTO>_HOST_SOURCES (biblioteca OBJECT);
        # así el archivo hereda los includes/defines de rexglue. Si no existe, se añade al ejecutable.
        new, n = re.subn(r"^(set\(\w*_HOST_SOURCES[^\n)]*)\)", r"\1 src/" + SOURCE_NAME + r")", build, count=1,
                         flags=re.M)
        if not n:
            new, n = re.subn(r"^(\s*)(add_executable\([^\n]*src/main\.cpp)",
                             r"\1\2 src/" + SOURCE_NAME, build, count=1, flags=re.M)
        if n:
            _write_if_changed(cml, new)
            changes.append("CMakeLists.txt")
    return changes
