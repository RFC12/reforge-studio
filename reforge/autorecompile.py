"""Política de recompilación automática resiliente.

Objetivo: recompilar cualquier juego «usando lo mejor» y, si algo falla, **degradar solo por una escalera de
seguridad** hasta lograrlo, en vez de romperse. No promete un 0 % de errores (hay juegos que todavía no son
recompilables), pero maximiza el éxito sin intervención manual. El algoritmo se compone de tres piezas que ya
viven integradas en el pipeline del Taller:

1. **Mejores componentes por defecto** (game_options): optimizador en modo *Fluido*, precompilación de shaders
   (AOT) y auto-ajuste activados; **base de datos de compatibilidad por Title ID** (gamedb.apply: modo de
   imagen idóneo, gamma, alpha, guardas de fetch y banderas verificadas por juego, ampliable y con la config
   que el propio PC va aprendiendo); motor detectado (engine.apply_engine_profile). `cpu_native` queda
   opt-in por seguridad.
2. **SDK siempre compatible** (sdkcompat.ensure_compatible): antes de configurar valida que el SDK provee los
   targets que el proyecto necesita; si no, cambia solo a un SDK instalado compatible o se detiene con un
   mensaje claro. Así, actualizar/cambiar componentes no rompe la recompilación.
3. **Escalera de seguridad de la optimización** (este módulo + game.build_with_ext_fallback): si la compilación
   falla con un nivel agresivo, se baja al siguiente y se regenera automáticamente, hasta el más seguro. Solo
   si el nivel más seguro también falla se reporta que el juego necesita trabajo específico.

Junto con las recuperaciones que ya hacía el build (encabezado SEH, funciones cortadas, «líneas vacías»,
compilar sin la extensión ReForge), esto es la recompilación «automática y lo más a prueba de errores posible».
"""

# De más agresivo (mejor rendimiento) a más seguro (máxima compatibilidad).
CODEGEN_LADDER = ["max", "safe", "off"]


def next_safer_level(current):
    """Siguiente nivel más seguro que `current`, o None si ya es el más seguro o es desconocido."""
    if current in CODEGEN_LADDER:
        i = CODEGEN_LADDER.index(current)
        if i < len(CODEGEN_LADDER) - 1:
            return CODEGEN_LADDER[i + 1]
    return None
