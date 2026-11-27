# build_diag_runtime.ps1  -  Windows PowerShell 5.1
# Compila un rexruntime.dll de DIAGNOSTICO (instrumentado) de la version EXACTA que carga tu juego:
# 0.10.1 (commit bd833a2a = runtime 0.10.0.24-dev.gbd833a2). Reconstruye ese arbol OFFLINE desde tus
# objetos git locales (sin red, sin tocar tu SDK en 0.11 ni sus cambios sin commit), aplica el parche de
# traza a src/system/kernel_state.cpp (fatal REX_FATAL, encolador CompleteOverlappedDeferredEx), compila,
# ejecuta UN intento en carpeta aparte y arma un ZIP SOLO con el diagnostico (sin juego, DLL, TU ni partidas).
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

# Resuelve una herramienta por rutas explicitas (como las del CMakeCache original) y, si no, por PATH.
function ResolveTool([string]$name,[string[]]$cands){
  foreach($c in $cands){ if($c -and (Test-Path $c)){ return (Resolve-Path $c).Path } }
  $g = Get-Command $name -ErrorAction SilentlyContinue
  if($g){ return $g.Source }
  return $null
}
Write-Host "== Requisitos (se comprueban ANTES de arrancar) =="
Need (Test-Path (Join-Path $sdk '.git')) "repo git del SDK en $sdk"
Need (Test-Path (Join-Path $proj 'build\asuraswrath.exe')) "asuraswrath.exe compilado"
# cmake/ninja NO suelen estar en el PATH: vienen con Visual Studio. Se resuelven por ruta explicita.
$cmakeExe = ResolveTool 'cmake' @(
  'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\CMake\bin\cmake.exe')
$ninjaExe = ResolveTool 'ninja' @(
  'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe',
  'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe',
  'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe')
Need $cmakeExe "cmake (ni en rutas de Visual Studio/CMake conocidas ni en PATH)"
Need $ninjaExe "ninja (ni en rutas de Visual Studio conocidas ni en PATH)"
Need (Test-Path (Join-Path $clang 'clang++.exe')) "clang en $clang"
Write-Host "  cmake: $cmakeExe"
Write-Host "  ninja: $ninjaExe"
# git (GitHub Desktop no lo pone en PATH): se resuelve por ruta explicita.
$gitExe = ResolveTool 'git' @(
  'C:\Users\roger\AppData\Local\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe',
  'C:\Program Files\Git\cmd\git.exe')
Need $gitExe "git (GitHub Desktop o Git for Windows)"
# Tu juego carga rexruntime.dll 0.10.0.24-dev.gbd833a2 = commit bd833a2a (tag v0.10.1). Instrumentamos ESA.
$rev0101 = 'bd833a2a'
Need ((& $gitExe -C $sdk cat-file -t $rev0101 2>&1) -eq 'commit') "el commit $rev0101 (v0.10.1) no esta en tu repo"
"Instrumentando 0.10.1 ($rev0101); tu juego carga 0.10.0.24-dev.gbd833a2. Tu SDK esta en 0.11 y NO se toca." | Tee-Object (Join-Path $diag 'sdk_rev.txt')
# FidelityFX (-fsr) se baja por FetchContent (red) en configure y NO esta en objetos locales, asi que para
# quedarnos OFFLINE lo dejamos OFF. Es irrelevante para este cierre: es GPU/upscaling (vive en rexgpu y en el
# amd_fidelityfx_dx12.dll instalado, que no tocamos), y rexruntime ni siquiera lo enlaza. El kernel/XAM/UTF-8
# (donde ocurre el fatal) es byte-identico con o sin FSR: misma rama de codigo del commit 0.10.1.
$fx = 'OFF'

Write-Host "== 1) Reconstruir el arbol 0.10.1 OFFLINE (superproyecto + submodulos desde objetos locales) =="
New-Item -ItemType Directory -Force -Path $sdkc | Out-Null
# Extrae un commit a $dest via 'git archive' + Expand-Archive. $asGitDir=$true para un object store (.git/modules/...).
function GitArchiveTo([string]$repo,[string]$rev,[string]$dest,[bool]$asGitDir){
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  $z = Join-Path $env:TEMP ("rfarc_" + [guid]::NewGuid().ToString('N') + ".zip")
  if($asGitDir){ & $gitExe --git-dir=$repo archive --format=zip -o $z $rev 2>&1 | Out-Null }
  else { & $gitExe -C $repo archive --format=zip -o $z $rev 2>&1 | Out-Null }
  if($LASTEXITCODE -ne 0 -or -not (Test-Path $z)){ return $false }
  Expand-Archive -Path $z -DestinationPath $dest -Force
  Remove-Item $z -Force -ErrorAction SilentlyContinue
  return $true
}
# 1a) superproyecto 0.10.1 (solo archivos versionados; sin submodulos, sin .git)
$okSuper = GitArchiveTo $sdk $rev0101 $sdkc $false
Need $okSuper "no se pudo extraer el superproyecto 0.10.1 (offline)"
# 1b) submodulos: commit esperado @0.10.1 y commit actual en tu arbol principal
$subs = @{}; (& $gitExe -C $sdk ls-tree -r $rev0101) | ForEach-Object { if($_ -match '^160000 commit ([0-9a-f]+)\s+(.+)$'){ $subs[$matches[2]] = $matches[1] } }
$cur  = @{}; (& $gitExe -C $sdk submodule status) | ForEach-Object { if($_ -match '^(.)([0-9a-f]+)\s+(\S+)'){ $cur[$matches[3]] = @{sha=$matches[2];flag=$matches[1]} } }
foreach($path in ($subs.Keys | Sort-Object)){
  $want = $subs[$path]; $destSub = Join-Path $sdkc ($path -replace '/','\'); $h = $cur[$path]
  if($h -and $h.flag -ne '-' -and $h.sha -eq $want){
    # ya poblado en el commit correcto -> copiar el working dir (incluye submodulos anidados)
    $src = Join-Path $sdk ($path -replace '/','\')
    $null = robocopy $src $destSub /E /NFL /NDL /NJH /NJS /NP /XD '.git'
    if($LASTEXITCODE -ge 8){ Write-Error "copia de submodulo $path fallo ($LASTEXITCODE)"; exit 3 }
    Write-Host ("  {0} <- working dir (match {1})" -f $path, $want.Substring(0,8))
  } else {
    # extraer el commit 0.10.1 desde el object store LOCAL del submodulo (offline, sin red)
    $store = Join-Path $sdk ('.git\modules\' + ($path -replace '/','\'))
    Need (Test-Path $store) "object store local de $path ausente (necesitaria red; usa la opcion 3)"
    $okSub = GitArchiveTo $store $want $destSub $true
    Need $okSub "no se pudo extraer $path @$($want.Substring(0,8)) offline (necesitaria red)"
    Write-Host ("  {0} <- object store (commit {1})" -f $path, $want.Substring(0,8))
  }
  # El SDK valida submodulos con 'if(NOT EXISTS <sub>/.git)' (thirdparty/CMakeLists.txt). La copia de working
  # dir ya trae ese archivo; para la extraida del object store lo creamos (solo centinela, no es un repo).
  $dotgit = Join-Path $destSub '.git'
  if(-not (Test-Path $dotgit)){ Set-Content $dotgit "rf-diag offline (centinela, no es un repo git)" -Encoding ASCII }
}
$disp = Join-Path $sdkc 'src\system\kernel_state.cpp'
Need (Test-Path $disp) "no se reconstruyo src/system/kernel_state.cpp (0.10.1)"

Write-Host "== 2) Aplicar el parche de traza a kernel_state.cpp (7 cambios, 1 vez cada uno) =="
$s = (Get-Content $disp -Raw) -replace "`r`n", "`n"
function Apply1([string]$old,[string]$new,[string]$name){
  $n = ([regex]::Matches($script:s,[regex]::Escape($old))).Count
  if($n -ne 1){ throw "cambio '$name': se esperaba 1 ancla, hay $n" }
  $script:s = $script:s.Replace($old,$new); Write-Host "  '$name' aplicado (1 vez)"
}
$state = (@'
#include <atomic>
#include <cstdint>
namespace {
struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; const char* phase = "idle"; };
thread_local RfDeferredTag rf_active_deferred{};
std::atomic<uint64_t> rf_deferred_counter{1};
}  // namespace
#define RF_RETURN_ADDRESS() __builtin_return_address(0)

'@) -replace "`r`n","`n"
# El bucle del hilo de despacho y su REX_FATAL estan ANTES de CompleteOverlappedDeferredEx, asi que el estado de
# traza se declara a ambito de archivo (tras este include), para estar en alcance tanto en el fatal como en el lambda.
$ksInc = '#include <rex/system/kernel_state.h>'
Apply1 $ksInc ($ksInc + "`n" + $state) 'estado-de-traza'
# -- encolar: id/ra + log de encolado, justo antes del push_back --
$enqOld = (@'
  auto global_lock = global_critical_region_.Acquire();
  dispatch_queue_.push_back(
'@) -replace "`r`n","`n"
$enqNew = (@'
  const uint64_t rf_task_id = rf_deferred_counter.fetch_add(1);
  const void* rf_ra = RF_RETURN_ADDRESS();
  REXSYS_WARN("[deferred] enqueue id={} ra={:016X} thread={:08X} overlapped={:08X}", rf_task_id,
              reinterpret_cast<uintptr_t>(rf_ra),
              XThread::GetCurrentThreadHandle(),
              overlapped_ptr);
  auto global_lock = global_critical_region_.Acquire();
  dispatch_queue_.push_back(
'@) -replace "`r`n","`n"
Apply1 $enqOld $enqNew 'encolado-id-ra'
# -- captura en el lambda + fase "pre" + log run --
$capOld = '      [this, completion_callback, overlapped_ptr, pre_callback, post_callback]() {'
$capNew = (@'
      [this, completion_callback, overlapped_ptr, pre_callback, post_callback, rf_task_id, rf_ra]() {
        rf_active_deferred = RfDeferredTag{rf_task_id, rf_ra, overlapped_ptr, "pre"};
        REXSYS_WARN("[deferred] run id={} overlapped={:08X}", rf_task_id, overlapped_ptr);
'@) -replace "`r`n","`n"
Apply1 $capOld $capNew 'captura-lambda-y-pre'
# -- fase "work" tras el sleep --
$workOld = '        rex::thread::Sleep(std::chrono::milliseconds(kDeferredOverlappedDelayMillis));'
$workNew = (@'
        rex::thread::Sleep(std::chrono::milliseconds(kDeferredOverlappedDelayMillis));
        rf_active_deferred.phase = "work";
'@) -replace "`r`n","`n"
Apply1 $workOld $workNew 'fase-work'
# -- fase "complete" tras la completion --
$compOld = '        auto result = completion_callback(extended_error, length);'
$compNew = (@'
        auto result = completion_callback(extended_error, length);
        rf_active_deferred.phase = "complete";
'@) -replace "`r`n","`n"
Apply1 $compOld $compNew 'fase-complete'
# -- log done + fase "post" + limpieza al final del lambda --
$postOld = (@'
        CompleteOverlappedEx(overlapped_ptr, result, extended_error, length);
        if (post_callback) {
          REXSYS_DEBUG("Deferred overlapped {:08X}: running post_callback", overlapped_ptr);
          post_callback();
        }
      });
'@) -replace "`r`n","`n"
$postNew = (@'
        CompleteOverlappedEx(overlapped_ptr, result, extended_error, length);
        REXSYS_WARN("[deferred] done id={} result={:08X}", rf_task_id, result);
        if (post_callback) {
          rf_active_deferred.phase = "post";
          REXSYS_DEBUG("Deferred overlapped {:08X}: running post_callback", overlapped_ptr);
          post_callback();
        }
        rf_active_deferred = RfDeferredTag{};
      });
'@) -replace "`r`n","`n"
Apply1 $postOld $postNew 'done-post-limpieza'
# -- fatal con id, fase y ra (ancla sin sangria para ser robusta) --
$fatOld = "REX_FATAL(""Dispatch thread: deferred completion threw '{}'"", e.what());"
$fatNew = (@'
REX_FATAL("Dispatch thread: deferred completion (task {} phase={} ra={:016X}) threw '{}'",
                    rf_active_deferred.id, rf_active_deferred.phase,
                    reinterpret_cast<uintptr_t>(rf_active_deferred.ra), e.what());
'@) -replace "`r`n","`n"
Apply1 $fatOld $fatNew 'fatal-con-id-y-fase'
foreach($m in @('rf_deferred_counter{1};','[deferred] enqueue id=','rf_active_deferred.phase = "work";','rf_active_deferred.phase = "post";','deferred completion (task {} phase={} ra={:016X}) threw')){
  if(([regex]::Matches($s,[regex]::Escape($m))).Count -ne 1){ throw "marca '$m' no quedo exactamente 1 vez" } }
Set-Content $disp $s -Encoding UTF8 -NoNewline
Copy-Item $disp (Join-Path $diag 'kernel_state.patched.cpp') -Force
# Quitar el sufijo 'rd' de RelWithDebInfo: si no, el runtime sale como rexruntimerd.dll y el plugin de GPU
# importa rexruntimerd.dll, pero el .exe del juego importa rexruntime.dll (sin sufijo) y no casan. Sin sufijo,
# runtime, plugin y exe usan el mismo nombre rexruntime.dll, como el build original.
$cmTop = Join-Path $sdkc 'CMakeLists.txt'
$cmTxt = (Get-Content $cmTop -Raw)
$cmNew = $cmTxt.Replace('set(CMAKE_RELWITHDEBINFO_POSTFIX rd)', 'set(CMAKE_RELWITHDEBINFO_POSTFIX "")')
if ($cmNew -eq $cmTxt) { Write-Error "FALTA: no se pudo quitar CMAKE_RELWITHDEBINFO_POSTFIX (ancla no encontrada)"; exit 2 }
Set-Content $cmTop $cmNew -Encoding UTF8 -NoNewline
Write-Host "Sufijo RelWithDebInfo quitado (DLLs sin 'rd')."
Write-Host "Parche OK."

Write-Host "== 3) Configurar (directorio NUEVO) y compilar rexruntime (RelWithDebInfo, con simbolos) =="
# clang y ninja al frente del PATH para que cmake los encuentre durante la compilacion.
$env:PATH = "$clang;$(Split-Path $ninjaExe);$env:PATH"
# IMPORTANTE (PS 5.1): cmake escribe avisos a stderr; con ErrorActionPreference='Stop' + '2>&1' esa linea de
# stderr se convierte en un error TERMINANTE (NativeCommandError) y aborta el script aunque el exit sea 0.
# Mandamos SOLO por el codigo de salida: bajamos a 'Continue' durante las llamadas nativas y lo restauramos.
$prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $cmakeExe -S $sdkc -B $build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo "-DREXGLUE_ENABLE_FIDELITYFX=$fx" `
        -DREXGLUE_BUILD_TESTS=OFF -DCMAKE_MAKE_PROGRAM="$ninjaExe" `
        -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ 2>&1 | Tee-Object (Join-Path $diag 'cmake_configure.txt')
$cfgExit = $LASTEXITCODE
if ($cfgExit -ne 0) { $ErrorActionPreference = $prevEAP; Write-Host "CONFIGURE FALLO ($cfgExit). Se entregan los logs, NO se lanza el juego."; Compress-Archive -Path (Join-Path $diag '*') -DestinationPath "$diag.zip" -Force; Write-Host "Devuelve: $diag.zip"; exit 4 }
# El juego carga el plugin de GPU 'xenos' (rexgpu-xenos.dll), que importa el runtime; hay que compilarlo tambien y
# ponerlo junto al runtime, o el juego no arranca y no se llega a la enumeracion de contenido (donde esta el cierre).
& $cmakeExe --build $build --target rexruntime --target rexgpu-xenos 2>&1 | Tee-Object (Join-Path $diag 'cmake_build.txt')
$bldExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($bldExit -ne 0) { Write-Host "BUILD FALLO ($bldExit). Se entregan los logs, NO se lanza el juego."; Compress-Archive -Path (Join-Path $diag '*') -DestinationPath "$diag.zip" -Force; Write-Host "Devuelve: $diag.zip"; exit 5 }
# Los binarios salen en out\<plataforma> (CMAKE_RUNTIME_OUTPUT_DIRECTORY), no dentro del build dir.
$outdir = Join-Path $sdkc 'out\win-amd64'
$newdll = Get-ChildItem $outdir -Filter 'rexruntime*.dll' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -desc | Select-Object -First 1
$newpdb = Get-ChildItem $outdir -Filter 'rexruntime*.pdb' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -desc | Select-Object -First 1
Need $newdll "no se genero rexruntime.dll (ver cmake_build.txt)"
Need $newpdb "no se generaron simbolos rexruntime.pdb (hace falta RelWithDebInfo)"

Write-Host "== 4) Ejecutar UN intento en carpeta aparte, con logs VACIOS (sin supervisor ni reintentos) =="
Copy-Item (Join-Path $proj 'build') $run -Recurse -Force
# Nuestro runtime + plugin de GPU + Tracy (todos sin sufijo, mismo commit) sobrescriben los del juego en la carpeta
# de ejecucion, para que TODO resuelva a nuestro build instrumentado (mismas exports, compatibles entre si).
Get-ChildItem $outdir -Filter '*.dll' | ForEach-Object { Copy-Item $_.FullName (Join-Path $run $_.Name) -Force }
Get-ChildItem $outdir -Filter '*.pdb' | ForEach-Object { Copy-Item $_.FullName (Join-Path $run $_.Name) -Force }
# El cargador de plugins del runtime pide el plugin con el sufijo del build-config (rexgpu-xenosrd.dll para
# RelWithDebInfo), aunque el archivo salga sin sufijo. Lo dejamos tambien con ese nombre para que lo encuentre.
if (Test-Path (Join-Path $run 'rexgpu-xenos.dll')) { Copy-Item (Join-Path $run 'rexgpu-xenos.dll') (Join-Path $run 'rexgpu-xenosrd.dll') -Force }
Get-FileHash (Join-Path $run 'rexruntime.dll') -Algorithm SHA256 | Tee-Object (Join-Path $diag 'runtime_dll.sha256.txt')
$rlogs = Join-Path $run 'logs'; if (Test-Path $rlogs) { Remove-Item (Join-Path $rlogs '*') -Force -ErrorAction SilentlyContinue } else { New-Item -ItemType Directory -Force -Path $rlogs | Out-Null }
$exe = Join-Path $run 'asuraswrath.exe'
$p = Start-Process $exe -ArgumentList "--game_data_root=$proj\assets" -WorkingDirectory $run -PassThru
Start-Sleep -Seconds 8
try { $p.Refresh(); $p.Modules | Where-Object { $_.ModuleName -match 'rexruntime|asuraswrath' } |
      Select-Object ModuleName, FileName, @{n='Base';e={('0x{0:X}' -f $_.BaseAddress.ToInt64())}}, @{n='Size';e={$_.ModuleMemorySize}} |
      Format-Table -Auto | Out-String | Tee-Object (Join-Path $diag 'modules.txt') } catch {}
# El cierre que buscamos ocurre pronto; si el juego NO cierra en 180s es que llego a menu/gameplay sin reproducirlo.
$exited = $p.WaitForExit(180000)
if (-not $exited) { Write-Host "El juego NO cerro en 180s (llego a menu/gameplay sin reproducir el cierre)."; try { $p.Kill() } catch {}; $p.WaitForExit() }
$exitTxt = if ($exited) { "0x{0:X8}" -f $p.ExitCode } else { "(vivo>180s, cerrado por el script)" }
"PID=$($p.Id)  exit=$exitTxt  salio_solo=$exited  hora_fin=$(Get-Date)" | Tee-Object (Join-Path $diag 'resultado.txt')

Write-Host "== 5) Recoger SOLO el diagnostico =="
$log = Get-ChildItem $rlogs -Filter *.log | Sort-Object LastWriteTime -desc | Select-Object -First 1
Need $log "la sesion no genero log"
Copy-Item $log.FullName (Join-Path $diag 'session.log')
Select-String $log.FullName -Pattern '\[deferred\]|Invalid UTF-8|deferred completion|XamContent|XNetLogon|\[render\]' |
  ForEach-Object { $_.Line } | Tee-Object (Join-Path $diag 'task_trace.txt')
Get-FileHash $exe -Algorithm SHA256 | Tee-Object (Join-Path $diag 'exe.sha256.txt')
# Simbolizar los 'ra' de los encoladores con el .pdb: nombra QUIEN encola cada tarea (y, si hubo fatal, su encolador).
# VA = ra - base_cargada + imagebase_del_PE (0x180000000 para estos DLL). base_cargada sale de modules.txt.
$symExe = Join-Path $clang 'llvm-symbolizer.exe'
$modLine = Select-String (Join-Path $diag 'modules.txt') -Pattern 'rexruntime\.dll.*?0x([0-9A-Fa-f]+)' -ErrorAction SilentlyContinue | Select-Object -First 1
if ((Test-Path $symExe) -and $modLine) {
  $base = [Convert]::ToUInt64($modLine.Matches.Groups[1].Value, 16); $runDll = Join-Path $run 'rexruntime.dll'
  $ras = Select-String $log.FullName -Pattern 'ra=([0-9A-Fa-f]{10,})' | ForEach-Object { $_.Matches.Groups[1].Value } | Sort-Object -Unique
  $symOut = @(); foreach ($r in $ras) { $va = [Convert]::ToUInt64($r,16) - $base + 0x180000000; $sr = (& $symExe --obj="$runDll" ("0x{0:X}" -f $va) 2>&1) -join ' | '; $symOut += ("ra={0}  RVA=0x{1:X}  ->  {2}" -f $r, ([Convert]::ToUInt64($r,16)-$base), $sr) }
  $symOut | Set-Content (Join-Path $diag 'symbols.txt'); Write-Host "Simbolos de encoladores -> symbols.txt"
}

# ZIP por LISTA EXPLICITA: solo diagnostico. Se EXCLUYE run\ (juego, DLL, TU, partidas, build) y la .cpp pesada no entra.
$include = 'sdk_rev.txt','cmake_configure.txt','cmake_build.txt','runtime_dll.sha256.txt','exe.sha256.txt',
           'modules.txt','resultado.txt','task_trace.txt','session.log','symbols.txt','kernel_state.patched.cpp'
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
