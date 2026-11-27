// dispatcher_trace_selftest.cpp
// Prueba autocontenida del MECANISMO de instrumentación del despachador (no usa el SDK): reproduce el
// seguimiento id/fase/ra y el bucle try/catch que convierte la excepción en fatal, y comprueba:
//   - el ID de la tarea activa se mantiene durante pre/work/complete/post,
//   - una excepción en `post` deja el fatal con el ID correcto y fase=post,
//   - dos tareas que comparten la misma dirección overlapped se distinguen por su ID (se culpa a la que lanza).
// Compilar: clang++ -std=c++20 -O2 dispatcher_trace_selftest.cpp -o selftest  (o cl /std:c++20 /EHsc)
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <functional>
#include <stdexcept>
#include <string>

namespace {
struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; const char* phase = "idle"; };
thread_local RfDeferredTag rf_active_deferred{};
thread_local const void* rf_enqueue_ra = nullptr;
std::atomic<uint64_t> rf_deferred_counter{1};

std::string g_last_fatal;   // en el SDK esto es REXSYS_FATAL; aquí lo capturamos para comprobarlo.

void rf_fatal_from_catch(const std::exception& e) {
  char buf[256];
  std::snprintf(buf, sizeof(buf),
                "[FATAL] Dispatch thread: deferred completion (task %llu phase=%s ra=%016llX) threw '%s'",
                (unsigned long long)rf_active_deferred.id, rf_active_deferred.phase,
                (unsigned long long)reinterpret_cast<uintptr_t>(rf_active_deferred.ra), e.what());
  g_last_fatal = buf;
  std::printf("%s\n", buf);
}

// Imita el lambda que empuja CompleteDeferred, con las cuatro fases.
std::function<void()> make_task(uint64_t id, const void* ra, uint32_t overlapped,
                                std::function<void()> pre, std::function<void()> work,
                                std::function<void()> post) {
  return [=]() mutable {
    rf_active_deferred = RfDeferredTag{id, ra, overlapped, "pre"};
    std::printf("[deferred] run id=%llu overlapped=%08X\n", (unsigned long long)id, overlapped);
    if (pre) pre();
    rf_active_deferred.phase = "work";
    if (work) work();
    rf_active_deferred.phase = "complete";
    std::printf("[deferred] done id=%llu result=00000000\n", (unsigned long long)id);
    if (post) { rf_active_deferred.phase = "post"; post(); }
    rf_active_deferred = RfDeferredTag{};
  };
}

// Imita el bucle del hilo despachador: saca cada tarea y la ejecuta en un try/catch.
void run_dispatch(std::deque<std::function<void()>>& q) {
  while (!q.empty()) {
    auto fn = std::move(q.front());
    q.pop_front();
    try { fn(); }
    catch (const std::exception& e) { rf_fatal_from_catch(e); }
  }
}
}  // namespace

static int g_checks = 0, g_fail = 0;
static void check(bool cond, const char* msg) {
  std::printf(cond ? "  OK  %s\n" : "  FAIL %s\n", msg);
  ++g_checks; if (!cond) ++g_fail;
}

int main() {
  std::deque<std::function<void()>> q;
  const uint32_t shared = 0x41F0FF50;  // misma dirección que reutilizan las dos tareas del 121

  // Tarea 1: termina bien (sin excepción) en la dirección compartida.
  q.push_back(make_task(1, (const void*)0x1000, shared, nullptr, nullptr, nullptr));
  // Tarea 2: MISMA dirección; lanza en la fase POST (no en work) para comprobar la fase.
  q.push_back(make_task(2, (const void*)0x2abc, shared, nullptr, nullptr,
                        [] { throw std::runtime_error("Invalid UTF-8"); }));

  run_dispatch(q);

  std::printf("--- comprobaciones ---\n");
  check(g_last_fatal.find("task 2 ") != std::string::npos, "el fatal culpa a la tarea 2 (no a la 1, misma direccion)");
  check(g_last_fatal.find("phase=post") != std::string::npos, "la excepcion en post se registra con fase=post");
  check(g_last_fatal.find("ra=0000000000002ABC") != std::string::npos, "conserva el ra del encolador de la tarea 2");
  check(g_last_fatal.find("'Invalid UTF-8'") != std::string::npos, "conserva el mensaje de la excepcion");

  // Tarea que lanza en WORK: la fase debe ser work.
  g_last_fatal.clear();
  std::deque<std::function<void()>> q2;
  q2.push_back(make_task(7, (const void*)0x7777, 0xDEAD0000, nullptr,
                         [] { throw std::runtime_error("boom"); }, nullptr));
  run_dispatch(q2);
  check(g_last_fatal.find("task 7 ") != std::string::npos && g_last_fatal.find("phase=work") != std::string::npos,
        "una excepcion en work se registra con fase=work y el id correcto");

  std::printf("\n%s (%d/%d)\n", g_fail ? "HAY FALLOS" : "TODO OK", g_checks - g_fail, g_checks);
  return g_fail ? 1 : 0;
}
