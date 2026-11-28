// Trozos de src/core/utf8.cpp reducidos a los puntos donde entra el parche utf8 tolerante.
// No es el archivo de rexglue: solo tiene las lineas que el parche tiene que encontrar, para que la
// prueba avise si una version nueva del SDK las cambia.
#include <algorithm>
#include <cstdint>
#include <locale>
#include <numeric>
#include <tuple>

#include <rex/string/utf8.h>

#define UTF_CPP_CPLUSPLUS 201703L
#include <utf8.h>

namespace utfcpp = utf8;

using citer = std::string_view::const_iterator;
using utf8_citer = utfcpp::iterator<std::string_view::const_iterator>;

namespace rex::string {

std::string to_utf8(const std::u16string_view source) {
  return utfcpp::utf16to8(source);
}

std::u16string to_utf16(const std::string_view source) {
  return utfcpp::utf8to16(source);
}

std::pair<utf8_citer, utf8_citer> make_citer(const std::string_view view) {
  return {utf8_citer(view.cbegin(), view.cbegin(), view.cend()),
          utf8_citer(view.cend(), view.cbegin(), view.cend())};
}

}  // namespace rex::string
