; framecutarea.g -- FRAME the cut area of the active mode: traces its
; outline with the POINTER (laser OFF) to see where it is, like the
; "Frame" of the cutting programs. Called by the "Frame" buttons of WorkshopJog
; (jog panel and Work zones page).
;
; The area (sys/workshop/zones/cutarea.g, global.cutArea<Mode> = {Xmin, Xmax, Ymin, Ymax})
; is in BED coordinates = where the pointer lands = MACHINE coordinates of
; X/Y, so it is traced with G53 (ignores the active workplace).
;
; Raises Z 5 mm before moving (like homex.g) and lowers it again at the
; end. Ends at the Xmin/Ymin corner.
; LASER: every G1 carries S0 (zero power in Laser mode; in CNC/FFF S
; is ignored): rule "every G1 carries S0".

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var modo = exists(global.selectedMode) ? global.selectedMode : state.machineMode   ; machine mode (global.selectedMode if it exists; otherwise the RRF one)
var feed = 3000                     ; mm/min of the trace (50 mm/s)

if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Frame: a job is running") : ("Enmarcar: hay un trabajo en curso")}
if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Frame: home X and Y first") : ("Enmarcar: primero hace homing de X e Y")}

var area = null
if true
    if var.modo == "Laser" && exists(global.cutAreaLaser)
        set var.area = global.cutAreaLaser
    elif var.modo == "CNC" && exists(global.cutAreaCNC)
        set var.area = global.cutAreaCNC
    elif var.modo == "FFF" && exists(global.cutAreaFFF)
        set var.area = global.cutAreaFFF
if var.area == null
    abort {var.en ? ("Frame: the cut area of this mode has not been measured") : ("Enmarcar: el area de corte de este modo no esta medida")}

; just in case: never leave the travel even if the file was edited by hand
var x0 = max(var.area[0], move.axes[0].min)
var x1 = min(var.area[1], move.axes[0].max)
var y0 = max(var.area[2], move.axes[1].min)
var y1 = min(var.area[3], move.axes[1].max)

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
    M118 P0 S{"Cut area framed: X " ^ var.x0 ^ " to " ^ var.x1 ^ ", Y " ^ var.y0 ^ " to " ^ var.y1}
else
    M118 P0 S{"Area de corte enmarcada: X " ^ var.x0 ^ " a " ^ var.x1 ^ ", Y " ^ var.y0 ^ " a " ^ var.y1}
