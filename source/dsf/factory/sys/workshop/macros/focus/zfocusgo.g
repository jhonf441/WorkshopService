; zfocusgo.g -- "Go to the focus height" WITHOUT probing.
; Moves Z to the height the zone should have, in MACHINE coordinates: laserfocus.g / focushere.g
; measure the surface with the BLTouch and then leave the laser at G53 Z<H>, so Z<H> is the focus
; as long as the material was measured with this zone and Z was not homed again afterwards.
; NOTHING is measured here: if that is not true the head ends up at the wrong height.
;
; Use:  M98 P"0:/sys/workshop/macros/focus/zfocusgo.g" H7.5      (H = focus height in mm, 1 to 60)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)

if !exists(param.H)
    abort {var.en ? ("Go to focus: H missing (focus height in mm)") : ("Ir a la altura de foco: falta H (altura en mm)")}
if param.H < 1 || param.H > 60
    abort {var.en ? ("Go to focus: H" ^ param.H ^ " out of range (1 to 60 mm)") : ("Ir a la altura de foco: H" ^ param.H ^ " fuera de rango (1 a 60 mm)")}
if !move.axes[2].homed
    abort {var.en ? ("Go to focus: home Z first") : ("Ir a la altura de foco: primero hace homing de Z")}
if param.H < move.axes[2].min || param.H > move.axes[2].max
    abort {var.en ? ("Go to focus: H" ^ param.H ^ " is outside the travel of Z") : ("Ir a la altura de foco: H" ^ param.H ^ " esta fuera del recorrido de Z")}

M400
G90
G53 G1 Z{param.H} F600 S0                       ; slow (Z is limited to 600 mm/min), laser off
M400
var tmsg1 = "Altura de foco: Z a " ^ param.H ^ " mm (sin medir)"
if var.en
    set var.tmsg1 = "Focus height: Z at " ^ param.H ^ " mm (not measured)"
M118 P0 S{var.tmsg1}
