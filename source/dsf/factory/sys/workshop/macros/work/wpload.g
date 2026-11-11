; wpload.g -- applies ONLY the saved origins again (sys/workshop/zones/p<N>.g),
; without reloading the cut area or checking the travel. Used by
; sys/workshop/macros/laser/laseroffset.g when the offset flag changes: measured 2026-10-08,
; workplaces.g took ~2.9 s (the 9-turn loop with checks) and this
; ~0.6 s. Each p<N>.g already computes its origin with global.laserOffsetOn.
; workplaces.g (startup, material macros) still does everything.
;
; The laser <-> pointer correction is ONE value of the machine (settings store "laser"); the service writes it to
; lasercorrection.g as global.workshopLaserCorrX / Y (+ Known: true when it was measured) and each p<N>.g adds those globals (no number of its own).
var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
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
; Without a measured correction the origins load with 0 (the pointer is the laser): said, not hidden (the Workbench blocks the cut as well).
if global.laserOffsetOn && (!fileexists("0:/sys/workshop/macros/laser/lasercorrection.g") || !global.workshopLaserCorrKnown)
    M118 P0 S{var.en ? "WARNING: the laser-pointer correction is not known (Machine > Offsets): the origins load WITHOUT correction" : "AVISO: la correccion laser-puntero no se conoce (Maquina > Offsets): los origenes se cargan SIN correccion"}

if fileexists("0:/sys/workshop/zones/p1.g")
    M98 P"0:/sys/workshop/zones/p1.g"
if fileexists("0:/sys/workshop/zones/p2.g")
    M98 P"0:/sys/workshop/zones/p2.g"
if fileexists("0:/sys/workshop/zones/p3.g")
    M98 P"0:/sys/workshop/zones/p3.g"
if fileexists("0:/sys/workshop/zones/p4.g")
    M98 P"0:/sys/workshop/zones/p4.g"
if fileexists("0:/sys/workshop/zones/p5.g")
    M98 P"0:/sys/workshop/zones/p5.g"
if fileexists("0:/sys/workshop/zones/p6.g")
    M98 P"0:/sys/workshop/zones/p6.g"
if fileexists("0:/sys/workshop/zones/p7.g")
    M98 P"0:/sys/workshop/zones/p7.g"
if fileexists("0:/sys/workshop/zones/p8.g")
    M98 P"0:/sys/workshop/zones/p8.g"
if fileexists("0:/sys/workshop/zones/p9.g")
    M98 P"0:/sys/workshop/zones/p9.g"
