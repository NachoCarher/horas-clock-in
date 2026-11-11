#!/usr/bin/env python3
"""horas - seguimiento sencillo de horas de trabajo.

  horas                    estado de hoy y saldo acumulado
  horas in  [HH:MM]        fichar entrada (ahora, o a la hora indicada)
  horas out [HH:MM]        fichar salida  (ahora, o a la hora indicada)
  horas in  --media        marcar hoy como media jornada (objetivo a la mitad);
                           también vale -m, y con `horas out` si se te olvidó al entrar
  horas undo               deshacer el último fichaje (entrada o salida)
  horas semana [N]         resumen de esta semana (o de hace N semanas)
  horas log [N]            historial: las últimas N líneas (por defecto 14)
  horas ajuste ±DUR [nota] corregir el saldo a mano, p. ej. `horas ajuste +2h`,
                           `horas ajuste -30m`, `horas ajuste +1h30m saldo inicial`
  horas edit               abrir el fichero de datos en tu editor
  horas help               mostrar esta ayuda (también: ayuda, h, -h, --help)

Atajos: i = in, o = out, s = status, u = undo, w = semana, l = log
"""
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Configuración ────────────────────────────────────────────────────────────
OBJETIVO = timedelta(hours=8)      # horas a trabajar cada día laborable
LABORABLES = {0, 1, 2, 3, 4}       # 0 = lunes ... 6 = domingo
ARCHIVO = Path(os.environ.get("HORAS_FILE", Path.home() / ".horas.csv"))
# ─────────────────────────────────────────────────────────────────────────────

FMT = "%Y-%m-%d %H:%M"
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
CERO = timedelta(0)
COLOR = sys.stdout.isatty()
EFECTOS = COLOR and os.environ.get("HORAS_EFECTOS", "1") != "0"   # HORAS_EFECTOS=0 los quita


def color(texto, codigo):
    return f"\033[{codigo}m{texto}\033[0m" if COLOR else texto


def verde(t): return color(t, "32")
def rojo(t): return color(t, "31")
def gris(t): return color(t, "2")
def negrita(t): return color(t, "1")


# ── Efectos al fichar ────────────────────────────────────────────────────────

def animar(fotogramas, duracion):
    """Dibuja los fotogramas uno tras otro sobre la misma línea y la deja limpia."""
    fotogramas = list(fotogramas)
    sys.stdout.write("\033[?25l")                      # ocultar el cursor
    try:
        for f in fotogramas:
            sys.stdout.write("\r\033[K" + f)
            sys.stdout.flush()
            time.sleep(duracion / len(fotogramas))
    finally:
        sys.stdout.write("\r\033[K\033[?25h")           # limpiar y mostrar el cursor
        sys.stdout.flush()


def efecto_in(texto):
    """Entrada: el mensaje se descifra de izquierda a derecha entre símbolos al azar."""
    def ruido(trozo):
        return "".join(" " if c == " " else random.choice("░▒▓█#%&$01") for c in trozo)
    animar((f"\033[1;32m{texto[:max(i, 0)]}\033[0;32m{ruido(texto[max(i, 0):])}\033[0m"
            for i in range(-8, len(texto) + 1)), 0.7)


def efecto_out(texto):
    """Salida: una barra se apaga como una tele antigua, encogiéndose hasta un punto."""
    ancho = len(texto)
    tonos = [226, 220, 214, 208, 202, 196]             # de amarillo a rojo
    barras = [" " * ((ancho - w) // 2)
              + f"\033[38;5;{tonos[(ancho - w) * len(tonos) // (ancho + 1)]}m{'━' * w}\033[0m"
              for w in range(ancho, 0, -2)]
    punto = " " * (ancho // 2)
    animar(barras + [punto + "\033[1;97m✦\033[0m"] * 3 + [punto + "\033[2m·\033[0m"] * 3, 0.7)


def anunciar(efecto, texto):
    """Imprime el mensaje del fichaje, con su efecto si la terminal lo permite."""
    if EFECTOS and len(texto) < shutil.get_terminal_size().columns:
        efecto(texto)
    print(texto)


def ahora():
    return datetime.now().replace(second=0, microsecond=0)


def dur(td, signo=False):
    """timedelta -> '7h 05m' (o '+1h 00m' / '-0h 30m' con signo)."""
    minutos = round(td.total_seconds() / 60)
    s = ("-" if minutos < 0 else "+") if signo else ""
    h, m = divmod(abs(minutos), 60)
    return f"{s}{h}h {m:02d}m"


def leer_dur(texto):
    """'+2h', '-30m', '1h30m' o '1:30' -> timedelta (None si no se entiende)."""
    t = texto.replace(" ", "").lower()
    m = re.fullmatch(r"([+-]?)(?:(\d+)h)?(?:(\d+)m)?", t)
    if m and (m[2] or m[3]):
        horas, minutos = int(m[2] or 0), int(m[3] or 0)
    else:
        m = re.fullmatch(r"([+-]?)(\d+):(\d\d)", t)
        if not m:
            return None
        horas, minutos = int(m[2]), int(m[3])
    td = timedelta(hours=horas, minutes=minutos)
    return -td if m[1] == "-" else td


def saldo_color(td, ancho=0):
    texto = dur(td, signo=True).rjust(ancho)
    if td > CERO:
        return verde(texto)
    if td < CERO:
        return rojo(texto)
    return texto


def etiqueta(fecha, media=False):
    return f"{DIAS[fecha.weekday()]} {fecha.strftime('%d/%m')}" + (" ½" if media else "")


# ── Datos ────────────────────────────────────────────────────────────────────
# Un fichero de texto con una línea por registro:
#   sesión:  "inicio,fin"            (la sesión abierta tiene el fin vacío)
#            "inicio,fin,media"      (marca ese día como media jornada)
#   ajuste:  "ajuste,fecha,±duración,nota"

def cargar():
    """Devuelve (sesiones, ajustes).

    sesiones: listas [inicio, fin | None, media], ordenadas por inicio
    ajustes:  listas [fecha, duración, nota]
    """
    sesiones, ajustes = [], []
    if not ARCHIVO.exists():
        return sesiones, ajustes
    for n, linea in enumerate(ARCHIVO.read_text().splitlines(), 1):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        try:
            if linea.lower().startswith("ajuste,"):
                _, fecha, cuanto, nota = (linea.split(",", 3) + [""])[:4]
                td = leer_dur(cuanto)
                if td is None:
                    raise ValueError
                ajustes.append([date.fromisoformat(fecha.strip()), td, nota.strip()])
            else:
                campos = [c.strip() for c in linea.split(",")] + ["", ""]
                ini, fin, marca = campos[:3]
                sesiones.append([
                    datetime.strptime(ini, FMT),
                    datetime.strptime(fin, FMT) if fin else None,
                    marca.lower() == "media",
                ])
        except ValueError:
            sys.exit(f"Línea {n} mal formada en {ARCHIVO}: {linea!r}\n"
                     f"Arréglala con `horas edit`.")
    sesiones.sort(key=lambda s: s[0])
    for s in sesiones[:-1]:
        if s[1] is None:
            sys.exit(f"La sesión del {s[0].strftime(FMT)} no tiene salida y no es la última.\n"
                     f"Arréglala con `horas edit`.")
    return sesiones, ajustes


def guardar(sesiones, ajustes):
    lineas = [(i, f"{i.strftime(FMT)},{f.strftime(FMT) if f else ''}{',media' if m else ''}")
              for i, f, m in sesiones]
    lineas += [(datetime.combine(d, datetime.min.time()),
                f"ajuste,{d.isoformat()},{dur(td, signo=True)},{nota}")
               for d, td, nota in ajustes]
    lineas.sort(key=lambda x: x[0])
    ARCHIVO.write_text("\n".join(texto for _, texto in lineas) + "\n")


def abierta(sesiones):
    """Devuelve la sesión en curso, si la hay."""
    return sesiones[-1] if sesiones and sesiones[-1][1] is None else None


def por_dia(sesiones):
    """{fecha: [sesiones]}; cada sesión cuenta para el día en que empezó."""
    dias = {}
    for s in sesiones:
        dias.setdefault(s[0].date(), []).append(s)
    return dict(sorted(dias.items()))


def trabajado(sesiones_dia):
    total = CERO
    for ini, fin, _ in sesiones_dia:
        total += (fin or ahora()) - ini
    return total


def es_media(sesiones_dia):
    """Un día es media jornada si alguna de sus sesiones lleva la marca."""
    return any(s[2] for s in sesiones_dia)


def objetivo(fecha, sesiones_dia=()):
    meta = OBJETIVO if fecha.weekday() in LABORABLES else CERO
    return meta / 2 if es_media(sesiones_dia) else meta


def cerrado(fecha, sesiones_dia):
    """Un día cuenta para el saldo cuando ya pasó y todas sus sesiones tienen salida."""
    return fecha < ahora().date() and all(s[1] for s in sesiones_dia)


def saldo_total(dias, ajustes):
    """Diferencia acumulada de los días cerrados, más los ajustes manuales."""
    total = sum((a[1] for a in ajustes), CERO)
    for d, ses in dias.items():
        if cerrado(d, ses):
            total += trabajado(ses) - objetivo(d, ses)
    return total


def separar_flag_media(args):
    """Devuelve (hay_flag, resto_de_argumentos)."""
    flags = ("--media", "-m", "media")
    return any(a in flags for a in args), [a for a in args if a not in flags]


def hora_arg(args):
    """Lee un HH:MM opcional de los argumentos."""
    if not args:
        return None
    try:
        return datetime.strptime(args[0], "%H:%M").time()
    except ValueError:
        sys.exit(f"Hora no válida: {args[0]!r}. Usa el formato HH:MM, p. ej. 09:15")


# ── Comandos ─────────────────────────────────────────────────────────────────

def cmd_in(args):
    media, args = separar_flag_media(args)
    sesiones, ajustes = cargar()
    s = abierta(sesiones)
    if s:
        sys.exit(f"Ya estás dentro desde {s[0].strftime('%H:%M')} "
                 f"({etiqueta(s[0])}). Usa `horas out` primero.")
    hora = hora_arg(args)
    t = datetime.combine(ahora().date(), hora) if hora else ahora()
    if t > ahora():
        sys.exit("Esa hora todavía no ha llegado.")
    if sesiones and t < sesiones[-1][1]:
        sys.exit(f"Esa hora es anterior a tu última salida "
                 f"({sesiones[-1][1].strftime('%d/%m %H:%M')}).")
    sesiones.append([t, None, media])
    guardar(sesiones, ajustes)
    anunciar(efecto_in,
             f"→ Entrada a las {t.strftime('%H:%M')}" + (" · media jornada" if media else ""))
    cmd_status([])


def cmd_out(args):
    media, args = separar_flag_media(args)
    sesiones, ajustes = cargar()
    s = abierta(sesiones)
    if not s:
        sys.exit("No estás dentro. Usa `horas in` primero.")
    hora = hora_arg(args)
    if hora:
        # La hora se entiende a partir del inicio de la sesión, así puedes
        # cerrar hoy una sesión que olvidaste cerrar ayer: `horas out 18:00`
        t = datetime.combine(s[0].date(), hora)
        if t <= s[0]:
            t += timedelta(days=1)
        if t > ahora():
            sys.exit("Esa hora todavía no ha llegado.")
    else:
        t = ahora()
    s[1] = t
    s[2] = s[2] or media
    guardar(sesiones, ajustes)
    anunciar(efecto_out, f"← Salida a las {t.strftime('%H:%M')} (sesión de {dur(t - s[0])})"
             + (" · media jornada" if media else ""))
    cmd_status([])


def cmd_undo(args):
    sesiones, ajustes = cargar()
    if not sesiones:
        sys.exit("No hay ningún fichaje que deshacer.")
    s = sesiones[-1]
    if s[1] is None:
        sesiones.pop()
        print(f"↶ Deshecha la entrada del {etiqueta(s[0])} a las {s[0].strftime('%H:%M')}")
    else:
        print(f"↶ Deshecha la salida del {etiqueta(s[1])} a las {s[1].strftime('%H:%M')}")
        s[1] = None
    guardar(sesiones, ajustes)
    cmd_status([])


def cmd_ajuste(args):
    td = leer_dur(args[0]) if args else None
    if not td:
        sys.exit("Uso: horas ajuste ±DURACIÓN [nota]\n"
                 "Ejemplos: horas ajuste +2h · horas ajuste -30m · "
                 "horas ajuste +1h30m saldo inicial")
    sesiones, ajustes = cargar()
    nota = " ".join(args[1:]).strip()
    ajustes.append([ahora().date(), td, nota])
    guardar(sesiones, ajustes)
    print(f"± Ajuste de {dur(td, signo=True)} registrado" + (f" ({nota})" if nota else ""))
    cmd_status([])


def cmd_status(args):
    sesiones, ajustes = cargar()
    dias = por_dia(sesiones)
    t = ahora()
    hoy = t.date()
    s = abierta(sesiones)
    ses_hoy = dias.get(hoy, [])
    hecho = trabajado(ses_hoy)
    meta = objetivo(hoy, ses_hoy)
    saldo = saldo_total(dias, ajustes)
    pendientes = [d for d, ses in dias.items() if d < hoy and not cerrado(d, ses)]

    if s and s[0].date() < hoy:
        print(rojo(f"⚠ Tienes una sesión abierta desde el {etiqueta(s[0])} "
                   f"a las {s[0].strftime('%H:%M')}."))
        print(rojo("  Si olvidaste fichar la salida: `horas out HH:MM` "
                   "(la hora a la que saliste ese día)."))
    elif s:
        print(verde("● DENTRO") + f" desde las {s[0].strftime('%H:%M')}")
    else:
        print(gris("○ FUERA"))

    falta = meta - hecho
    linea = f"  Hoy:    {negrita(dur(hecho))} de {dur(meta)}"
    if es_media(ses_hoy):
        linea += " (media jornada)"
    if falta > CERO:
        linea += f"  · faltan {dur(falta)}"
    elif falta < CERO:
        linea += "  · " + verde(f"objetivo cumplido ({dur(-falta)} extra)")
    else:
        linea += "  · " + verde("objetivo cumplido")
    print(linea)

    linea = f"  Saldo:  {saldo_color(saldo)} acumulado hasta ayer"
    if pendientes:
        linea += gris(f" (sin contar el {etiqueta(pendientes[0])}, pendiente de cerrar)")
    print(linea)

    # A qué hora puedes cortar (solo tiene sentido si estás dentro hoy)
    if s and s[0].date() == hoy:
        if falta > CERO:
            print(f"  Salida: a las {(t + falta).strftime('%H:%M')} cumples el día")
        if saldo != CERO:
            a_cero = falta - saldo
            if a_cero > CERO:
                print(f"          a las {(t + a_cero).strftime('%H:%M')} dejas el saldo a cero")
            else:
                print(f"          si cortas ahora el saldo queda en {saldo_color(-a_cero)}")


def cmd_semana(args):
    try:
        atras = abs(int(args[0])) if args else 0
    except ValueError:
        sys.exit("Uso: horas semana [N]   (N = cuántas semanas hacia atrás)")
    sesiones, _ = cargar()
    hoy = ahora().date()
    lunes = hoy - timedelta(days=hoy.weekday(), weeks=atras)
    domingo = lunes + timedelta(days=6)
    semana = {d: s for d, s in por_dia(sesiones).items() if lunes <= d <= domingo}

    print(negrita(f"Semana del {etiqueta(lunes)} al {etiqueta(domingo)}"))
    if not semana:
        print("  Sin registros.")
        return
    total = dif_total = CERO
    sin_cerrar = False
    for d, ses in semana.items():
        hecho = trabajado(ses)
        total += hecho
        if cerrado(d, ses):
            dif = hecho - objetivo(d, ses)
            dif_total += dif
            col = saldo_color(dif, 8)
        else:
            sin_cerrar = True
            col = gris(f"{'en curso' if d == hoy else 'sin cerrar':>10}")
        print(f"  {etiqueta(d, es_media(ses)):<12}  {dur(hecho):>7}  {col}")
    print(f"  {negrita('Total'.ljust(12))}  {negrita(dur(total).rjust(7))}  "
          f"{saldo_color(dif_total, 8)}" + (gris("  (solo días cerrados)") if sin_cerrar else ""))


def cmd_log(args):
    try:
        n = int(args[0]) if args else 14
    except ValueError:
        sys.exit("Uso: horas log [N]")
    sesiones, ajustes = cargar()
    dias = por_dia(sesiones)
    if not dias and not ajustes:
        print("Todavía no hay registros.")
        return
    hoy = ahora().date()

    # Días y ajustes mezclados por fecha (los ajustes de un día van antes)
    eventos = [(a[0], 0, a) for a in ajustes] + [(d, 1, ses) for d, ses in dias.items()]
    eventos.sort(key=lambda e: (e[0], e[1]))

    # Cada fila: (fecha, detalle, total, diferencia, saldo); None = no aplica
    filas, saldo = [], CERO
    for d, tipo, dato in eventos:
        if tipo == 0:
            saldo += dato[1]
            detalle = "ajuste" + (f": {dato[2]}" if dato[2] else "")
            filas.append((etiqueta(d), detalle, "", dato[1], saldo))
            continue
        tramos = " ".join(
            f"{i.strftime('%H:%M')}-{f.strftime('%H:%M') if f else '…'}" for i, f, _ in dato)
        total = dur(trabajado(dato))
        fecha = etiqueta(d, es_media(dato))
        if cerrado(d, dato):
            dif = trabajado(dato) - objetivo(d, dato)
            saldo += dif
            filas.append((fecha, tramos, total, dif, saldo))
        else:
            filas.append((fecha, tramos, total, None, "en curso" if d == hoy else "sin cerrar"))
    filas = filas[-n:]

    ancho = max(len("Sesiones"), *(len(f[1]) for f in filas))
    print(negrita(f"{'Fecha':<12}  {'Sesiones':<{ancho}}  {'Total':>7}  {'Dif.':>8}  {'Saldo':>8}"))
    for fecha, detalle, total, dif, acum in filas:
        if dif is None:
            resto = gris(f"{acum:>8}")
        else:
            resto = f"{saldo_color(dif, 8)}  {saldo_color(acum, 8)}"
        print(f"{fecha:<12}  {detalle:<{ancho}}  {total:>7}  {resto}")


def cmd_edit(args):
    ARCHIVO.touch()
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    subprocess.call([editor, str(ARCHIVO)])
    cargar()   # valida el formato tras editar
    print(f"Datos en {ARCHIVO}")


COMANDOS = {
    "in": cmd_in, "i": cmd_in, "entrar": cmd_in,
    "out": cmd_out, "o": cmd_out, "salir": cmd_out,
    "status": cmd_status, "s": cmd_status,
    "undo": cmd_undo, "u": cmd_undo, "deshacer": cmd_undo,
    "semana": cmd_semana, "w": cmd_semana,
    "log": cmd_log, "l": cmd_log,
    "ajuste": cmd_ajuste,
    "edit": cmd_edit,
}


def main():
    args = sys.argv[1:]
    if not args:
        return cmd_status([])
    if args[0] in ("-h", "--help", "help", "ayuda", "h"):
        return print(__doc__)
    cmd = COMANDOS.get(args[0])
    if not cmd:
        sys.exit(f"Comando desconocido: {args[0]!r}\n{__doc__}")
    cmd(args[1:])


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:      # p. ej. `horas log | head`
        sys.stderr.close()
