# build_diag_runtime.ps1  -  Windows PowerShell 5.1
# Compila un rexruntime.dll de DIAGNOSTICO (instrumentado) desde una COPIA AISLADA del SDK, lo ejecuta en una
# carpeta aparte (sin tocar tu instalacion, TU ni partidas) y arma un ZIP SOLO con el diagnostico.
# Probado por Claude en tu PC: aplicacion del parche (4 cambios, 1 vez cada uno) y el mecanismo C++ (selftest 5/5).
# Lo que corre aqui y NO se ha probado en tu equipo: la compilacion completa de rexruntime.dll y el arranque.
$ErrorActionPreference = 'Stop'
$sdk   = 'C:\ReForgeBuild\rexglue-sdk'
$proj  = 'C:\Users\roger\ReForgeProjects\asura_s_wrath'
$clang = 'C:\Program Files\LLVM\bin'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$diag  = Join-Path $proj ("diag_asura_" + $stamp)        # SOLO diagnostico (lo que devuelves)
$sdkc  = Join-Path $env:TEMP ("rf_sdk_diag_" + $stamp)   # copia aislada del SDK (fuente)
$build = Join-Path $sdkc 'out\build\diag'                # directorio de compilacion NUEVO
$run   = Join-Path $diag 'run'                           # carpeta de ejecucion (NO entra al ZIP)
New-Item -ItemType Directory -Force -Path $diag | Out-Null
function Need($c,$m){ if(-not $c){ Write-Error "FALTA: $m"; exit 2 } }

Write-Host "== Requisitos (se comprueban ANTES de arrancar) =="
Need (Test-Path (Join-Path $sdk 'src\kernel\dispatcher.cpp')) "SDK en $sdk"
Need (Test-Path (Join-Path $proj 'build\asuraswrath.exe')) "asuraswrath.exe compilado"
Need (Get-Command cmake -ErrorAction SilentlyContinue) "cmake en PATH"
Need (Get-Command ninja -ErrorAction SilentlyContinue) "ninja en PATH"
Need (Test-Path (Join-Path $clang 'clang++.exe')) "clang en $clang"
# Revision del SDK (sin depender de git en PATH: usamos el .git/HEAD y packed-refs si estan)
$rev = '?'; $head = Join-Path $sdk '.git\HEAD'
if (Test-Path $head) { $rev = (Get-Content $head -Raw).Trim() }
"SDK HEAD: $rev   (tu runtime cargado es 0.10.0.24-dev.gbd833a2-fsr)" | Tee-Object (Join-Path $diag 'sdk_rev.txt')
# Variante -fsr = REXGLUE_ENABLE_FIDELITYFX ON (confirmado en tu CMakeCache)
$fx = 'ON'

Write-Host "== 1) Copia AISLADA del SDK (sin out\ ni .git\) =="
# robocopy: /MIR espeja; se excluyen artefactos de compilacion y el repo git para que sea solo fuente.
$null = robocopy $sdk $sdkc /E /NFL /NDL /NJH /NJS /NP /XD (Join-Path $sdk 'out') (Join-Path $sdk '.git')
if ($LASTEXITCODE -ge 8) { Write-Error "robocopy fallo ($LASTEXITCODE)"; exit 3 }
$disp = Join-Path $sdkc 'src\kernel\dispatcher.cpp'
Need (Test-Path $disp) "no se copio dispatcher.cpp"

Write-Host "== 2) Aplicar el parche de traza (4 cambios, 1 vez cada uno) =="
$s = (Get-Content $disp -Raw) -replace "`r`n", "`n"
function Apply1([string]$old,[string]$new,[string]$name){
  $n = ([regex]::Matches($script:s,[regex]::Escape($old))).Count
  if($n -ne 1){ throw "cambio '$name': se esperaba 1 ancla, hay $n" }
  $script:s = $script:s.Replace($old,$new); Write-Host "  '$name' aplicado (1 vez)"
}
$state = (@'
#include <cstdint>
namespace {
struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; const char* phase = "idle"; };
thread_local RfDeferredTag rf_active_deferred{};
thread_local const void* rf_enqueue_ra = nullptr;
std::atomic<uint64_t> rf_deferred_counter{1};
}  // namespace
#define RF_RETURN_ADDRESS() __builtin_return_address(0)

'@) -replace "`r`n","`n"
$sig = 'void Dispatcher::CompleteDeferred(u32 overlapped, rex::MoveOnlyFunction<void()> work,'
Apply1 $sig ($state + $sig) 'estado-de-traza'
$bodyOld = (@'
                                  rex::MoveOnlyFunction<void()> post) {
  CompleteDeferred(
      overlapped,
'@) -replace "`r`n","`n"
$bodyNew = (@'
                                  rex::MoveOnlyFunction<void()> post) {
  rf_enqueue_ra = RF_RETURN_ADDRESS();
  CompleteDeferred(
      overlapped,
'@) -replace "`r`n","`n"
Apply1 $bodyOld $bodyNew 'ra-en-primera-sobrecarga'
$lamOld = (@'
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post)]() mutable {
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
    if (pre) {
      pre();
    }
    REXSYS_DEBUG("Deferred overlapped {:08X}: sleeping {}ms", overlapped,
                 kDeferredOverlappedDelayMillis);
    rex::platform::SleepFor(std::chrono::milliseconds(kDeferredOverlappedDelayMillis));
    REXSYS_DEBUG("Deferred overlapped {:08X}: running completion", overlapped);
    const CompletionOptions options = work();
    REXSYS_DEBUG("Deferred overlapped {:08X}: completing with result {:08X}", overlapped,
                 options.result);
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    if (post) {
      REXSYS_DEBUG("Deferred overlapped {:08X}: running post", overlapped);
      post();
    }
  });
'@) -replace "`r`n","`n"
$lamNew = (@'
  const uint64_t rf_task_id = rf_deferred_counter.fetch_add(1);
  const void* rf_ra = rf_enqueue_ra ? rf_enqueue_ra : RF_RETURN_ADDRESS();
  rf_enqueue_ra = nullptr;
  REXSYS_WARN("[deferred] enqueue id={} ra={:016X} thread={:08X} overlapped={:08X}", rf_task_id,
              reinterpret_cast<uintptr_t>(rf_ra),
              static_cast<uint32_t>(reinterpret_cast<uintptr_t>(KernelThread::GetCurrentThreadHandle())),
              overlapped);
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post), rf_task_id, rf_ra]() mutable {
    rf_active_deferred = RfDeferredTag{rf_task_id, rf_ra, overlapped, "pre"};
    REXSYS_WARN("[deferred] run id={} overlapped={:08X}", rf_task_id, overlapped);
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
    if (pre) {
      pre();
    }
    REXSYS_DEBUG("Deferred overlapped {:08X}: sleeping {}ms", overlapped,
                 kDeferredOverlappedDelayMillis);
    rex::platform::SleepFor(std::chrono::milliseconds(kDeferredOverlappedDelayMillis));
    rf_active_deferred.phase = "work";
    REXSYS_DEBUG("Deferred overlapped {:08X}: running completion", overlapped);
    const CompletionOptions options = work();
    rf_active_deferred.phase = "complete";
    REXSYS_DEBUG("Deferred overlapped {:08X}: completing with result {:08X}", overlapped,
                 options.result);
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    REXSYS_WARN("[deferred] done id={} result={:08X}", rf_task_id, options.result);
    if (post) {
      rf_active_deferred.phase = "post";
      REXSYS_DEBUG("Deferred overlapped {:08X}: running post", overlapped);
      post();
    }
    rf_active_deferred = RfDeferredTag{};
  });
'@) -replace "`r`n","`n"
Apply1 $lamOld $lamNew 'lambda-instrumentado'
$fatOld = "        REXSYS_FATAL(""Dispatch thread: deferred completion threw '{}'"", e.what());"
$fatNew = (@'
        REXSYS_FATAL("Dispatch thread: deferred completion (task {} phase={} ra={:016X}) threw '{}'",
                     rf_active_deferred.id, rf_active_deferred.phase,
                     reinterpret_cast<uintptr_t>(rf_active_deferred.ra), e.what());
'@) -replace "`r`n","`n"
Apply1 $fatOld $fatNew 'fatal-con-id-y-fase'
foreach($m in @('rf_deferred_counter{1};','[deferred] enqueue id=','rf_active_deferred.phase = "work";','rf_active_deferred.phase = "post";','deferred completion (task {} phase={} ra={:016X}) threw')){
  if(([regex]::Matches($s,[regex]::Escape($m))).Count -ne 1){ throw "marca '$m' no quedo exactamente 1 vez" } }
Set-Content $disp $s -Encoding UTF8 -NoNewline
Copy-Item $disp (Join-Path $diag 'dispatcher.patched.cpp') -Force
Write-Host "Parche OK."

Write-Host "== 3) Configurar (directorio NUEVO) y compilar rexruntime (RelWithDebInfo, con simbolos) =="
$env:PATH = "$clang;$env:PATH"
& cmake -S $sdkc -B $build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DREXGLUE_ENABLE_FIDELITYFX=$fx `
        -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ 2>&1 | Tee-Object (Join-Path $diag 'cmake_configure.txt')
if ($LASTEXITCODE -ne 0) { Write-Host "CONFIGURE FALLO ($LASTEXITCODE). Se entregan los logs, NO se lanza el juego."; Compress-Archive -Path (Join-Path $diag '*') -DestinationPath "$diag.zip" -Force; Write-Host "Devuelve: $diag.zip"; exit 4 }
& cmake --build $build --target rexruntime 2>&1 | Tee-Object (Join-Path $diag 'cmake_build.txt')
if ($LASTEXITCODE -ne 0) { Write-Host "BUILD FALLO ($LASTEXITCODE). Se entregan los logs, NO se lanza el juego."; Compress-Archive -Path (Join-Path $diag '*') -DestinationPath "$diag.zip" -Force; Write-Host "Devuelve: $diag.zip"; exit 5 }
$newdll = Get-ChildItem $build -Recurse -Filter rexruntime.dll | Sort-Object LastWriteTime -desc | Select-Object -First 1
$newpdb = Get-ChildItem $build -Recurse -Filter rexruntime.pdb -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -desc | Select-Object -First 1
Need $newdll "no se genero rexruntime.dll (ver cmake_build.txt)"
Need $newpdb "no se generaron simbolos rexruntime.pdb (hace falta RelWithDebInfo)"

Write-Host "== 4) Ejecutar UN intento en carpeta aparte, con logs VACIOS (sin supervisor ni reintentos) =="
Copy-Item (Join-Path $proj 'build') $run -Recurse -Force
Copy-Item $newdll.FullName (Join-Path $run 'rexruntime.dll') -Force
Copy-Item $newpdb.FullName (Join-Path $run 'rexruntime.pdb') -Force
Get-FileHash (Join-Path $run 'rexruntime.dll') -Algorithm SHA256 | Tee-Object (Join-Path $diag 'runtime_dll.sha256.txt')
$rlogs = Join-Path $run 'logs'; if (Test-Path $rlogs) { Remove-Item (Join-Path $rlogs '*') -Force -ErrorAction SilentlyContinue } else { New-Item -ItemType Directory -Force -Path $rlogs | Out-Null }
$exe = Join-Path $run 'asuraswrath.exe'
$p = Start-Process $exe -ArgumentList "--game_data_root=$proj\assets" -WorkingDirectory $run -PassThru
Start-Sleep -Seconds 8
try { $p.Refresh(); $p.Modules | Where-Object { $_.ModuleName -match 'rexruntime|asuraswrath' } |
      Select-Object ModuleName, FileName, @{n='Base';e={('0x{0:X}' -f $_.BaseAddress.ToInt64())}}, @{n='Size';e={$_.ModuleMemorySize}} |
      Format-Table -Auto | Out-String | Tee-Object (Join-Path $diag 'modules.txt') } catch {}
$p.WaitForExit()
"PID=$($p.Id)  exit=0x{0:X8}  hora_fin={1}" -f $p.ExitCode,(Get-Date) | Tee-Object (Join-Path $diag 'resultado.txt')

Write-Host "== 5) Recoger SOLO el diagnostico =="
$log = Get-ChildItem $rlogs -Filter *.log | Sort-Object LastWriteTime -desc | Select-Object -First 1
Need $log "la sesion no genero log"
Copy-Item $log.FullName (Join-Path $diag 'session.log')
Select-String $log.FullName -Pattern '\[deferred\]|Invalid UTF-8|deferred completion|XamContent|XNetLogon|\[render\]' |
  ForEach-Object { $_.Line } | Tee-Object (Join-Path $diag 'task_trace.txt')
Get-FileHash $exe -Algorithm SHA256 | Tee-Object (Join-Path $diag 'exe.sha256.txt')

# ZIP por LISTA EXPLICITA: solo diagnostico. Se EXCLUYE run\ (juego, DLL, TU, partidas, build) y la .cpp pesada no entra.
$include = 'sdk_rev.txt','cmake_configure.txt','cmake_build.txt','runtime_dll.sha256.txt','exe.sha256.txt',
           'modules.txt','resultado.txt','task_trace.txt','session.log','dispatcher.patched.cpp'
$zipItems = @(); foreach($f in $include){ $pth = Join-Path $diag $f; if(Test-Path $pth){ $zipItems += $pth } }
$zip = "$diag.zip"; if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $zipItems -DestinationPath $zip -Force
Write-Host ""
Write-Host "== Contenido del ZIP (antes de compartir) =="
Add-Type -AssemblyName System.IO.Compression.FileSystem
$za = [System.IO.Compression.ZipFile]::OpenRead($zip)
$za.Entries | ForEach-Object { "{0,10}  {1}" -f $_.Length, $_.FullName }
$za.Dispose()
"{0:N0} bytes total" -f (Get-Item $zip).Length
Write-Host ""
Write-Host "Devuelve SOLO este archivo: $zip"
Write-Host "Limpieza opcional de la copia del SDK: Remove-Item -Recurse -Force '$sdkc' ; Remove-Item -Recurse -Force '$run'"
