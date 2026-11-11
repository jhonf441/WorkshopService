; zcal-goto.g -- Calibrate the height (WorkshopJog, Zones > Active zone > Z height
; > Calibrate). Takes the TOOL (laser / cutter / nozzle, the cross of the
; map) over the point X Y, without going down: it stays at Z max(current, 10). Then the
; user goes down in small steps until it brushes a sheet of paper (zcal-mark.g).
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zcal-goto.g" X120 Y80

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var clearZ = 10                                 ; minimum height before moving
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402

if !exists(param.X) || !exists(param.Y)
    abort {var.en ? ("Calibrate: X and Y missing") : ("Calibrar: faltan X e Y")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Calibrate: home all axes first") : ("Calibrar: primero hace homing de todos los ejes")}

; BLTouch pin STOWED before moving (like zprobepoint.g). Only a BLTouch has a pin.
if var.servo
    M280 P0 S160                                ; clear the BLTouch alarm (raises the pin)
    G4 P300
    M402                                        ; stow the pin
    G4 P300

M400
G90
G53 G0 Z{max(move.axes[2].machinePosition, var.clearZ)}   ; raise before moving
G53 G0 X{min(max(param.X, move.axes[0].min), move.axes[0].max)} Y{min(max(param.Y, move.axes[1].min), move.axes[1].max)}
M400
var tmsg1 = "Calibrar: herramienta sobre X" ^ param.X ^ " Y" ^ param.Y ^ ". Bajala con pasos chicos hasta que roce un papel."
if var.en
    set var.tmsg1 = "Calibrate: tool over X" ^ param.X ^ " Y" ^ param.Y ^ ". Lower it in small steps until it just drags a sheet of paper."
M118 P0 S{var.tmsg1}
