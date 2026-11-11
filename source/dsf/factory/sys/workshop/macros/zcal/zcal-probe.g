; zcal-probe.g -- Calibrate the height of the probe (WorkshopJog). Needs
; Z0 to be the surface just marked with the paper (zcal-mark.g). Puts the
; PROBE over the same point X Y and measures with G30 S-1: it does NOT change Z, it only
; reports at what height it triggered. That height is the right G31 Z of the mode.
; It is left in global.workshopZcalMed (the page reads it and offers to save it).
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zcal-probe.g" X120 Y80

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if !exists(param.X) || !exists(param.Y)
    abort {var.en ? ("Calibrate: X and Y missing") : ("Calibrar: faltan X e Y")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Calibrate: home all axes first") : ("Calibrar: primero hace homing de todos los ejes")}
if !exists(sensors.probes[0])
    abort {var.en ? ("Calibrate: there is no probe configured") : ("Calibrar: no hay sonda configurada")}
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402
if !exists(global.workshopZcalMed)
    global workshopZcalMed = -1
set global.workshopZcalMed = -1

var ox = sensors.probes[0].offsets[0]
var oy = sensors.probes[0].offsets[1]
var hx = min(max(param.X - var.ox, move.axes[0].min), move.axes[0].max)
var hy = min(max(param.Y - var.oy, move.axes[1].min), move.axes[1].max)

if var.servo
    M280 P0 S160                                ; clear the BLTouch alarm
    G4 P300
    M402
    G4 P300
M400
G90
G0 Z{max(move.axes[2].userPosition, 5)}         ; 5 mm above the surface (room to deploy)
G53 G0 X{var.hx} Y{var.hy}
G30 S-1                                         ; measure without changing Z: reports the trigger height
M400
set global.workshopZcalMed = sensors.probes[0].lastStopHeight
G0 Z5
M400
var zth = sensors.probes[0].triggerHeight
if var.en
    M118 P0 S{"Calibrate: the probe triggered at " ^ global.workshopZcalMed ^ " mm (current G31 Z: " ^ var.zth ^ ")"}
else
    M118 P0 S{"Calibrar: la sonda disparo a " ^ global.workshopZcalMed ^ " mm (G31 Z actual: " ^ var.zth ^ ")"}
if abs(var.hx + var.ox - param.X) > 0.05 || abs(var.hy + var.oy - param.Y) > 0.05
    if var.en
        M118 P0 S{"Note: the probe couldn't reach the same point (machine edge): the result may be off"}
    else
        M118 P0 S{"Ojo: la sonda no llegaba al mismo punto (borde de la maquina): el resultado puede no servir"}
