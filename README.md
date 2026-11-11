# horas

Control de horas de trabajo desde la terminal: fichas al entrar, fichas al salir y siempre sabes cuánto llevas hoy, a qué hora puedes cortar y cuántas horas debes o te deben.

Es un único script de Python sin dependencias. Los datos se guardan en un fichero de texto que puedes leer y corregir a mano.

```
$ horas in
→ Entrada a las 14:25
● DENTRO desde las 14:25
  Hoy:    5h 33m de 8h 00m  · faltan 2h 27m
  Saldo:  +2h 00m acumulado hasta ayer
  Salida: a las 17:50 cumples el día
          a las 15:50 dejas el saldo a cero
```

## Instalación

Necesita Python 3.8 o posterior.

```bash
git clone https://github.com/<tu-usuario>/horas.git
cp horas/horas.py ~/.local/bin/horas
chmod +x ~/.local/bin/horas
```

Comprueba que `~/.local/bin` está en tu `PATH`. Está pensado para Linux y macOS; en Windows debería funcionar con `python horas.py`, pero no está probado.

## Uso

| Comando | Qué hace |
|---|---|
| `horas` | Estado de hoy: horas trabajadas, cuánto falta, saldo y hora de salida |
| `horas in [HH:MM]` | Fichar entrada, ahora o a la hora indicada |
| `horas out [HH:MM]` | Fichar salida, ahora o a la hora indicada |
| `horas in --media` | Fichar entrada y marcar hoy como media jornada |
| `horas undo` | Deshacer el último fichaje |
| `horas semana [N]` | Resumen de esta semana, o de hace N semanas |
| `horas log [N]` | Historial: las últimas N líneas (14 por defecto) |
| `horas ajuste ±DUR [nota]` | Corregir el saldo a mano |
| `horas edit` | Abrir el fichero de datos en tu editor |
| `horas help` | Mostrar la ayuda |

Atajos de una letra: `i` (in), `o` (out), `s` (status), `u` (undo), `w` (semana), `l` (log).

### Fichar

Ficha la salida cada vez que te levantes (a comer, a un recado) y la entrada al volver. Solo cuenta el tiempo entre una entrada y su salida.

Si se te olvidó fichar, indica la hora:

```bash
horas in 09:15
horas out 18:00
```

Si te fuiste sin fichar la salida, al día siguiente `horas` te avisa. Ciérrala con `horas out HH:MM`; la hora se aplica al día en que empezó esa sesión.

### Saldo

Cada día laborable tiene un objetivo de 8 horas. Lo que trabajes de más o de menos se acumula en el saldo: si un día haces 7 horas y al siguiente 9, vuelves a cero.

- **El día de hoy no entra en el saldo** hasta mañana. Mientras tanto, `horas` te dice a qué hora cumples el día y a qué hora dejarías el saldo a cero.
- **Los días sin ningún fichaje no cuentan.** Festivos y vacaciones no restan, pero un día laborable que no fiches tampoco.
- **Fuera de los días laborables el objetivo es cero**, así que todo lo que trabajes un fin de semana suma.
- **Un día con una sesión sin cerrar queda fuera del saldo** hasta que la cierres.

### Media jornada

```bash
horas in --media      # o: horas in -m
```

El objetivo de hoy pasa a la mitad. Basta con indicarlo una vez al día; si se te olvidó al entrar, también vale `horas out --media`. En el historial esos días aparecen marcados con `½`.

### Deshacer

`horas undo` deshace el último fichaje: si era una entrada, la borra; si era una salida, la sesión vuelve a quedar abierta. Puedes repetirlo para ir más atrás. No afecta a los ajustes.

### Ajustes

Para sumar o restar horas al saldo sin tocar las sesiones, por ejemplo para empezar con el saldo que ya arrastrabas:

```bash
horas ajuste +1h30m saldo inicial
horas ajuste -30m
horas ajuste +2h
```

La duración admite `2h`, `30m`, `1h30m` o `1:30`, con signo opcional. Los ajustes se aplican al saldo en el momento y aparecen en el historial.

### Historial y semana

```
$ horas log
Fecha         Sesiones                   Total      Dif.     Saldo
vie 06/11 ½   09:00-13:30               4h 30m   +0h 30m   +0h 30m
lun 09/11     09:00-13:00 14:00-17:00   7h 00m   -1h 00m   -0h 30m
mar 10/11     08:30-13:30 14:30-18:30   9h 00m   +1h 00m   +0h 30m
mié 11/11     ajuste: saldo inicial              +1h 30m   +2h 00m
mié 11/11     09:05-13:40 14:25-…       5h 33m  en curso

$ horas semana
Semana del lun 09/11 al dom 15/11
  lun 09/11      7h 00m   -1h 00m
  mar 10/11      9h 00m   +1h 00m
  mié 11/11      5h 33m    en curso
  Total         21h 33m   +0h 00m  (solo días cerrados)
```

`horas semana 1` muestra la semana pasada, `horas semana 2` la anterior, y así sucesivamente.

## Configuración

Al principio del script:

```python
OBJETIVO = timedelta(hours=8)      # horas a trabajar cada día laborable
LABORABLES = {0, 1, 2, 3, 4}       # 0 = lunes ... 6 = domingo
```

Los datos se guardan en `~/.horas.csv`. Para usar otra ruta, define la variable de entorno `HORAS_FILE`.

Al fichar se muestra una animación breve, distinta para la entrada y para la salida. Dura menos de un segundo y solo aparece en una terminal interactiva. Para quitarla, define `HORAS_EFECTOS=0`.

## Formato de los datos

Una línea por registro, en texto plano:

```
2026-11-06 09:00,2026-11-06 13:30,media
2026-11-10 08:30,2026-11-10 13:30
2026-11-10 14:30,2026-11-10 18:30
ajuste,2026-11-11,+1h 30m,saldo inicial
2026-11-11 09:05,2026-11-11 13:40
2026-11-11 14:25,
```

- **Sesión:** `inicio,fin`. La sesión en curso tiene el fin vacío.
- **Media jornada:** un tercer campo `media` en cualquier sesión del día.
- **Ajuste:** `ajuste,fecha,±duración,nota`.

Una sesión que cruza la medianoche cuenta entera para el día en que empezó. Para corregir cualquier cosa, `horas edit` abre el fichero en `$EDITOR` y comprueba el formato al cerrar. El script reescribe el fichero en cada fichaje, así que no conserva comentarios ni líneas en blanco que añadas a mano.
