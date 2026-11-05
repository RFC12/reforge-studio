// ReForge Studio: cambio de texturas en la GPU (ver reforge_texswap.cpp).
#pragma once

#include <cstdint>

namespace rex::graphics::reforge_texswap {

// Antes de subir el nivel base de una textura: cambia sus bytes si hay pareja y la vuelca si se pide.
void OnLoad(uint8_t* membase, uint32_t base_address, uint32_t base_size, uint32_t width, uint32_t height,
            uint32_t pitch_texels, uint32_t tiled, uint32_t format, uint32_t endianness, uint32_t has_mips);

// Al empezar cada lote de texturas: vigila style.txt e index.txt y aplica los cambios en caliente.
void Tick(uint8_t* membase);

}  // namespace rex::graphics::reforge_texswap
