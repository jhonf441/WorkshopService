; workplaces.g
; PERSISTENT work coordinate systems.
; RRF does not keep the G10s across a power off / restart (they are volatile). Each saved
; origin lives in 0:/sys/workshop/zones/p<N>.g (written by sys/workshop/macros/work/saveworkplace.g, or
; editable by hand) and this file applies them again. Called
; from config.g at every startup, from the material macros and from
; sys/workshop/macros/laser/laseroffset.g.
;
; Each p<N>.g keeps the position of the POINTER and adds the laser <-> pointer
; correction of the machine only if global.laserOffsetOn (flag, see sys/workshop/macros/laser/laseroffset.g):
;   G10 L2 P2 X{20.0375 + (global.laserOffsetOn ? global.workshopLaserCorrX : 0)} Y{...} Z0
; The correction is ONE value (settings store "laser", Machine > Offsets): the service writes it to
; sys/workshop/macros/laser/lasercorrection.g, run below before the zones, so a new correction rewrites no zone. That file also sets
; global.workshopLaserCorrKnown (true = measured); while it is false or the file is missing the zones load with 0 and this macro says so.
;
; P1 = G54 (free / general: CNC setzero.g, "Set Work" button of DWC)
; P2 = G55 MDF 3mm (macros/laser/mdf3mm.g)
; P3 = G56 MDF 6mm (macros/laser/mdf6mm.g)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if !exists(global.laserOffsetOn)
    global laserOffsetOn = true                 ; default at startup: offset applied
if !exists(global.workshopLaserCorrX)
    global workshopLaserCorrX = 0               ; no correction measured yet (or no service): the pointer is the laser
if !exists(global.workshopLaserCorrY)
    global workshopLaserCorrY = 0
if !exists(global.workshopLaserCorrKnown)
    global workshopLaserCorrKnown = false       ; true only while lasercorrection.g says a correction was MEASURED: 0 0 with false is "unknown", not "zero"
if fileexists("0:/sys/workshop/macros/laser/lasercorrection.g")
    M98 P"0:/sys/workshop/macros/laser/lasercorrection.g"
; Without a measured correction the zones load with 0 (the pointer is the laser): said, not hidden. It does not abort: this runs from config.g.
if global.laserOffsetOn && (!fileexists("0:/sys/workshop/macros/laser/lasercorrection.g") || !global.workshopLaserCorrKnown)
    M118 P0 S{var.en ? "WARNING: the laser-pointer correction is not known (Machine > Offsets): the zones load WITHOUT correction" : "AVISO: la correccion laser-puntero no se conoce (Maquina > Offsets): las zonas se cargan SIN correccion"}

; Usable cut area per mode (measured by the jog: Advanced -> Zones -> Cut
; area). Defines global.cutAreaLaser / cutAreaCNC / cutAreaFFF = {Xmin, Xmax,
; Ymin, Ymax} in BED coordinates (= position of the pointer), or null if not
; measured. sys/workshop/macros/work/saveworkplace.g uses it to never save an origin outside.
if fileexists("0:/sys/workshop/zones/cutarea.g")
    M98 P"0:/sys/workshop/zones/cutarea.g"

; Each zone with a file is loaded and checked in the same pass: warning (it does
; not abort -- this runs from config.g at startup) if its origin is OUTSIDE
; the travel of the active mode, e.g. saved in Laser mode (Y 0..523) and
; now in FFF (Y 0..480): "Go to zero" would end at an axis limit. Only
; the zones with a file: a separate loop over the 9 added ~1s to every
; "Laser offset" change (measured 2026-10-08).
while iterations < 9
    if fileexists("0:/sys/workshop/zones/p" ^ (iterations + 1) ^ ".g")
        M98 P{"0:/sys/workshop/zones/p" ^ (iterations + 1) ^ ".g"}
        var ox = move.axes[0].workplaceOffsets[iterations]
        var oy = move.axes[1].workplaceOffsets[iterations]
        if var.ox < move.axes[0].min || var.ox > move.axes[0].max || var.oy < move.axes[1].min || var.oy > move.axes[1].max
            var tmsg1 = "AVISO: el origen de la zona P" ^ (iterations + 1) ^ " (X" ^ var.ox ^ " Y" ^ var.oy ^ ") esta FUERA del recorrido de este modo"
            if var.en
                set var.tmsg1 = "WARNING: the origin of zone P" ^ (iterations + 1) ^ " (X" ^ var.ox ^ " Y" ^ var.oy ^ ") is OUTSIDE the travel of this mode"
            M118 P0 S{var.tmsg1}
