# build_diag_runtime.ps1 — PowerShell 5.1
# Aplica el parche de traza, compila un rexruntime.dll de DIAGNOSTICO (con simbolos), lo coloca en una carpeta
# aparte (sin tocar tu instalacion, TU ni partidas) y hace UNA captura. Con el runtime instrumentado, la traza
# [deferred] sale a nivel WARN: el log ya identifica quien encola la tarea que lanza, sin depurador.
#
# Requisitos: el SDK en C:\ReForgeBuild\rexglue-sdk (rev. gbd833a2-fsr), CMake+Ninja+Clang (los del Taller), y el
# proyecto de Asura compilado. Si falta algo, el script lo dice ANTES de arrancar.
$ErrorActionPreference = 'Stop'
$sdk   = 'C:\ReForgeBuild\rexglue-sdk'
$proj  = 'C:\Users\roger\ReForgeProjects\asura_s_wrath'
$disp  = Join-Path $sdk 'src\kernel\dispatcher.cpp'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$diag  = Join-Path $proj ("diag_asura_" + $stamp)
New-Item -ItemType Directory -Force -Path $diag | Out-Null
function Need($cond,$msg){ if(-not $cond){ Write-Error "FALTA: $msg"; exit 1 } }

Write-Host "== Requisitos =="
Need (Test-Path $disp) "dispatcher.cpp en $sdk"
Need (Test-Path (Join-Path $proj 'build\asuraswrath.exe')) "asuraswrath.exe compilado"
Need (Get-Command cmake -ErrorAction SilentlyContinue) "cmake en PATH"
# Revision del SDK (para confirmar que es la de tu runtime, gbd833a2)
try { $rev = (& git -C $sdk rev-parse --short HEAD) 2>$null } catch { $rev = '?' }
Write-Host ("SDK rev: {0}  (tu runtime es 0.10.0.24-dev.gbd833a2-fsr)" -f $rev)
$rev | Out-File (Join-Path $diag 'sdk_rev.txt')

Write-Host "== 1) Aplicar el parche de traza (con copia de seguridad) =="
Copy-Item $disp "$disp.bak_$stamp" -Force
$src = Get-Content $disp -Raw
if($src -notmatch 'rf_deferred_counter'){
  # 1. estado de traza, tras el primer #include "..."
  $src = $src -replace '(#include[^\r\n]*\r?\n)(?!#include)', ('$1' + @"
#include <cstdint>
namespace {
struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; };
thread_local RfDeferredTag rf_active_deferred{};
thread_local const void* rf_enqueue_ra = nullptr;
std::atomic<uint64_t> rf_deferred_counter{1};
}  // namespace
#define RF_RETURN_ADDRESS() __builtin_return_address(0)
"@ ), 1
  # 2. encolado: insertar enqueue-log antes del REXSYS_DEBUG("CompleteDeferred: queuing...
  $src = $src.Replace(
'  REXSYS_DEBUG("CompleteDeferred: queuing for overlapped {:08X}", overlapped);',
@"
  const uint64_t rf_task_id = rf_deferred_counter.fetch_add(1);
  const void* rf_ra = rf_enqueue_ra ? rf_enqueue_ra : RF_RETURN_ADDRESS();
  rf_enqueue_ra = nullptr;
  REXSYS_WARN("[deferred] enqueue id={} ra={:016X} thread={:08X} overlapped={:08X}", rf_task_id,
              reinterpret_cast<uintptr_t>(rf_ra),
              static_cast<uint32_t>(reinterpret_cast<uintptr_t>(KernelThread::GetCurrentThreadHandle())),
              overlapped);
  REXSYS_DEBUG("CompleteDeferred: queuing for overlapped {:08X}", overlapped);
"@)
  # 2b. capturar id/ra en el lambda y marcar la tarea activa + log run
  $src = $src.Replace(
@"
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post)]() mutable {
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
"@,
@"
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post), rf_task_id, rf_ra]() mutable {
    rf_active_deferred = RfDeferredTag{rf_task_id, rf_ra, overlapped};
    REXSYS_WARN("[deferred] run id={} overlapped={:08X}", rf_task_id, overlapped);
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
"@)
  # 2c. log done + limpiar la tarea activa, tras CompleteOverlappedEx
  $src = $src.Replace(
@"
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    if (post) {
"@,
@"
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    REXSYS_WARN("[deferred] done id={} result={:08X}", rf_task_id, options.result);
    rf_active_deferred = RfDeferredTag{};
    if (post) {
"@)
  # 3. marcar el ra real en la sobrecarga void(work)
  $src = $src.Replace(
@"
                                  rex::MoveOnlyFunction<void()> post) {
  CompleteDeferred(
      overlapped,
"@,
@"
                                  rex::MoveOnlyFunction<void()> post) {
  rf_enqueue_ra = RF_RETURN_ADDRESS();
  CompleteDeferred(
      overlapped,
"@)
  # 4. nombrar la tarea activa en el fatal
  $src = $src.Replace(
'        REXSYS_FATAL("Dispatch thread: deferred completion threw ''{}''", e.what());',
@"
        REXSYS_FATAL("Dispatch thread: deferred completion (task {} ra={:016X}) threw '{}'",
                     rf_active_deferred.id, reinterpret_cast<uintptr_t>(rf_active_deferred.ra), e.what());
"@)
  Set-Content $disp $src -Encoding UTF8 -NoNewline
  Write-Host "Parche aplicado."
} else { Write-Host "Ya estaba parcheado; se reutiliza." }
Copy-Item $disp (Join-Path $diag 'dispatcher.patched.cpp') -Force

Write-Host "== 2) Compilar rexruntime (RelWithDebInfo, con simbolos) =="
# Usa tu configuracion del SDK. Ajusta --preset si usas otro nombre; se listan los disponibles:
& cmake --list-presets 2>&1 | Tee-Object (Join-Path $diag 'cmake_presets.txt')
$build = Join-Path $sdk 'out\build\win-amd64-reldbg'
& cmake -S $sdk -B $build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo 2>&1 | Tee-Object (Join-Path $diag 'cmake_configure.txt')
& cmake --build $build --target rexruntime 2>&1 | Tee-Object (Join-Path $diag 'cmake_build.txt')
$newdll = Get-ChildItem $build -Recurse -Filter rexruntime.dll | Sort LastWriteTime -desc | Select -First 1
Need ($newdll) "no se genero rexruntime.dll (mira cmake_build.txt)"
$newpdb = Get-ChildItem $build -Recurse -Filter rexruntime.pdb -ErrorAction SilentlyContinue | Sort LastWriteTime -desc | Select -First 1
Write-Host ("DLL de diagnostico: {0}" -f $newdll.FullName)

Write-Host "== 3) Carpeta de ejecucion aparte (no toca tu build/instalacion) =="
$run = Join-Path $diag 'run'
Copy-Item (Join-Path $proj 'build') $run -Recurse -Force
Copy-Item $newdll.FullName (Join-Path $run 'rexruntime.dll') -Force
if($newpdb){ Copy-Item $newpdb.FullName (Join-Path $run 'rexruntime.pdb') -Force }
Get-FileHash (Join-Path $run 'rexruntime.dll') -Algorithm SHA256 | Tee-Object (Join-Path $diag 'runtime_dll.sha256.txt')

Write-Host "== 4) UN intento (sin supervisor ni reintentos; con la TU y tus assets) =="
$exe = Join-Path $run 'asuraswrath.exe'
$p = Start-Process $exe -ArgumentList "--game_data_root=$proj\assets" -WorkingDirectory $run -PassThru
# Modulos y bases REALES cargados por el proceso (para simbolizar el ra):
Start-Sleep -Seconds 8
try { $p.Refresh(); $p.Modules | Where-Object { $_.ModuleName -match 'rexruntime|asuraswrath' } |
      Select ModuleName, FileName, @{n='Base';e={('0x{0:X}' -f $_.BaseAddress.ToInt64())}} |
      Format-Table -Auto | Out-String | Tee-Object (Join-Path $diag 'modules.txt') } catch {}
$p.WaitForExit()
"PID=$($p.Id)  exit=0x{0:X8}  hora_fin={1}" -f $p.ExitCode,(Get-Date) | Tee-Object (Join-Path $diag 'resultado.txt')

Write-Host "== 5) Recoger el log de ESTE intento y la traza de tareas =="
$log = Get-ChildItem (Join-Path $run 'logs\*.log') | Sort LastWriteTime -desc | Select -First 1
Copy-Item $log.FullName (Join-Path $diag 'session.log')
Select-String $log.FullName -Pattern '\[deferred\]|Invalid UTF-8|deferred completion|XamContent|XNetLogon' |
  Select -Last 80 | ForEach-Object { $_.Line } | Tee-Object (Join-Path $diag 'task_trace.txt')
Compress-Archive -Path "$diag\*" -DestinationPath "$diag.zip" -Force
Write-Host ""
Write-Host "LISTO. Devuelve: $diag.zip"
Write-Host "   (contiene session.log, task_trace.txt con las lineas [deferred], modules.txt con las bases,"
Write-Host "    runtime_dll.sha256.txt, y el dispatcher.patched.cpp)"
