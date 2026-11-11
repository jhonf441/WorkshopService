; laserfocus.g
; Selects the origin of a material, MEASURES the surface of the material with the
; probe (zmeasure.g, by the type of probe the machine declares) and leaves the laser at the
; focus distance above that surface.
; So the height does not depend on what Z was homed on before
; (empty bed or another sheet thickness).
;
; Use:  M98 P"0:/sys/workshop/macros/focus/laserfocus.g" W2 H7.5 N"MDF 3mm"
;   W = workplace: 1=G54 2=G55 3=G56 4=G57 5=G58 6=G59
;   H = focus distance in mm ABOVE the surface of the material, 0.3 to 60 (the same range as focusrule.g and focushere.g). Optional if T is
;       given: then it is calculated from the thickness (focusrule.g: the maker table + the measured geometry)
;   N = name for the message (optional)
;   Q = 1: ask first whether there is material on the table (Cancel stops before moving)
;   T = expected thickness of the material in mm (optional): if the measurement does
;       not match, it asks before going on (see zsurface.g)
;   X Y = point where the probe touches, relative to the zero of the zone (optional,
;         X30 Y30 if missing). The Zones page writes it when the measuring point
;         is chosen on the map (request 2026-10-09).

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var probeX = exists(param.X) ? param.X : 30     ; measuring point, relative to the zero of the material
var probeY = exists(param.Y) ? param.Y : 30
var clearZ = 15                                 ; minimum height to move in XY without touching the sheet
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402

if !exists(param.W) || (!exists(param.H) && !exists(param.T))
    abort {var.en ? ("laserfocus: W (workplace) and H (focus) or T (thickness) missing") : ("laserfocus: faltan W (sistema de trabajo) y H (foco) o T (grosor)")}
if param.W < 1 || param.W > 6
    abort {var.en ? ("laserfocus: W must be 1..6 (G54..G59)") : ("laserfocus: W debe ser 1..6 (G54..G59)")}
if exists(param.H) && (param.H < 0.3 || param.H > 60)
    abort {var.en ? ("laserfocus: H" ^ param.H ^ " out of range (0.3 to 60 mm)") : ("laserfocus: H" ^ param.H ^ " fuera de rango (0.3 a 60 mm)")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Laser focus: home all axes first") : ("Foco laser: primero hace homing de todos los ejes")}

; 2026-10-18: livemark.g (the last line of the material macros) refuses to open the job if this macro did not get to its end: a probe that did
; not trigger, a BLTouch alarm (M280) or any error here aborts THIS macro only, and the line that follows would carry on as if the focus was set.
if !exists(global.workshopFocusOk)
    global workshopFocusOk = true
set global.workshopFocusOk = false

; Q1 = ask first whether there is material on the table (the "Ask if there is material before focusing" box of the zone). Cancel aborts this
; macro before anything moves; workshopFocusOk stays false, so livemark.g stops the job too.
if exists(param.Q) && param.Q == 1
    M291 P{var.en ? "Is there material on the table? OK = measure and focus, Cancel = stop." : "Hay material en la mesa? OK = medir y enfocar, Cancelar = parar."} R"Material" S3

; The BLTouch pin has to be STOWED before moving (request
; 2026-10-08): if it was left out (e.g. probe offset wizard) a possible alarm
; is cleared and it is stowed. If it was already stowed nothing happens. Only a BLTouch has a pin.
if var.servo
    M280 P0 S160                                ; clear the BLTouch alarm (raises the pin)
    G4 P300
    M402                                        ; stow the pin
    G4 P300

var name = exists(param.N) ? param.N : ("P" ^ param.W)

; focus height: given (H) or calculated from the thickness (T)
var focusH = exists(param.H) ? param.H : 0
if !exists(param.H)
    M98 P"0:/sys/workshop/macros/focus/focusrule.g" T{param.T}
    set var.focusH = global.focusRuleH
; the height that G53 G0 Z will use below, whichever way it was given: never outside the range focusrule.g and focushere.g accept
if var.focusH < 0.3 || var.focusH > 60
    abort {var.en ? ("laserfocus: focus height H" ^ var.focusH ^ " is out of range (0.3 to 60 mm)") : ("laserfocus: la altura de foco H" ^ var.focusH ^ " esta fuera de rango (0.3 a 60 mm)")}

if !exists(global.laserOffsetOn)
    global laserOffsetOn = true
set global.laserOffsetOn = true                 ; a laser job is being prepared: offset always applied
M98 P"0:/sys/workshop/macros/work/wpload.g"                          ; reapplies the saved origins (fast ~0.6 s; the full workplaces.g took ~2.9 s and the cut area is already loaded)
M400
G90

if param.W == 1
    G54
elif param.W == 2
    G55
elif param.W == 3
    G56
elif param.W == 4
    G57
elif param.W == 5
    G58
else
    G59

G53 G0 Z{max(move.axes[2].machinePosition, var.clearZ)}   ; raise before moving
; The PROBE has to TOUCH at X30 Y30 of the material (not the head): the head goes
; to point - G31 offset of the probe. If with that offset the head cannot reach
; (near the edge of the machine), the point is moved into the
; material just enough.
var ox = sensors.probes[0].offsets[0]
var oy = sensors.probes[0].offsets[1]
var wx = move.axes[0].workplaceOffsets[move.workplaceNumber]
var wy = move.axes[1].workplaceOffsets[move.workplaceNumber]
set var.probeX = max(var.probeX, move.axes[0].min - var.wx + var.ox + 1)
set var.probeY = max(var.probeY, move.axes[1].min - var.wy + var.oy + 1)
set var.probeX = min(var.probeX, move.axes[0].max - var.wx + var.ox - 1)
set var.probeY = min(var.probeY, move.axes[1].max - var.wy + var.oy - 1)
G0 X{var.probeX - var.ox} Y{var.probeY - var.oy}  ; head placed so that the PROBE is over the measuring point
M98 P"0:/sys/workshop/macros/zcal/zmeasure.g"        ; measure: Z0 = surface of the material (by probe type)
M98 P"0:/sys/workshop/macros/zcal/zsurface.g" T{exists(param.T) ? param.T : 0} N{var.name}   ; thickness (T = expected)
G53 G0 Z{var.focusH}                            ; focus distance above the surface

var tmsg1 = var.name ^ ": superficie medida en X" ^ var.probeX ^ " Y" ^ var.probeY ^ ", laser a " ^ var.focusH ^ "mm sobre el material"
if var.en
    set var.tmsg1 = var.name ^ ": surface measured at X" ^ var.probeX ^ " Y" ^ var.probeY ^ ", laser at " ^ var.focusH ^ "mm above the material"
M118 P0 S{var.tmsg1}
set global.workshopFocusOk = true                  ; reached the end: the probe triggered and the laser is at its height
