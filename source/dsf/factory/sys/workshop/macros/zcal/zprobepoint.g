; zprobepoint.g -- "Measure Z at the point" (WorkshopJog, Zones > Active zone >
; Z height and focus). Measures the surface with the probe (K0, it exists in the 3
; modes with its own G31; zmeasure.g measures by the type of probe the machine declares) at a
; point of the MAP and leaves Z0 = that surface.
; What Z0 means depends on the mode:
;   Laser: surface of the material; then it goes up to H mm (focus).
;   CNC:   top face of the material (zero of the tool); goes up to H
;          (or 5 mm) to stay at a safe height.
;   FFF:   the bed at that point (like homez.g but where one chooses); goes up to
;          H (or 5 mm). The mesh (G29) is still applied on top.
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zprobepoint.g" X120 Y80 H7.5
;   X Y = point where the probe TOUCHES, in machine coordinates (the ones of the map,
;         where the pointer lands). The head goes to point - G31 offset.
;   H   = final height above the measured surface (optional, 5 mm if missing)
;   T   = expected thickness of the material (optional, see zsurface.g)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var modo = exists(global.selectedMode) ? global.selectedMode : state.machineMode   ; machine mode (global.selectedMode if it exists; otherwise the RRF one)
var clearZ = 10                                 ; minimum height before moving / deploying the probe
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402

if !exists(param.X) || !exists(param.Y)
    abort {var.en ? ("Measure Z: X and Y missing (point where the probe touches)") : ("Medir Z: faltan X e Y (punto donde toca la sonda)")}
var h = exists(param.H) ? param.H : 5
if var.h < 1 || var.h > 60
    abort {var.en ? ("Measure Z: H" ^ var.h ^ " out of range (1 to 60 mm)") : ("Medir Z: H" ^ var.h ^ " fuera de rango (1 a 60 mm)")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Measure Z: home all axes first") : ("Medir Z: primero hace homing de todos los ejes")}

; Head placed so that the PROBE is over the point. If with the offset the head
; cannot reach (edge of the machine), it is moved just enough and a note is shown.
var ox = sensors.probes[0].offsets[0]
var oy = sensors.probes[0].offsets[1]
var hx = min(max(param.X - var.ox, move.axes[0].min), move.axes[0].max)
var hy = min(max(param.Y - var.oy, move.axes[1].min), move.axes[1].max)

; BLTouch pin STOWED before moving (like laserfocus.g). Only a BLTouch has a pin.
if var.servo
    M280 P0 S160                                ; clear the BLTouch alarm (raises the pin)
    G4 P300
    M402                                        ; stow the pin
    G4 P300

M400
G90
G53 G0 Z{max(move.axes[2].machinePosition, var.clearZ)}   ; raise before moving
G53 G0 X{var.hx} Y{var.hy}
M98 P"0:/sys/workshop/macros/zcal/zmeasure.g"        ; measure: Z0 = surface under the probe (by probe type)
M98 P"0:/sys/workshop/macros/zcal/zsurface.g" T{exists(param.T) ? param.T : 0}   ; thickness (T = expected, optional)
G53 G0 Z{var.h}
M400

var px = var.hx + var.ox
var py = var.hy + var.oy
var what = var.en ? ((var.modo == "Laser") ? "laser (focus)" : (var.modo == "CNC") ? "tool" : "nozzle") : ((var.modo == "Laser") ? "laser (foco)" : (var.modo == "CNC") ? "herramienta" : "boquilla")
var tmsg1 = "Z0 medido en X" ^ var.px ^ " Y" ^ var.py ^ " (" ^ var.modo ^ "); " ^ var.what ^ " a " ^ var.h ^ " mm sobre la superficie"
if var.en
    set var.tmsg1 = "Z0 measured at X" ^ var.px ^ " Y" ^ var.py ^ " (" ^ var.modo ^ "); " ^ var.what ^ " at " ^ var.h ^ " mm above the surface"
M118 P0 S{var.tmsg1}
if abs(var.px - param.X) > 0.05 || abs(var.py - param.Y) > 0.05
    if var.en
        M118 P0 S{"Note: the head couldn't reach it, it measured shifted (requested X" ^ param.X ^ " Y" ^ param.Y ^ ")"}
    else
        M118 P0 S{"Ojo: el cabezal no llegaba, se midio corrido (pedido X" ^ param.X ^ " Y" ^ param.Y ^ ")"}
