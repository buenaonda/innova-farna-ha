#!/usr/bin/env python3
"""Genera los assets de marca de la integración Innova FÄRNA.

Por qué existe (2026-08-08): el workflow `Validate` fallaba todos los días en
`HACS → Validation brands` — 1 de 9 chequeos. HACS exige assets de marca y los
busca primero en `custom_components/<dominio>/brand/`, y si no, en el repo
`home-assistant/brands`. No había en ninguno de los dos.

## Decisiones de diseño, y por qué

**La marca es ORIGINAL, no la de Innova.** Este repo es público y Apache 2.0;
reusar el logo de un tercero es un problema de marca registrada, no un detalle
estético. El símbolo evoca *aire acondicionado* de forma genérica —tres trazos
de flujo con el gancho del glifo clásico de viento— sin imitar identidad ajena.

**Tampoco usa imágenes de Home Assistant.** Las reglas del repo de brands lo
prohíben explícitamente para integraciones de la comunidad: confundiría al
usuario haciéndole creer que es oficial.

**Se dibuja a 4x y se reduce con LANCZOS.** Pillow no antialiasea trazos; la
única forma de obtener bordes limpios es supersamplear. A 24 px —el tamaño real
en la lista de integraciones de HA— la diferencia es entre legible y sucio.

**El símbolo funciona sin color.** Tres trazos de grosor decreciente se
distinguen por forma, no solo por tono. Un ícono que solo se lee en color falla
en modo oscuro, en escala de grises y para daltónicos.

Regenerar:  python3 tools/make_brand_assets.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "custom_components" / "innova_farna" / "brand"

SS = 4  # factor de supersampleo

# Azul frío → verde azulado. Evoca aire acondicionado sin copiar a nadie.
FRIO = (11, 95, 165)
TIBIO = (23, 184, 166)


def _mezcla(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _estampar(draw: ImageDraw.ImageDraw, camino, ancho: float,
              color: tuple[int, int, int]) -> None:
    """Dibuja un trazo estampando círculos a lo largo del camino.

    `draw.line` con una polilínea gruesa produce BORDES DENTADOS: Pillow dibuja
    cada segmento como un rectángulo independiente y en las curvas quedan
    muescas visibles. Estampar círculos superpuestos da un trazo con extremos y
    bordes redondeados, sin dientes, a cambio de más operaciones — irrelevante
    para un ícono de 1024 px.
    """
    r = ancho / 2
    for x, y in camino:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color + (255,))


def _camino_de_flujo(y: float, largo: float, lado: float):
    """Onda de aire: una sinusoide suave con extremos redondeados.

    Versión anterior: se le agregaba un rizo al final para que "significara
    viento". Fallaba por geometría — el trazo era más grueso que el diámetro del
    rizo, así que el rizo se rellenaba y quedaba un bulto tipo porra. Menos
    símbolo y más legible gana: tres ondas paralelas de largo decreciente son el
    signo universal de flujo de aire en interfaces de climatización, y sobreviven
    la reducción a 24 px, que es donde de verdad se ve este ícono.
    """
    x0 = lado * 0.10
    x1 = x0 + largo
    pts = []
    n = 260
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        # Una onda y media: suficiente para leerse como movimiento, no tanta
        # como para verse rizada al achicar.
        onda = math.sin(t * math.pi * 2.0) * (lado * 0.045)
        pts.append((x, y + onda))
    return pts


def construir_icono(lado_final: int) -> Image.Image:
    lado = lado_final * SS
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    ancho = lado * 0.082
    # Tres trazos: largo decreciente y grosor decreciente. Jerarquía visible en
    # blanco y negro, no solo por color.
    # Reparto vertical amplio y trazos largos: un ícono de avatar debe LLENAR
    # su caja. Con márgenes generosos el símbolo se ve diminuto a 24 px, que es
    # el tamaño real en la lista de integraciones.
    filas = [
        (lado * 0.28, lado * 0.80, ancho * 1.00, 0.00),
        (lado * 0.50, lado * 0.66, ancho * 0.88, 0.50),
        (lado * 0.72, lado * 0.50, ancho * 0.76, 1.00),
    ]
    for y, largo, grosor, t in filas:
        _estampar(draw, _camino_de_flujo(y, largo, lado), grosor, _mezcla(FRIO, TIBIO, t))

    return img.resize((lado_final, lado_final), Image.LANCZOS)


def construir_logo(alto_final: int) -> Image.Image:
    """Símbolo + nombre, sin adornos.

    El nombre es uso nominativo: describe con qué equipos funciona la
    integración, no se apropia de la identidad de Innova — por eso la tipografía
    es genérica y no imita la suya.

    Se quitó el subtítulo "Home Assistant integration": dentro de HA es
    redundante, y las reglas del repo de brands prohíben que una integración de
    la comunidad se presente de forma que sugiera carácter oficial.
    """
    alto = alto_final * SS
    base = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
    f_reg = ImageFont.truetype(f"{base}.ttf", round(alto * 0.34))
    f_bold = ImageFont.truetype(f"{base}-Bold.ttf", round(alto * 0.34))

    # El ancho se MIDE, no se adivina con un multiplicador. Una versión previa
    # usaba alto*3.1 y al subir el tamaño de fuente el texto quedó cortado
    # ("FÄRN"). Un lienzo dimensionado a ojo se rompe en silencio cada vez que
    # cambia la tipografía o el texto.
    regla = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    x = round(alto * 1.00)
    w_texto = regla.textlength("Innova ", font=f_reg) + regla.textlength("FÄRNA", font=f_bold)
    ancho = round(x + w_texto + alto * 0.10)  # margen derecho mínimo

    img = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    img.alpha_composite(construir_icono(alto), (0, 0))
    draw = ImageDraw.Draw(img)

    y = round(alto * 0.50)  # centrado con el símbolo, no con la caja
    draw.text((x, y), "Innova ", font=f_reg, fill=FRIO + (255,), anchor="lm")
    draw.text((x + draw.textlength("Innova ", font=f_reg), y), "FÄRNA",
              font=f_bold, fill=TIBIO + (255,), anchor="lm")

    img = img.resize((round(ancho / SS), alto_final), Image.LANCZOS)
    # "Trimmed": las reglas exigen mínimo espacio vacío en los bordes.
    caja = img.getbbox()
    return img.crop(caja) if caja else img


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    salidas = {
        "icon.png": construir_icono(256),
        "icon@2x.png": construir_icono(512),
        "logo.png": construir_logo(256),
        "logo@2x.png": construir_logo(512),
    }
    for nombre, img in salidas.items():
        destino = DESTINO / nombre
        # optimize + interlaced: las reglas piden comprimido y progresivo.
        img.save(destino, "PNG", optimize=True, interlace=1)
        print(f"  {nombre:14s} {img.size[0]}x{img.size[1]}  {destino.stat().st_size:>6} bytes")


if __name__ == "__main__":
    main()
