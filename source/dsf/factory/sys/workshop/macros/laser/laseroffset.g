; laseroffset.g -- "laser offset" flag of the work zones
; global.laserOffsetOn decides whether the zones saved in sys/workshop/zones/p<N>.g
; add the laser <-> pointer correction of the machine (global.workshopLaserCorrX / Y, e.g. X-16.5):
;   ON  (true)  -> X0 Y0 of the zone = where the LASER hits  (to cut)
;   OFF (false) -> X0 Y0 of the zone = where the POINTER is (to locate/check)
; It only changes what is in memory; the files are not touched. Goes back to ON
; on restart and every time a material macro runs (laserfocus.g).
; Zones without a file (e.g. G54 of DWC/CNC) are not affected.
;
; Use:  M98 P"0:/sys/workshop/macros/laser/laseroffset.g" S1   apply
;       M98 P"0:/sys/workshop/macros/laser/laseroffset.g" S0   remove
;       M98 P"0:/sys/workshop/macros/laser/laseroffset.g"      toggle

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if !exists(global.laserOffsetOn)
    global laserOffsetOn = true

if exists(param.S)
    set global.laserOffsetOn = (param.S != 0)
else
    set global.laserOffsetOn = !global.laserOffsetOn

M400                                            ; do not change origins with a move running
M98 P"0:/sys/workshop/macros/work/wpload.g"                          ; reapply the saved origins with the new flag (fast: ~0.6 s; workplaces.g took ~2.9 s)
if var.en
    M118 P0 S{global.laserOffsetOn ? "Laser offset APPLIED: X0 Y0 = laser" : "Laser offset REMOVED: X0 Y0 = pointer"}
else
    M118 P0 S{global.laserOffsetOn ? "Offset laser APLICADO: X0 Y0 = laser" : "Offset laser QUITADO: X0 Y0 = puntero"}
