"""Selector de renderer (D3D12/Vulkan) y detección de Vulkan en el SDK."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import game                                  # noqa: E402
from reforge.game_options import GameOptions              # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def _proj(renderer):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    o = GameOptions()
    o.renderer = renderer
    o.save(d)
    return d


print("Flag de renderer en launch_args")
exe = "C:/juego/juego.exe"
args_auto = game.launch_args(exe, _proj("auto"))
check(not any("gpu.driver" in a for a in args_auto), "auto: no añade --gpu.driver")

args_vk = game.launch_args(exe, _proj("vulkan"))
check("--gpu.driver=vulkan" in args_vk, "vulkan: añade --gpu.driver=vulkan")
check(not any("gpu_plugin" in a for a in args_vk), "sin --gpu_plugin por línea de comandos (va en el .toml)")

print("SDK 0.11: nada por línea de comandos")
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "build"), exist_ok=True)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    open(os.path.join(d, "src", "main.cpp"), "w").write("REX_TITLE_APP(XApp)\n")   # proyecto del SDK 0.11
    open(os.path.join(d, "build", "CMakeCache.txt"), "w").write(
        "rexglue_DIR:PATH=C:/x/tools/rexglue-sdk/0.11.0.13-dev.g115171b4-fsr/win-amd64/lib/cmake/rexglue\n")
    o = GameOptions()
    o.renderer = "vulkan"
    o.save(d)
    check(game.sdk_no_cli_flags(d), "se reconoce el SDK 0.11 en la caché de CMake")
    check(game.launch_args(exe, d) == [exe, f"--game_data_root={os.path.join(d, 'assets')}"],
          "0.11: ni --gpu_plugin ni --gpu.driver (los rechaza el cargador)")
    check(game._driver_flag(d) == "", "0.11: los lanzadores tampoco los llevan")

args_dx = game.launch_args(exe, _proj("d3d12"))
check("--gpu.driver=d3d12" in args_dx, "d3d12: añade --gpu.driver=d3d12")

print("_driver_flag para lanzadores")
check(game._driver_flag(_proj("vulkan")) == " --gpu.driver=vulkan", "vulkan → ' --gpu.driver=vulkan'")
check(game._driver_flag(_proj("auto")) == "", "auto → cadena vacía")

print("sdk_has_vulkan")
with tempfile.TemporaryDirectory() as d:
    exe2 = os.path.join(d, "juego.exe")
    open(exe2, "wb").close()
    check(game.sdk_has_vulkan(exe2) is None, "sin rexgpu-xenos.dll → None")
    with open(os.path.join(d, "rexgpu-xenos.dll"), "wb") as f:
        f.write(b"....d3d12....no vk here....")
    check(game.sdk_has_vulkan(exe2) is False, "DLL solo D3D12 → False")
    with open(os.path.join(d, "rexgpu-xenos.dll"), "wb") as f:
        f.write(b"....vkCreateDevice....VK_KHR_swapchain....")
    check(game.sdk_has_vulkan(exe2) is True, "DLL con firma Vulkan → True")

with tempfile.TemporaryDirectory() as d:
    exe3 = os.path.join(d, "juego.exe")
    open(exe3, "wb").close()
    with open(os.path.join(d, "rexgpu-xenos.dll"), "wb") as f:
        f.write(b"....solo d3d12....")
    open(os.path.join(d, "rexgpu-xenos-vulkan.dll"), "wb").close()
    check(game.sdk_has_vulkan(exe3) is True, "layout nuevo: rexgpu-xenos-vulkan.dll presente → True")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
