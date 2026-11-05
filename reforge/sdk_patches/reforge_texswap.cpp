// ReForge Studio: cambio de texturas en la GPU (iconos de botones Xbox <-> PlayStation, packs universales).
//
// Cada vez que el juego sube una textura a la GPU, se calcula el hash XXH3 de sus bytes (nivel base, tal
// como están en la memoria del juego). Si ReForge preparó una pareja para ese hash (original de Xbox +
// versión PlayStation, mismos bytes de tamaño y formato), se escriben en la memoria del juego los bytes del
// estilo elegido antes de subirla. Funciona con cualquier formato de archivo del juego (.xpr, .str, .ff…).
//
// Junto al .exe, carpeta reforge_textures/:
//   index.txt       una pareja por línea: <original.bin> <playstation.bin>
//   style.txt       "playstation" o "xbox" (se vigila: cambiarlo en marcha cambia los iconos al momento)
//   dump.on         si existe, guarda en dump/ las texturas pequeñas que el juego usa (para reconocerlas)
#include "reforge_texswap.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <rex/filesystem.h>
#include <xxhash.h>

namespace rex::graphics::reforge_texswap {
namespace {

namespace fs = std::filesystem;

struct Pair {
  std::vector<uint8_t> side[2];  // 0 = original (Xbox), 1 = PlayStation
  uint64_t hash[2] = {0, 0};
};

struct Live {
  uint32_t addr;
  uint32_t size;
  uint64_t hash_now;  // hash de lo que ReForge dejó (o encontró) en la memoria del juego
};

struct DumpJob {
  uint64_t hash;
  std::string header;
  std::vector<uint8_t> data;
};

constexpr uint32_t kMaxDumpBytes = 1u << 20;
constexpr uint32_t kMaxDumpSide = 1024;
constexpr size_t kMaxDumps = 6000;
constexpr size_t kMaxLive = 8192;

std::mutex g_mutex;
bool g_init = false;
fs::path g_dir;
std::vector<Pair> g_pairs;
std::unordered_map<uint64_t, std::pair<uint32_t, int>> g_by_hash;  // hash -> (pareja, lado)
std::unordered_map<uint32_t, Live> g_live;                          // dirección -> textura cambiable
std::unordered_map<uint64_t, std::pair<uint32_t, uint32_t>> g_seen;  // hash volcado -> (dir, tamaño)
std::unordered_set<uint64_t> g_dumped;
int g_style = 0;
bool g_dump = false;
fs::file_time_type g_index_time{}, g_style_time{};
std::chrono::steady_clock::time_point g_next_poll{};

std::mutex g_q_mutex;
std::condition_variable g_q_cv;
std::deque<DumpJob> g_queue;
std::once_flag g_worker_once;

void Worker() {
  for (;;) {
    DumpJob job;
    {
      std::unique_lock<std::mutex> lock(g_q_mutex);
      g_q_cv.wait(lock, [] { return !g_queue.empty(); });
      job = std::move(g_queue.front());
      g_queue.pop_front();
    }
    std::error_code ec;
    fs::create_directories(g_dir / "dump", ec);
    char name[40];
    std::snprintf(name, sizeof(name), "%016llx.rftx", static_cast<unsigned long long>(job.hash));
    const fs::path tmp = g_dir / "dump" / (std::string(name) + ".tmp");
    {
      std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
      f.write(job.header.data(), static_cast<std::streamsize>(job.header.size()));
      f.write(reinterpret_cast<const char*>(job.data.data()), static_cast<std::streamsize>(job.data.size()));
    }
    fs::rename(tmp, g_dir / "dump" / name, ec);
  }
}

bool ReadFile(const fs::path& p, std::vector<uint8_t>& out) {
  std::ifstream f(p, std::ios::binary);
  if (!f) return false;
  out.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
  return !out.empty();
}

void LoadStyleLocked() {
  std::error_code ec;
  const fs::path p = g_dir / "style.txt";
  const auto t = fs::last_write_time(p, ec);
  if (ec || t == g_style_time) return;
  g_style_time = t;
  std::ifstream f(p);
  std::string s;
  f >> s;
  g_style = (s == "playstation") ? 1 : 0;
}

void LoadIndexLocked() {
  std::error_code ec;
  const fs::path p = g_dir / "index.txt";
  const auto t = fs::last_write_time(p, ec);
  if (ec || t == g_index_time) return;
  g_index_time = t;
  g_pairs.clear();
  g_by_hash.clear();
  std::ifstream f(p);
  std::string a, b;
  while (f >> a >> b) {
    Pair pair;
    if (!ReadFile(g_dir / a, pair.side[0]) || !ReadFile(g_dir / b, pair.side[1]) ||
        pair.side[0].size() != pair.side[1].size()) {
      continue;
    }
    pair.hash[0] = XXH3_64bits(pair.side[0].data(), pair.side[0].size());
    pair.hash[1] = XXH3_64bits(pair.side[1].data(), pair.side[1].size());
    if (pair.hash[0] == pair.hash[1]) continue;
    const uint32_t idx = static_cast<uint32_t>(g_pairs.size());
    g_by_hash[pair.hash[0]] = {idx, 0};
    g_by_hash[pair.hash[1]] = {idx, 1};
    g_pairs.push_back(std::move(pair));
  }
}

void InitLocked() {
  if (g_init) return;
  g_init = true;
  g_dir = rex::filesystem::GetExecutableFolder() / "reforge_textures";
  std::error_code ec;
  g_dump = fs::exists(g_dir / "dump.on", ec);
  if (g_dump) {
    for (const auto& e : fs::directory_iterator(g_dir / "dump", ec)) {
      const std::string n = e.path().stem().string();
      if (n.size() == 16) g_dumped.insert(std::strtoull(n.c_str(), nullptr, 16));
    }
  }
  LoadIndexLocked();
  LoadStyleLocked();
}

// Escribe en la memoria del juego la versión del estilo elegido (solo si ahí sigue lo que se dejó).
// Devuelve false si esa memoria ya no es la textura (el juego la reutilizó): se olvida.
bool ApplyLocked(uint8_t* membase, Live& live) {
  auto it = g_by_hash.find(live.hash_now);
  if (it == g_by_hash.end()) return true;
  const Pair& pair = g_pairs[it->second.first];
  if (it->second.second == g_style) return true;
  const std::vector<uint8_t>& want = pair.side[g_style];
  if (want.size() != live.size) return true;
  uint8_t* p = membase + (live.addr & 0x1FFFFFFF);
  if (XXH3_64bits(p, live.size) != live.hash_now) return false;
  std::memcpy(p, want.data(), live.size);  // la vigilancia de memoria marca la textura para recargarla
  live.hash_now = pair.hash[g_style];
  return true;
}

}  // namespace

void OnLoad(uint8_t* membase, uint32_t base_address, uint32_t base_size, uint32_t width, uint32_t height,
            uint32_t pitch_texels, uint32_t tiled, uint32_t format, uint32_t endianness, uint32_t has_mips) {
  if (!membase || !base_size || base_size > (16u << 20)) return;
  std::lock_guard<std::mutex> lock(g_mutex);
  InitLocked();
  if (g_pairs.empty() && !g_dump) return;
  uint8_t* p = membase + (base_address & 0x1FFFFFFF);
  const uint64_t h = XXH3_64bits(p, base_size);
  auto it = g_by_hash.find(h);
  if (it != g_by_hash.end()) {
    const Pair& pair = g_pairs[it->second.first];
    if (pair.side[0].size() == base_size) {
      Live live{base_address, base_size, h};
      if (it->second.second != g_style) {
        std::memcpy(p, pair.side[g_style].data(), base_size);
        live.hash_now = pair.hash[g_style];
      }
      if (g_live.size() < kMaxLive || g_live.count(base_address)) g_live[base_address] = live;
    }
    return;
  }
  if (!g_dump || base_size > kMaxDumpBytes || width > kMaxDumpSide || height > kMaxDumpSide) return;
  // solo formatos que ReForge sabe leer: 8888, DXT1, DXT3, DXT5
  if (format != 6 && format != 18 && format != 19 && format != 20) return;
  if (g_seen.size() < kMaxLive) g_seen[h] = {base_address, base_size};
  if (g_dumped.size() >= kMaxDumps || !g_dumped.insert(h).second) return;
  char header[160];
  const int n = std::snprintf(header, sizeof(header), "RFTX1 %u %u %u %u %u %u %u %u\n", format, width, height,
                              pitch_texels, tiled, endianness, base_size, has_mips);
  DumpJob job{h, std::string(header, n > 0 ? static_cast<size_t>(n) : 0), std::vector<uint8_t>(p, p + base_size)};
  std::call_once(g_worker_once, [] { std::thread(Worker).detach(); });
  {
    std::lock_guard<std::mutex> ql(g_q_mutex);
    g_queue.push_back(std::move(job));
  }
  g_q_cv.notify_one();
}

void Tick(uint8_t* membase) {
  const auto now = std::chrono::steady_clock::now();
  std::lock_guard<std::mutex> lock(g_mutex);
  if (now < g_next_poll) return;
  g_next_poll = now + std::chrono::milliseconds(500);
  InitLocked();
  const int old_style = g_style;
  const size_t old_pairs = g_pairs.size();
  const auto old_index_time = g_index_time;
  LoadStyleLocked();
  LoadIndexLocked();
  if (!membase) return;
  if (g_index_time != old_index_time) {
    // parejas nuevas (ReForge reconoce texturas mientras juegas): las ya cargadas cambian al momento
    for (const auto& [h, where] : g_seen) {
      if (!g_by_hash.count(h) || g_live.count(where.first)) continue;
      g_live[where.first] = Live{where.first, where.second, h};
    }
  }
  if (g_style != old_style || g_pairs.size() != old_pairs || g_index_time != old_index_time) {
    for (auto it = g_live.begin(); it != g_live.end();) {
      if (ApplyLocked(membase, it->second)) {
        ++it;
      } else {
        it = g_live.erase(it);
      }
    }
  }
}

}  // namespace rex::graphics::reforge_texswap
