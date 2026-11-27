# build_fix_runtime.ps1  -  Windows PowerShell 5.1
# Compila un rexruntime.dll ARREGLADO (Release, sin sufijo, drop-in del que carga tu juego) con el fix de
# src/core/utf8.cpp: las conversiones UTF-8<->UTF-16 y la iteracion de cadenas pasan a ser TOLERANTES (reemplazan
# los bytes invalidos por U+FFFD en vez de lanzar utf8::invalid_utf8). Eso elimina el cierre
# "[FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'" que ocurre al enumerar contenido
# (DLC/partida/TU) cuyo nombre tiene bytes invalidos (xam_content_aggregate.cpp:73 -> string::to_utf16(name)).
#
# Reconstruye el arbol 0.10.1 (commit bd833a2a = tu runtime 0.10.0.24-dev.gbd833a2) OFFLINE desde tus objetos git
# locales, sin tocar tu SDK en 0.11. Deja el DLL en $proj\rexruntime_fixed\ y hace una verificacion en carpeta
# aislada (NO toca tu juego). El deploy al juego se hace aparte, con copia de seguridad.
$ErrorActionPreference = 'Stop'
$sdk   = 'C:\ReForgeBuild\rexglue-sdk'
$proj  = 'C:\Users\roger\ReForgeProjects\asura_s_wrath'
$clang = 'C:\Program Files\LLVM\bin'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$outbase = Join-Path $proj ('rexruntime_fixed_' + $stamp)
$sdkc  = Join-Path $env:TEMP ("rf_sdk_fix_" + $stamp)
$build = Join-Path $sdkc 'out\build\fix'
$run   = Join-Path $outbase 'verify'
New-Item -ItemType Directory -Force -Path $outbase | Out-Null
function Need($c,$m){ if(-not $c){ Write-Error "FALTA: $m"; exit 2 } }
function ResolveTool([string]$name,[string[]]$cands){
  foreach($c in $cands){ if($c -and (Test-Path $c)){ return (Resolve-Path $c).Path } }
  $g = Get-Command $name -ErrorAction SilentlyContinue; if($g){ return $g.Source }; return $null
}
Write-Host "== Requisitos =="
Need (Test-Path (Join-Path $sdk '.git')) "repo git del SDK en $sdk"
Need (Test-Path (Join-Path $proj 'build\asuraswrath.exe')) "asuraswrath.exe compilado"
$cmakeExe = ResolveTool 'cmake' @(
  'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe',
  'C:\Program Files\CMake\bin\cmake.exe')
$ninjaExe = ResolveTool 'ninja' @(
  'C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe',
  'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe',
  'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe')
Need $cmakeExe "cmake (Visual Studio/CMake o PATH)"
Need $ninjaExe "ninja (Visual Studio o PATH)"
Need (Test-Path (Join-Path $clang 'clang++.exe')) "clang en $clang"
$gitExe = ResolveTool 'git' @(
  'C:\Users\roger\AppData\Local\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe',
  'C:\Program Files\Git\cmd\git.exe')
Need $gitExe "git (GitHub Desktop o Git for Windows)"
$rev0101 = 'bd833a2a'
Need ((& $gitExe -C $sdk cat-file -t $rev0101 2>&1) -eq 'commit') "el commit $rev0101 (v0.10.1) no esta en tu repo"
Write-Host "  cmake: $cmakeExe"; Write-Host "  ninja: $ninjaExe"

Write-Host "== 1) Reconstruir el arbol 0.10.1 OFFLINE =="
New-Item -ItemType Directory -Force -Path $sdkc | Out-Null
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
$okSuper = GitArchiveTo $sdk $rev0101 $sdkc $false
Need $okSuper "no se pudo extraer el superproyecto 0.10.1 (offline)"
$subs = @{}; (& $gitExe -C $sdk ls-tree -r $rev0101) | ForEach-Object { if($_ -match '^160000 commit ([0-9a-f]+)\s+(.+)$'){ $subs[$matches[2]] = $matches[1] } }
$cur  = @{}; (& $gitExe -C $sdk submodule status) | ForEach-Object { if($_ -match '^(.)([0-9a-f]+)\s+(\S+)'){ $cur[$matches[3]] = @{sha=$matches[2];flag=$matches[1]} } }
foreach($path in ($subs.Keys | Sort-Object)){
  $want = $subs[$path]; $destSub = Join-Path $sdkc ($path -replace '/','\'); $h = $cur[$path]
  if($h -and $h.flag -ne '-' -and $h.sha -eq $want){
    $src = Join-Path $sdk ($path -replace '/','\')
    $null = robocopy $src $destSub /E /NFL /NDL /NJH /NJS /NP /XD '.git'
    if($LASTEXITCODE -ge 8){ Write-Error "copia de submodulo $path fallo ($LASTEXITCODE)"; exit 3 }
    Write-Host ("  {0} <- working dir" -f $path)
  } else {
    $store = Join-Path $sdk ('.git\modules\' + ($path -replace '/','\'))
    Need (Test-Path $store) "object store local de $path ausente (necesitaria red)"
    $okSub = GitArchiveTo $store $want $destSub $true
    Need $okSub "no se pudo extraer $path offline (necesitaria red)"
    Write-Host ("  {0} <- object store" -f $path)
  }
  $dotgit = Join-Path $destSub '.git'
  if(-not (Test-Path $dotgit)){ Set-Content $dotgit "rf-fix offline (centinela)" -Encoding ASCII }
}
$u8 = Join-Path $sdkc 'src\core\utf8.cpp'
Need (Test-Path $u8) "no se reconstruyo src/core/utf8.cpp (0.10.1)"

Write-Host "== 2) Aplicar el fix de utf8.cpp (iterador tolerante + conversiones tolerantes) via git apply =="
# El parche vive junto a este script (utf8_tolerant.diff), relativo a src/core/utf8.cpp.
$diff = Join-Path $PSScriptRoot 'utf8_tolerant.diff'
if(-not (Test-Path $diff)){ $diff = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'utf8_tolerant.diff' }
Need (Test-Path $diff) "no se encontro utf8_tolerant.diff junto al script"
& $gitExe -C $sdkc apply --verbose --whitespace=nowarn $diff 2>&1 | ForEach-Object { Write-Host "  $_" }
Need ($LASTEXITCODE -eq 0) "git apply del parche utf8 fallo ($LASTEXITCODE)"
# Verificar que el fix quedo aplicado
$s = Get-Content $u8 -Raw
foreach($m in @('class utf8_citer','rf_detail::rf_seq_len','utfcpp::replace_invalid(source.begin()')){
  if(-not ($s -match [regex]::Escape($m))){ throw "marca '$m' ausente tras aplicar el parche" }
}
Write-Host "  parche aplicado y verificado (class utf8_citer tolerante, to_utf16/to_utf8 tolerantes)"
Copy-Item $u8 (Join-Path $outbase 'utf8.fixed.cpp') -Force
Write-Host "Fix aplicado."

Write-Host "== 3) Compilar rexruntime (Release, sin sufijo = drop-in) =="
# Variante FSR (drop-in identico): FidelityFX ON para conservar el import de amd_fidelityfx_dx12.dll.
#   Requiere Vulkan SDK, git en PATH + GIT_EXECUTABLE (FetchContent clona FidelityFX-SDK: unico acceso a red),
#   y convertir ffx_api_dll.rc de UTF-16 a UTF-8 (llvm-rc rechaza el BOM UTF-16).
# Para una build 100% offline SIN FSR, pon $ffx='OFF' (se omite la descarga y el paso del .rc).
$ffx = 'ON'
$vulkan = $env:VULKAN_SDK; if(-not $vulkan){ $vulkan = (Get-ChildItem 'C:\VulkanSDK' -Directory -ErrorAction SilentlyContinue | Sort-Object Name -desc | Select-Object -First 1).FullName }
if($ffx -eq 'ON'){ Need $vulkan "Vulkan SDK (necesario para FidelityFX ON)"; $env:VULKAN_SDK = $vulkan }
$gitDir = Split-Path $gitExe
$env:PATH = "$clang;$(Split-Path $ninjaExe);$gitDir;$vulkan\Bin;$env:PATH"
$prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $cmakeExe -S $sdkc -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release "-DREXGLUE_ENABLE_FIDELITYFX=$ffx" `
        -DREXGLUE_ENABLE_TRACY=OFF -DREXGLUE_BUILD_TESTS=OFF -DCMAKE_MAKE_PROGRAM="$ninjaExe" `
        -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DGIT_EXECUTABLE=$gitExe" 2>&1 | Tee-Object (Join-Path $outbase 'cmake_configure.txt')
$cfgExit = $LASTEXITCODE
if ($cfgExit -ne 0) { $ErrorActionPreference = $prevEAP; Write-Host "CONFIGURE FALLO ($cfgExit). Ver cmake_configure.txt."; exit 4 }
if($ffx -eq 'ON'){
  # llvm-rc no soporta el BOM UTF-16: convertir los .rc de FidelityFX a UTF-8.
  $ffxSrc = Join-Path $build '_deps\fidelityfx-src'
  Get-ChildItem $ffxSrc -Recurse -Filter *.rc -File -ErrorAction SilentlyContinue | ForEach-Object {
    $bytes = [IO.File]::ReadAllBytes($_.FullName)
    if($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE){
      $text = [Text.Encoding]::Unicode.GetString($bytes,2,$bytes.Length-2)
      [IO.File]::WriteAllText($_.FullName,$text,(New-Object Text.UTF8Encoding($false)))
      Write-Host ("  .rc UTF-16->UTF-8: {0}" -f $_.Name)
    }
  }
}
& $cmakeExe --build $build --target rexruntime 2>&1 | Tee-Object (Join-Path $outbase 'cmake_build.txt')
$bldExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($bldExit -ne 0) { Write-Host "BUILD FALLO ($bldExit). Ver cmake_build.txt."; exit 5 }
$outdir = Join-Path $sdkc 'out\win-amd64'
$fixed = Get-ChildItem $outdir -Filter 'rexruntime*.dll' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -desc | Select-Object -First 1
Need $fixed "no se genero rexruntime.dll"
Copy-Item $fixed.FullName (Join-Path $outbase 'rexruntime.dll') -Force
Get-FileHash (Join-Path $outbase 'rexruntime.dll') -Algorithm SHA256 | Tee-Object (Join-Path $outbase 'rexruntime_fixed.sha256.txt')
Write-Host "rexruntime.dll ARREGLADO: $(Join-Path $outbase 'rexruntime.dll')  ($((Get-Item (Join-Path $outbase 'rexruntime.dll')).Length) bytes)"

Write-Host "== 4) Verificar en carpeta AISLADA (copia del juego + runtime arreglado; tu plugin de GPU sin tocar) =="
if (Test-Path $run) { Remove-Item $run -Recurse -Force -ErrorAction SilentlyContinue }
Copy-Item (Join-Path $proj 'build') $run -Recurse -Force
Copy-Item (Join-Path $outbase 'rexruntime.dll') (Join-Path $run 'rexruntime.dll') -Force
$rlogs = Join-Path $run 'logs'; if (Test-Path $rlogs) { Remove-Item (Join-Path $rlogs '*') -Force -ErrorAction SilentlyContinue } else { New-Item -ItemType Directory -Force -Path $rlogs | Out-Null }
$exe = Join-Path $run 'asuraswrath.exe'
$p = Start-Process $exe -ArgumentList "--game_data_root=$proj\assets" -WorkingDirectory $run -PassThru
# El cierre original ocurria solo (en el menu de titulo, tras XNetLogonGetTitleID) en <1 min; esperamos 200s.
$exited = $p.WaitForExit(200000)
if (-not $exited) { try { $p.Kill() } catch {}; $p.WaitForExit() }
$log = Get-ChildItem $rlogs -Filter *.log | Sort-Object LastWriteTime -desc | Select-Object -First 1
$crashed = $false
if ($log) { Copy-Item $log.FullName (Join-Path $outbase 'verify_session.log') -Force; $crashed = [bool](Select-String $log.FullName -Pattern "Invalid UTF-8|deferred completion threw") }
Write-Host ""
if ($crashed) { Write-Host "RESULTADO: el cierre 'Invalid UTF-8' AUN aparece en el log (ver verify_session.log). El fix NO basto." }
elseif ($exited) { Write-Host "RESULTADO: el juego cerro solo SIN 'Invalid UTF-8' (exit 0x{0:X8}). Revisa verify_session.log por otra causa." -f $p.ExitCode }
else { Write-Host "RESULTADO: el juego corrio >200s SIN 'Invalid UTF-8' y lo cerro el script. El cierre parece ARREGLADO." }
Write-Host ""
Write-Host "DLL arreglado listo en: $(Join-Path $outbase 'rexruntime.dll')"
Write-Host "Para desplegarlo en tu juego (con copia de seguridad):"
Write-Host "  Copy-Item '$proj\build\rexruntime.dll' '$proj\build\rexruntime.dll.bak_$stamp'"
Write-Host "  Copy-Item '$(Join-Path $outbase 'rexruntime.dll')' '$proj\build\rexruntime.dll' -Force"
