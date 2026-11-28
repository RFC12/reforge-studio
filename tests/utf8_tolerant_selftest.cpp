// Prueba de comportamiento del iterador UTF-8 TOLERANTE que el parche sdk_patch.apply_utf8_tolerant
// inserta en src/core/utf8.cpp. Ejercita secuencias UTF-8 invalidas y truncadas y comprueba que:
//   - nunca lanza,
//   - una secuencia invalida/truncada produce U+FFFD,
//   - operator++ NUNCA avanza mas alla de end (la causa del cuelgue con el iterador unchecked),
//   - recorrer un buffer arbitrario (incluido basura) SIEMPRE termina en end exacto,
//   - operator-- vuelve al inicio del codepoint anterior.
// La clase es identica a la que inserta el parche: si alguien la cambia y la rompe, esto lo caza.
// Compila sin rexglue ni utfcpp:  c++ -std=c++20 utf8_tolerant_selftest.cpp -o x && ./x
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <iterator>
#include <string>
#include <string_view>
#include <vector>

// ---- INICIO: copia textual del iterador del parche (debe coincidir con UTF8_ITER_HOOK) ----
namespace rf_detail {
inline int rf_seq_len(unsigned char c) {
  if (c < 0x80) return 1;
  if ((c & 0xE0) == 0xC0) return 2;
  if ((c & 0xF0) == 0xE0) return 3;
  if ((c & 0xF8) == 0xF0) return 4;
  return 1;
}
}  // namespace rf_detail

class utf8_citer {
 public:
  using iterator_category = std::bidirectional_iterator_tag;
  using value_type = char32_t;
  using difference_type = std::ptrdiff_t;
  using pointer = const char32_t*;
  using reference = char32_t;
  using octet_iterator = std::string_view::const_iterator;

  utf8_citer() = default;
  utf8_citer(octet_iterator it, octet_iterator start, octet_iterator end)
      : it_(it), start_(start), end_(end) {}

  octet_iterator base() const { return it_; }

  char32_t operator*() const {
    unsigned char c0 = static_cast<unsigned char>(*it_);
    int len = rf_detail::rf_seq_len(c0);
    if (len == 1) return c0 < 0x80 ? char32_t(c0) : char32_t(0xFFFD);
    char32_t cp = static_cast<char32_t>(c0 & (0x3F >> (len - 1)));
    octet_iterator q = it_;
    ++q;
    for (int i = 1; i < len; ++i) {
      if (q == end_) return 0xFFFD;
      unsigned char cc = static_cast<unsigned char>(*q);
      if ((cc & 0xC0) != 0x80) return 0xFFFD;
      cp = (cp << 6) | (cc & 0x3F);
      ++q;
    }
    return cp;
  }

  utf8_citer& operator++() {
    int len = rf_detail::rf_seq_len(static_cast<unsigned char>(*it_));
    ++it_;
    for (int i = 1; i < len && it_ != end_; ++i) {
      if ((static_cast<unsigned char>(*it_) & 0xC0) != 0x80) break;
      ++it_;
    }
    return *this;
  }
  utf8_citer operator++(int) { utf8_citer t = *this; ++(*this); return t; }

  utf8_citer& operator--() {
    --it_;
    for (int i = 0; i < 3 && it_ != start_ &&
                    (static_cast<unsigned char>(*it_) & 0xC0) == 0x80;
         ++i) {
      --it_;
    }
    return *this;
  }
  utf8_citer operator--(int) { utf8_citer t = *this; --(*this); return t; }

  bool operator==(const utf8_citer& o) const { return it_ == o.it_; }
  bool operator!=(const utf8_citer& o) const { return it_ != o.it_; }

 private:
  octet_iterator it_{};
  octet_iterator start_{};
  octet_iterator end_{};
};
// ---- FIN: copia del iterador del parche ----

static std::pair<utf8_citer, utf8_citer> make_citer(std::string_view v) {
  return {utf8_citer(v.cbegin(), v.cbegin(), v.cend()),
          utf8_citer(v.cend(), v.cbegin(), v.cend())};
}

static int fails = 0;
static void check(bool c, const char* m) {
  std::printf(c ? "  ok  %s\n" : "  FAIL %s\n", m);
  if (!c) ++fails;
}

// Decodifica un solo codepoint y devuelve (cp, bytes_avanzados).
static std::pair<char32_t, long> one(std::string_view v) {
  auto [b, e] = make_citer(v);
  char32_t cp = *b;
  auto nb = b;
  ++nb;
  return {cp, nb.base() - b.base()};
}

int main() {
  // 1) Validos: codepoint y avance correctos
  { auto [cp, n] = one("A"); check(cp == U'A' && n == 1, "ASCII 'A' -> 1 byte"); }
  { auto [cp, n] = one("\xC3\xA9"); check(cp == 0xE9 && n == 2, "'e aguda' (C3 A9) -> U+00E9, 2 bytes"); }
  { auto [cp, n] = one("\xE2\x82\xAC"); check(cp == 0x20AC && n == 3, "euro (E2 82 AC) -> U+20AC, 3 bytes"); }
  { auto [cp, n] = one("\xF0\x9D\x84\x9E"); check(cp == 0x1D11E && n == 4, "clave de sol -> U+1D11E, 4 bytes"); }

  // 2) Invalidos: U+FFFD y avance de 1 byte (no se come bytes buenos de mas)
  { auto [cp, n] = one("\xA9"); check(cp == 0xFFFD && n == 1, "continuacion suelta (A9) -> U+FFFD, 1 byte"); }
  { auto [cp, n] = one("\xFF"); check(cp == 0xFFFD && n == 1, "0xFF (lider invalido) -> U+FFFD, 1 byte"); }

  // 3) TRUNCADO: lider de 3 bytes con solo 2 disponibles antes de end.
  //    operator* -> U+FFFD; operator++ NO pasa de end (esto colgaba con unchecked).
  {
    std::string_view v("\xE2\x82", 2);
    auto [b, e] = make_citer(v);
    check(*b == 0xFFFD, "truncado (E2 82) -> U+FFFD");
    ++b;
    check(b.base() <= e.base(), "++ sobre truncado no pasa de end");
    check(b == e, "++ sobre truncado llega EXACTO a end");
  }
  // lider que pide continuacion pero el siguiente byte NO es continuacion
  {
    std::string_view v("\xE2\x41\x42", 3);  // E2 (pide 2 mas) seguido de 'A' 'B'
    auto [b, e] = make_citer(v);
    check(*b == 0xFFFD, "E2 seguido de no-continuacion -> U+FFFD");
    ++b;
    check(*b == U'A', "tras E2 roto, el siguiente es 'A' (no se comio la 'A')");
  }

  // 4) Recorrer basura arbitraria SIEMPRE termina en end exacto y nunca pasa de end.
  {
    std::vector<unsigned char> bytes;
    for (int i = 0; i < 2000; ++i) bytes.push_back((unsigned char)((i * 2654435761u) >> 13));
    std::string_view v(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    auto [b, e] = make_citer(v);
    long steps = 0, maxsteps = (long)bytes.size() + 8;
    bool overran = false;
    for (; b != e && steps < maxsteps; ++b, ++steps) {
      (void)*b;                         // no debe lanzar ni leer fuera
      if (b.base() > e.base()) { overran = true; break; }
    }
    check(!overran, "basura: base() nunca pasa de end");
    check(b == e, "basura: el recorrido termina EXACTO en end (sin bucle infinito)");
    check(steps <= (long)bytes.size(), "basura: pasos <= bytes (cada paso avanza >=1)");
  }

  // 5) operator-- vuelve al inicio del codepoint anterior (datos validos)
  {
    std::string_view v("A\xE2\x82\xAC""Z");  // 'A', euro(3B), 'Z'
    auto [b, e] = make_citer(v);
    auto it = b; ++it; ++it;                  // b=A, +1=euro, +1=Z
    check(*it == U'Z', "posicionado en 'Z'");
    --it;                                      // debe volver al euro (saltando 2 continuacion)
    check(*it == 0x20AC, "-- vuelve al euro (inicio del codepoint anterior)");
    --it;
    check(*it == U'A', "-- vuelve a 'A'");
  }

  std::printf(fails ? "\nFALLARON %d\n" : "\nTodas las pruebas C++ pasaron\n", fails);
  return fails ? 1 : 0;
}
