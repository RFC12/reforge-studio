// Trozos de src/input/mnk/mnk_input_driver.cpp reducidos a los puntos donde entra el parche.
// No es el archivo de rexglue: solo tiene las líneas que el parche tiene que encontrar, para
// que la prueba avise si una versión nueva del SDK las cambia.
#include <rex/cvar.h>

REXCVAR_DEFINE_DOUBLE(mnk_sensitivity, 1.0, "Input", "Mouse sensitivity for right stick")
    .range(0.01, 10.0);

namespace rex::input::mnk {
namespace {

std::atomic<bool> mouse_look_active{true};

}  // namespace

X_RESULT MnkInputDriver::GetDeviceState(DeviceId id, X_INPUT_STATE* out_state) {
  int32_t rx = 0;
  int32_t ry = 0;

  if (REXCVAR_GET(mnk_mouse) && IsMouseLookActive()) {
    double sensitivity = REXCVAR_GET(mnk_sensitivity);
    constexpr double kBaseScale = 200.0;
    rx += static_cast<int32_t>(double(mouse_dx_) * sensitivity * kBaseScale);
    ry += static_cast<int32_t>(double(-mouse_dy_) * sensitivity * kBaseScale);
  }
  // Drained unconditionally: deltas keep accumulating in OnMouseMove while the
  mouse_dx_ = 0.0f;
  mouse_dy_ = 0.0f;
  return X_ERROR_SUCCESS;
}

}  // namespace rex::input::mnk
