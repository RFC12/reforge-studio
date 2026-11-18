$log = "H:\ReForgeHD\aw_cargadas_log.txt"
"esperando a que se cierre el juego $(Get-Date)" | Set-Content $log
while (Get-Process s1_sp64_ship, s1_mp64_ship -EA SilentlyContinue) { Start-Sleep 3 }
Start-Sleep 3
"aplicando $(Get-Date)" | Add-Content $log
Set-Location C:\ReForgeBuild\awlat\tools
python aw_doblaje_latino.py --pc "H:\Call of Duty Advanced Warfare" --x360 H:\cod_aw\assets\spanishna --solo-cargadas *>> $log
"FIN $(Get-Date)" | Add-Content $log
