; gotobed.g -- takes the POINTER to a point of the bed (bed coordinates =
; MACHINE coordinates of X/Y, hence G53: ignores the active workplace).
; Used by the "From the map" mode of the cut area measurement
; (WorkshopJog, Work zones page): a point is tapped on the map, the
; machine goes there, it is adjusted with the jog and captured.
;
; Use:  M98 P"0:/sys/workshop/macros/work/gotobed.g" X123.4 Y56.7
;
; Raises Z 5 mm before moving and lowers it again on arrival (same
; height it started with). LASER: every G1 carries S0.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var feed = 3000                     ; mm/min

if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Go to point: a job is running") : ("Ir al punto: hay un trabajo en curso")}
if !exists(param.X) || !exists(param.Y)
    abort {var.en ? ("Go to point: X and Y missing") : ("Ir al punto: faltan X e Y")}
if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Go to point: home X and Y first") : ("Ir al punto: primero hace homing de X e Y")}
if param.X < move.axes[0].min || param.X > move.axes[0].max || param.Y < move.axes[1].min || param.Y > move.axes[1].max
    abort {var.en ? ("Go to point: X" ^ param.X ^ " Y" ^ param.Y ^ " is outside the axis travel") : ("Ir al punto: X" ^ param.X ^ " Y" ^ param.Y ^ " esta fuera del recorrido de los ejes")}

M400
G91
G1 H2 Z5 F600 S0                    ; raise 5 mm before moving X/Y
G90
G53 G1 X{param.X} Y{param.Y} F{var.feed} S0
M400
G91
G1 H2 Z-5 F600 S0                   ; Z back to where it was
G90
