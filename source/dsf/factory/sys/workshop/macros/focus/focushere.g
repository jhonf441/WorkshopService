; focushere.g -- "Focus here" (WorkshopJog, steps that need the laser
; focused, e.g. Measure the probe offset). Like laserfocus.g but WITHOUT
; changing zone or moving in X/Y: it measures the surface with the probe (zmeasure.g, by the
; type of probe the machine declares) where it is now (the probe touches at head + G31 offset)
; and leaves the laser at H mm.
;
; Use:  M98 P"0:/sys/workshop/macros/focus/focushere.g" H7.5      (H = focus in mm ABOVE the surface, 0.3 to 60 like laserfocus.g and focusrule.g)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var clearZ = 10                                 ; minimum height before deploying the probe
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402

if !exists(param.H)
    abort {var.en ? ("Focus: H missing (focus height in mm)") : ("Enfocar: falta H (altura de foco en mm)")}
if param.H < 0.3 || param.H > 60
    abort {var.en ? ("Focus: H" ^ param.H ^ " out of range (0.3 to 60 mm)") : ("Enfocar: H" ^ param.H ^ " fuera de rango (0.3 a 60 mm)")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Focus: home all axes first") : ("Enfocar: primero hace homing de todos los ejes")}

; The BLTouch pin has to be STOWED before moving (request
; 2026-10-08): if it was left out (e.g. probe offset wizard) a possible alarm
; is cleared and it is stowed. If it was already stowed nothing happens. Only a BLTouch has a pin.
if var.servo
    M280 P0 S160                                ; clear the BLTouch alarm (raises the pin)
    G4 P300
    M402                                        ; stow the pin
    G4 P300

M400
G90
G53 G0 Z{max(move.axes[2].machinePosition, var.clearZ)}   ; leave room to deploy the probe
M98 P"0:/sys/workshop/macros/zcal/zmeasure.g"        ; measure: Z0 = surface under the probe (by probe type)
M98 P"0:/sys/workshop/macros/zcal/zsurface.g" T{exists(param.T) ? param.T : 0}   ; thickness
G53 G0 Z{param.H}                               ; laser H mm above that surface
M400
var tmsg1 = "Enfocado aqui: laser a " ^ param.H ^ " mm sobre la superficie (medida en X" ^ (move.axes[0].machinePosition + sensors.probes[0].offsets[0]) ^ " Y" ^ (move.axes[1].machinePosition + sensors.probes[0].offsets[1]) ^ ")"
if var.en
    set var.tmsg1 = "Focused here: laser at " ^ param.H ^ " mm above the surface (measured at X" ^ (move.axes[0].machinePosition + sensors.probes[0].offsets[0]) ^ " Y" ^ (move.axes[1].machinePosition + sensors.probes[0].offsets[1]) ^ ")"
M118 P0 S{var.tmsg1}
