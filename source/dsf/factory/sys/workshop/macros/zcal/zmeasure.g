; zmeasure.g -- measures the surface under the probe where the head is now: Z0 = that surface (like G30).
; It is the ONE place that decides HOW to measure, by the type of probe the machine declares (M558 P, object model
; sensors.probes[0].type). laserfocus.g, focushere.g and zprobepoint.g call it instead of a bare G30.
;
;   type 9   BLTouch                 clears a possible alarm and stows the pin, then G30 (G30 deploys and stows it again)
;   type 1 2 3 5 8 10 11             analog, switch, piezo / unfiltered, Z motor stall, scanning probe: G30
;   none, or type 0 (manual)         nothing to touch with: it stops and says so (use the paper: Z0 with paper)
;
; Not here: the touch plate (G38.2 against a plate on the material). It is pending, see the README of WorkshopWorkbench.
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zmeasure.g"      (home all axes first; the caller already raised Z and put the probe over the point)
; After it, zsurface.g can compare the thickness: sensors.probes[0].lastStopHeight is where the probe stopped.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)

if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Measure Z: home all axes first") : ("Medir Z: primero hace homing de todos los ejes")}
if #sensors.probes < 1 || sensors.probes[0] == null || sensors.probes[0].type == 0
    ; RRF rejects an argument over 255 characters ("Keyword argument too long"): the message is built from two short expressions
    var m1 = var.en ? "Measure Z: the machine has no probe to touch the surface with." : "Medir Z: la maquina no tiene sonda para tocar la superficie."
    var m2 = var.en ? "Lower the tool to a sheet of paper and use Z0 with paper" : "Baja la herramienta hasta un papel y usa Z0 con papel"
    abort {var.m1 ^ " " ^ var.m2}

if sensors.probes[0].type == 9
    M280 P0 S160                                ; BLTouch: clear a possible alarm (raises the pin)
    G4 P300
    M402                                        ; stow the pin: G30 deploys it fresh
    G4 P300
M400
G30                                             ; measure: Z0 = surface under the probe
