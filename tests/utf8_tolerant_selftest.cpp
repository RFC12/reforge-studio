// Prueba de comportamiento del iterador UTF-8 TOLERANTE y de to_utf8 acotado que el parche
// sdk_patch.apply_utf8_tolerant inserta en src/core/utf8.cpp. La clase y to_utf8 son copia textual
// de lo que inserta el parche: si alguien los cambia y los rompe, esto lo caza.
// Comprueba, sin lanzar ni pasar de los limites:
//   - validos decodifican bien y operator++ avanza los bytes correctos,
//   - invalido/truncado/overlong/fuera de rango/surrogate -> U+FFFD,
//   - operator++ NUNCA pasa de end (causa del cuelgue con unchecked); recorrer basura SIEMPRE termina,
//   - operator-- no lee antes de [start] y hace round-trip en datos validos,
//   - to_utf8: par surrogate valido -> 4 bytes; alto aislado/truncado o bajo aislado -> U+FFFD.
// Compila sin rexglue ni utfcpp:  c++ -std=c++20 utf8_tolerant_selftest.cpp -o x && ./x
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
    if (it_ == end_) return 0xFFFD;
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
    static const char32_t kMin[5] = {0, 0, 0x80, 0x800, 0x10000};
    if (cp < kMin[len] || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return 0xFFFD;
    return cp;
  }

  utf8_citer& operator++() {
    if (it_ == end_) return *this;
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
    if (it_ == start_) return *this;
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
// ---- FIN iterador ----

// ---- INICIO: copia textual de to_utf8 del parche (debe coincidir con UTF8_TO8_HOOK) ----
static std::string to_utf8(std::u16string_view source) {
  std::string out;
  out.reserve(source.size());
  auto emit = [&out](char32_t cp) {
    if (cp < 0x80) { out.push_back(static_cast<char>(cp)); }
    else if (cp < 0x800) { out.push_back(static_cast<char>(0xC0 | (cp >> 6))); out.push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
    else if (cp < 0x10000) { out.push_back(static_cast<char>(0xE0 | (cp >> 12))); out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F))); out.push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
    else { out.push_back(static_cast<char>(0xF0 | (cp >> 18))); out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F))); out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F))); out.push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
  };
  for (size_t i = 0; i < source.size();) {
    char16_t u = source[i++];
    char32_t cp;
    if (u >= 0xD800 && u <= 0xDBFF) {
      if (i < source.size() && source[i] >= 0xDC00 && source[i] <= 0xDFFF) { char16_t lo = source[i++]; cp = 0x10000u + ((static_cast<char32_t>(u - 0xD800) << 10) | (lo - 0xDC00)); }
      else { cp = 0xFFFD; }
    } else if (u >= 0xDC00 && u <= 0xDFFF) { cp = 0xFFFD; }
    else { cp = u; }
    emit(cp);
  }
  return out;
}
// ---- FIN to_utf8 ----

static std::pair<utf8_citer, utf8_citer> mk(std::string_view v) {
  return {utf8_citer(v.cbegin(), v.cbegin(), v.cend()), utf8_citer(v.cend(), v.cbegin(), v.cend())};
}
static int fails = 0;
static void check(bool c, const char* m) { std::printf(c ? "  ok  %s\n" : "  FAIL %s\n", m); if (!c) ++fails; }
static char32_t one(std::string_view v) { auto [b, e] = mk(v); (void)e; return *b; }
static long adv(std::string_view v) { auto [b, e] = mk(v); (void)e; auto n = b; ++n; return n.base() - b.base(); }

int main() {
  // validos
  check(one("A") == U'A' && adv("A") == 1, "ASCII 'A' -> 1 byte");
  check(one("\xC3\xA9") == 0xE9 && adv("\xC3\xA9") == 2, "C3 A9 -> U+00E9, 2 bytes");
  check(one("\xE2\x82\xAC") == 0x20AC && adv("\xE2\x82\xAC") == 3, "euro -> U+20AC, 3 bytes");
  check(one("\xF0\x9D\x84\x9E") == 0x1D11E && adv("\xF0\x9D\x84\x9E") == 4, "clave de sol -> U+1D11E, 4 bytes");
  // invalidos simples
  check(one(std::string_view("\xA9", 1)) == 0xFFFD, "continuacion suelta -> U+FFFD");
  check(one(std::string_view("\xFF", 1)) == 0xFFFD, "0xFF lider invalido -> U+FFFD");
  // overlong
  check(one(std::string_view("\xC0\x80", 2)) == 0xFFFD, "overlong C0 80 -> U+FFFD");
  check(one(std::string_view("\xE0\x80\x80", 3)) == 0xFFFD, "overlong E0 80 80 -> U+FFFD");
  // surrogate codificado en UTF-8 (ED A0 80 = U+D800)
  check(one(std::string_view("\xED\xA0\x80", 3)) == 0xFFFD, "surrogate ED A0 80 -> U+FFFD");
  // fuera del rango Unicode
  check(one(std::string_view("\xF4\x90\x80\x80", 4)) == 0xFFFD, "fuera de rango F4 90 -> U+FFFD");
  check(one(std::string_view("\xF5\x80\x80\x80", 4)) == 0xFFFD, "fuera de rango F5 -> U+FFFD");
  // truncado: lider de 3 con solo 2 bytes -> U+FFFD y ++ no pasa de end
  {
    std::string_view v("\xE2\x82", 2); auto [b, e] = mk(v);
    check(*b == 0xFFFD, "truncado E2 82 -> U+FFFD"); ++b;
    check(b.base() <= e.base() && b == e, "++ sobre truncado llega EXACTO a end (sin pasar)");
  }
  // E2 seguido de no-continuacion: FFFD y la 'A' no se consume
  { std::string_view v("\xE2\x41\x42", 3); auto [b, e] = mk(v); (void)e; check(*b == 0xFFFD, "E2 roto -> U+FFFD"); ++b; check(*b == U'A', "la 'A' no se comio"); }
  // basura arbitraria: recorrer siempre termina en end, nunca pasa de end
  {
    std::vector<unsigned char> bytes; for (int i = 0; i < 3000; ++i) bytes.push_back((unsigned char)((i * 2654435761u) >> 11));
    std::string_view v(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    auto [b, e] = mk(v); long steps = 0; bool over = false;
    for (; b != e && steps < (long)bytes.size() + 8; ++b, ++steps) { (void)*b; if (b.base() > e.base()) { over = true; break; } }
    check(!over && b == e && steps <= (long)bytes.size(), "basura: termina EXACTO en end, sin pasar, sin bucle");
  }
  // operator-- no lee antes de start y hace round-trip en datos validos
  {
    std::string_view v("A\xE2\x82\xAC""Z"); auto [b, e] = mk(v); (void)e; auto it = b; ++it; ++it;
    check(*it == U'Z', "en Z"); --it; check(*it == 0x20AC, "-- euro"); --it; check(*it == U'A', "-- A");
    --it; check(it == b, "-- en start es no-op (no lee antes de [start])");
  }
  // to_utf8 acotado
  { char16_t s[] = {0xD834, 0xDD1E}; check(to_utf8(std::u16string_view(s, 2)) == "\xF0\x9D\x84\x9E", "to_utf8 par surrogate -> clave de sol"); }
  { char16_t s[] = {0xD834, 0x0041}; check(to_utf8(std::u16string_view(s, 2)) == "\xEF\xBF\xBD""A", "to_utf8 alto aislado -> U+FFFD + 'A'"); }
  { char16_t s[] = {0xDD1E};        check(to_utf8(std::u16string_view(s, 1)) == "\xEF\xBF\xBD", "to_utf8 bajo aislado -> U+FFFD"); }
  { char16_t s[] = {0xD834};        check(to_utf8(std::u16string_view(s, 1)) == "\xEF\xBF\xBD", "to_utf8 alto truncado al final -> U+FFFD"); }

  std::printf(fails ? "\nFALLARON %d\n" : "\nTodas las pruebas C++ pasaron\n", fails);
  return fails ? 1 : 0;
}
