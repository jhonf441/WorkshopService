; zcal-szp.g -- Calibrate the Scanning Z Probe (SZP, probe K1) in FFF
; (WorkshopJog), following the Duet3D guide "Scanning Z probe calibration".
; Needs Z0 = valid bed (Z homed). Puts the SZP over X Y and:
;   A1 = drive level: at the trigger height (G31 K1 Z) runs
;        M558.2 K1 S-1 and then M558.2 K1 (reports S and R to save)
;   A2 = height vs reading: from Z6 runs M558.1 K1 S1.7 and M558.1 K1
;        (the coefficients change with the temperature: they are NOT saved; the
;        guide recommends repeating it before every mesh)
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zcal-szp.g" X120 Y80 A1

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var modo = exists(global.selectedMode) ? global.selectedMode : state.machineMode
if var.modo != "FFF"
    abort {var.en ? ("SZP: only in FFF mode") : ("SZP: solo en modo FFF")}
if #sensors.probes < 2 || sensors.probes[1] == null
    abort {var.en ? ("SZP: there is no probe K1 (M558 K1) in this mode") : ("SZP: no hay sonda K1 (M558 K1) en este modo")}
if !exists(param.X) || !exists(param.Y) || !exists(param.A)
    abort {var.en ? ("SZP: X, Y and A missing") : ("SZP: faltan X, Y y A")}
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("SZP: home all axes first (Z0 = bed)") : ("SZP: primero hace homing de todos los ejes (Z0 = cama)")}

var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402
var ox = sensors.probes[1].offsets[0]
var oy = sensors.probes[1].offsets[1]
var hx = min(max(param.X - var.ox, move.axes[0].min), move.axes[0].max)
var hy = min(max(param.Y - var.oy, move.axes[1].min), move.axes[1].max)

if var.servo
    M280 P0 S160                                ; BLTouch: pin stowed before moving
    G4 P300
    M402
    G4 P300
M400
G90
G53 G0 Z{max(move.axes[2].machinePosition, 10)}
G53 G0 X{var.hx} Y{var.hy}
if param.A == 1
    G0 Z{sensors.probes[1].triggerHeight}       ; minimum height of use = trigger height
    M400
    M558.2 K1 S-1                               ; calibrate the drive level
    M558.2 K1                                   ; report S (level) and R (reading offset)
else
    G0 Z6                                       ; above the range (avoids axis backlash)
    M400
    M558.1 K1 S1.7                              ; calibrate height vs reading (+-1.7 mm)
    M558.1 K1                                   ; report the coefficients
G0 Z10
M400
