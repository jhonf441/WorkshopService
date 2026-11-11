; visionpose.g -- puts the GANTRY (with the camera) at Y / Z to take a
; measuring photo (Vision page, WorkshopVision). The camera is on the gantry: Z
; raises/lowers it and Y centres it; X does not change what it sees.
;
; Use:  M98 P"0:/sys/workshop/macros/probe/visionpose.g" Y123.4 Z200     (Y or Z can be missing)
;       X123.4 too, if the camera is on the CARRIAGE (Vision page > Settings):
;       X moves together with Y (after raising Z / before lowering it).
;
; Safe order: going up, first Z and then Y; going down, first Y (still
; high) and Z at the end. MACHINE coordinates (G53). LASER: every G1 with S0.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false
var zmin = 40                       ; never lower the gantry below this for a photo (mm)
var fy = 3000                       ; mm/min (M203 limits it)
var fz = 1200

if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Camera pose: a job is running") : ("Posicion de foto: hay un trabajo en curso")}
if !exists(param.Y) && !exists(param.Z) && !exists(param.X)
    abort {var.en ? ("Camera pose: X, Y and/or Z missing") : ("Posicion de foto: falta X, Y y/o Z")}
if exists(param.X) && !move.axes[0].homed
    abort {var.en ? ("Camera pose: home X first") : ("Posicion de foto: primero hace homing de X")}
if !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Camera pose: home Y and Z first") : ("Posicion de foto: primero hace homing de Y y Z")}

var tx = exists(param.X) ? param.X : move.axes[0].machinePosition
var ty = exists(param.Y) ? param.Y : move.axes[1].machinePosition
var tz = exists(param.Z) ? param.Z : move.axes[2].machinePosition
if var.tx < move.axes[0].min || var.tx > move.axes[0].max
    abort {var.en ? ("Camera pose: X" ^ var.tx ^ " is outside the travel") : ("Posicion de foto: X" ^ var.tx ^ " esta fuera del recorrido")}
if var.ty < move.axes[1].min || var.ty > move.axes[1].max
    abort {var.en ? ("Camera pose: Y" ^ var.ty ^ " is outside the travel") : ("Posicion de foto: Y" ^ var.ty ^ " esta fuera del recorrido")}
if var.tz > move.axes[2].max
    abort {var.en ? ("Camera pose: Z" ^ var.tz ^ " is above the maximum") : ("Posicion de foto: Z" ^ var.tz ^ " pasa el maximo")}
if var.tz < var.zmin
    abort {var.en ? ("Camera pose: Z" ^ var.tz ^ " is below " ^ var.zmin ^ " mm (too close to the material)") : ("Posicion de foto: Z" ^ var.tz ^ " es menor que " ^ var.zmin ^ " mm (muy cerca del material)")}

G90                             ; absolute: the calling channel may have been left in G91 (jog, loose G91/G1/G90); when the macro ends it goes back to the previous mode by itself
M400
if var.tz >= move.axes[2].machinePosition
    G53 G1 Z{var.tz} F{var.fz} S0
    G53 G1 X{var.tx} Y{var.ty} F{var.fy} S0
else
    G53 G1 X{var.tx} Y{var.ty} F{var.fy} S0
    G53 G1 Z{var.tz} F{var.fz} S0
M400
