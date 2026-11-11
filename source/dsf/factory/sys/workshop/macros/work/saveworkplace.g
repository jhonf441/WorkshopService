; saveworkplace.g
; Saves the CURRENT position as the origin of workplace W and writes it to
; 0:/sys/workshop/zones/p<W>.g so it survives a power off (workplaces.g
; loads those files at startup).
;
; The file keeps the origin point in BED coordinates (= where the POINTER
; lands); the laser <-> pointer correction of the machine (global.workshopLaserCorrX / Y,
; loaded from sys/workshop/macros/laser/lasercorrection.g, which the service writes from the
; settings store "laser") is only added while the flag global.laserOffsetOn is ON
; (see sys/workshop/macros/laser/laseroffset.g). The zone file keeps no correction of its own.
;
; Use:  M98 P"0:/sys/workshop/macros/work/saveworkplace.g" W2 L0 S"MDF 3mm"
;   W = workplace: 1=G54 2=G55 3=G56 4=G57 5=G58 6=G59 7..9=G59.1..3
;   L = WHAT is over the origin point right now (2026-10-08, to avoid the
;       double offset):
;         L0 (or no L) = the POINTER -> the position is saved as it is
;         L1           = the LASER   -> position - correction is saved
;       (with the laser over the point the pointer is shifted by the
;       correction; saving the raw position and then adding the correction
;       applied it TWICE -- a real bug, 2026-10-08).
;   S = optional zone name -- it goes in the first line of the file with
;       the format "; G55 <name> -- ..." that the jog shows (files written
;       before 2026-10-13 have the rest of that line in Spanish; only the
;       name before " --" is read back).
; Z is always 0: the focus height is set by the macro of each material.
;
; CHECKS (they abort without touching anything if they fail):
;   0) The laser <-> pointer correction has to be KNOWN (lasercorrection.g exists and sets global.workshopLaserCorrKnown to true).
;   1) The origin has to be REACHABLE (inside M208 of the active mode) with
;      the laser offset ON and also OFF -- the flag can be changed later, both
;      resulting origins have to exist.
;   2) If the cut area of the active mode is measured (sys/workshop/zones/cutarea.g,
;      global.cutArea<Mode> = {Xmin, Xmax, Ymin, Ymax} in bed coordinates),
;      the origin point has to be INSIDE it.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var modo = exists(global.selectedMode) ? global.selectedMode : state.machineMode   ; machine mode (global.selectedMode if it exists; otherwise the RRF one)
if !exists(param.W) || param.W < 1 || param.W > 9
    abort {var.en ? ("Save origin: W missing (1..9)") : ("Guardar origen: falta W (1..9)")}
if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Save origin: home X and Y first") : ("Guardar origen: primero hace homing de X e Y")}
if !exists(global.laserOffsetOn)
    global laserOffsetOn = true
if !exists(global.workshopLaserCorrX)
    global workshopLaserCorrX = 0
if !exists(global.workshopLaserCorrY)
    global workshopLaserCorrY = 0
if !exists(global.workshopLaserCorrKnown)
    global workshopLaserCorrKnown = false       ; true only while lasercorrection.g says a correction was MEASURED: 0 0 with false is "unknown", not "zero"
if fileexists("0:/sys/workshop/macros/laser/lasercorrection.g")
    M98 P"0:/sys/workshop/macros/laser/lasercorrection.g"
; An origin is saved as a POINT of the pointer plus the machine's correction, so the correction has to be a MEASURED value: with the file missing or
; Known false, 0 0 is not a measure and the zone would be saved (and later cut) with the laser where the pointer is.
if !fileexists("0:/sys/workshop/macros/laser/lasercorrection.g") || !global.workshopLaserCorrKnown
    abort {var.en ? ("Save origin: the laser-pointer correction is not known (measure it in Machine > Offsets). Nothing was saved.") : ("Guardar origen: la correccion laser-puntero no se conoce (midela en Maquina > Offsets). No se guardo nada.")}

M400                                            ; steady position before reading it

var dx = global.workshopLaserCorrX
var dy = global.workshopLaserCorrY
var laserOver = exists(param.L) && param.L != 0
var x = move.axes[0].machinePosition - (var.laserOver ? var.dx : 0)   ; origin point in bed coordinates
var y = move.axes[1].machinePosition - (var.laserOver ? var.dy : 0)
var f = "0:/sys/workshop/zones/p" ^ param.W ^ ".g"
var code = (param.W <= 6) ? ("G" ^ (53 + param.W)) : ("G59." ^ (param.W - 6))

; --- 1) reachable with the offset ON and OFF
if var.x < move.axes[0].min || var.x > move.axes[0].max || var.x + var.dx < move.axes[0].min || var.x + var.dx > move.axes[0].max
    var rx = "Guardar origen " ^ var.code ^ ": X fuera del recorrido (" ^ move.axes[0].min ^ " a " ^ move.axes[0].max ^ ")"
    if var.en
        set var.rx = "Save origin " ^ var.code ^ ": X outside the travel (" ^ move.axes[0].min ^ " to " ^ move.axes[0].max ^ ")"
    abort {var.en ? (var.rx ^ ". Origin X" ^ var.x ^ ", with laser offset X" ^ (var.x + var.dx) ^ ". Nothing was saved.") : (var.rx ^ ". Origen X" ^ var.x ^ ", con offset laser X" ^ (var.x + var.dx) ^ ". No se guardo nada.")}
if var.y < move.axes[1].min || var.y > move.axes[1].max || var.y + var.dy < move.axes[1].min || var.y + var.dy > move.axes[1].max
    var ry = "Guardar origen " ^ var.code ^ ": Y fuera del recorrido (" ^ move.axes[1].min ^ " a " ^ move.axes[1].max ^ ")"
    if var.en
        set var.ry = "Save origin " ^ var.code ^ ": Y outside the travel (" ^ move.axes[1].min ^ " to " ^ move.axes[1].max ^ ")"
    abort {var.en ? (var.ry ^ ". Origin Y" ^ var.y ^ ", with laser offset Y" ^ (var.y + var.dy) ^ ". Nothing was saved.") : (var.ry ^ ". Origen Y" ^ var.y ^ ", con offset laser Y" ^ (var.y + var.dy) ^ ". No se guardo nada.")}

; --- 2) inside the cut area of the active mode (if it is measured)
var area = null
if true
    if var.modo == "Laser" && exists(global.cutAreaLaser)
        set var.area = global.cutAreaLaser
    elif var.modo == "CNC" && exists(global.cutAreaCNC)
        set var.area = global.cutAreaCNC
    elif var.modo == "FFF" && exists(global.cutAreaFFF)
        set var.area = global.cutAreaFFF
if var.area != null
    if var.x < var.area[0] || var.x > var.area[1] || var.y < var.area[2] || var.y > var.area[3]
        var amsg = var.en ? ("Save origin " ^ var.code ^ ": point X" ^ var.x ^ " Y" ^ var.y ^ " is OUTSIDE the cut area") : ("Guardar origen " ^ var.code ^ ": el punto X" ^ var.x ^ " Y" ^ var.y ^ " queda FUERA del area de corte")
        var tmsg1 = var.amsg ^ " (X " ^ var.area[0] ^ " a " ^ var.area[1] ^ ", Y " ^ var.area[2] ^ " a " ^ var.area[3] ^ "). No se guardo nada."
        if var.en
            set var.tmsg1 = var.amsg ^ " (X " ^ var.area[0] ^ " to " ^ var.area[1] ^ ", Y " ^ var.area[2] ^ " to " ^ var.area[3] ^ "). Nothing was saved."
        abort {var.tmsg1}

; --- save (with the previous value in the comment, to be able to recover it)
var prevX = move.axes[0].workplaceOffsets[param.W - 1]
var prevY = move.axes[1].workplaceOffsets[param.W - 1]
; (built in parts: DSF refuses arguments longer than 255 characters)
; The header is always English (2026-10-13: files on the machine in English);
; the zone readers only take the name before " --".
var who = var.laserOver ? "laser" : "pointer"
var info = "generated by saveworkplace.g on " ^ state.time ^ " (" ^ var.who ^ " over the point"
set var.info = var.info ^ ", machine X" ^ move.axes[0].machinePosition ^ " Y" ^ move.axes[1].machinePosition
set var.info = var.info ^ "; applied before X" ^ var.prevX ^ " Y" ^ var.prevY ^ ")"
if exists(param.S)
    echo >{var.f} "; " ^ var.code ^ " " ^ param.S ^ " -- " ^ var.info
else
    echo >{var.f} "; " ^ var.code ^ " -- " ^ var.info
var g10 = "G10 L2 P" ^ param.W ^ " X{" ^ var.x ^ " + (global.laserOffsetOn ? global.workshopLaserCorrX : 0)}"
echo >>{var.f} var.g10 ^ " Y{" ^ var.y ^ " + (global.laserOffsetOn ? global.workshopLaserCorrY : 0)} Z0"

M98 P{var.f}                                    ; apply now, without waiting for a restart
var quien = var.laserOver ? "laser" : "puntero"
var msg = var.en ? ("Origin " ^ var.code ^ " saved: point X" ^ var.x ^ " Y" ^ var.y ^ " (" ^ var.who ^ " over the point)") : ("Origen " ^ var.code ^ " guardado: punto X" ^ var.x ^ " Y" ^ var.y ^ " (" ^ var.quien ^ " sobre el punto)")
if var.en
    set var.msg = var.msg ^ ", correction X" ^ var.dx ^ " Y" ^ var.dy ^ (global.laserOffsetOn ? " (applied)" : " (laser offset OFF)")
    M118 P0 S{var.msg ^ ". Before: X" ^ var.prevX ^ " Y" ^ var.prevY}
else
    set var.msg = var.msg ^ ", correccion X" ^ var.dx ^ " Y" ^ var.dy ^ (global.laserOffsetOn ? " (aplicada)" : " (offset laser OFF)")
    M118 P0 S{var.msg ^ ". Antes: X" ^ var.prevX ^ " Y" ^ var.prevY}
