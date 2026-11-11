; framerect.g -- FRAME a rectangle with the POINTER (laser OFF), in
; machine coordinates = the ones of the map. Used by the "Prepare" wizard of
; the Zones page to trace the material of a zone before cutting.
; Like framecutarea.g: raises Z 5 mm, traces and lowers it again.
;
; Use:  M98 P"0:/sys/workshop/macros/work/framerect.g" A10 B310 C0 D200    (Xmin Xmax Ymin Ymax)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var feed = 3000

if !exists(param.A) || !exists(param.B) || !exists(param.C) || !exists(param.D)
    abort {var.en ? ("Frame: A B C D missing (Xmin Xmax Ymin Ymax)") : ("Enmarcar: faltan A B C D (Xmin Xmax Ymin Ymax)")}
if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Frame: a job is running") : ("Enmarcar: hay un trabajo en curso")}
if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Frame: home X and Y first") : ("Enmarcar: primero hace homing de X e Y")}

var x0 = max(min(param.A, param.B), move.axes[0].min)
var x1 = min(max(param.A, param.B), move.axes[0].max)
var y0 = max(min(param.C, param.D), move.axes[1].min)
var y1 = min(max(param.C, param.D), move.axes[1].max)

M400
G91
G1 H2 Z5 F600 S0                    ; raise 5 mm before moving X/Y
G90
G53 G1 X{var.x0} Y{var.y0} F{var.feed} S0
G53 G1 X{var.x1} Y{var.y0} F{var.feed} S0
G53 G1 X{var.x1} Y{var.y1} F{var.feed} S0
G53 G1 X{var.x0} Y{var.y1} F{var.feed} S0
G53 G1 X{var.x0} Y{var.y0} F{var.feed} S0
M400
G91
G1 H2 Z-5 F600 S0                   ; Z back to where it was
G90
if var.en
    M118 P0 S{"Framed with the pointer: X " ^ var.x0 ^ " to " ^ var.x1 ^ ", Y " ^ var.y0 ^ " to " ^ var.y1}
else
    M118 P0 S{"Enmarcado con el puntero: X " ^ var.x0 ^ " a " ^ var.x1 ^ ", Y " ^ var.y0 ^ " a " ^ var.y1}
