; zcal-mark.g -- Calibrate the height (WorkshopJog): the tool is brushing
; a sheet of paper P mm thick on the surface. Sets Z = P here (G92), shifts the
; bed reference like zhere0.g (so the thickness can still be
; measured) and goes up to H mm above the surface.
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zcal-mark.g" P0.1 H5
;   P = thickness of the paper / feeler gauge (0 to 3 mm, default 0.1)
;   H = final height above the surface (optional, default 5)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var p = exists(param.P) ? param.P : 0.1
var h = exists(param.H) ? param.H : 5
if var.p < 0 || var.p > 3
    if var.en
        abort {"Calibrate: paper P" ^ var.p ^ " out of range (0 to 3 mm)"}
    abort {"Calibrar: papel P" ^ var.p ^ " fuera de rango (0 a 3 mm)"}
if var.h < 1 || var.h > 60
    abort {var.en ? ("Calibrate: H" ^ var.h ^ " out of range (1 to 60 mm)") : ("Calibrar: H" ^ var.h ^ " fuera de rango (1 a 60 mm)")}
if !move.axes[2].homed
    abort {var.en ? ("Calibrate: home Z first") : ("Calibrar: primero hace homing de Z")}

M400
if exists(global.workshopZBed)
    set global.workshopZBed = global.workshopZBed - (move.axes[2].machinePosition - var.p)
G92 Z{var.p}                                    ; the surface becomes Z0
G91
G1 Z{var.h - var.p} F600 S0                     ; go up to H above the surface (S0: laser off with M452 S1; in CNC/FFF it changes nothing)
G90
M400
if var.en
    M118 P0 S{"Calibrate: surface set (Z0) with a " ^ var.p ^ " mm paper; now at " ^ var.h ^ " mm"}
else
    M118 P0 S{"Calibrar: superficie fijada (Z0) con papel de " ^ var.p ^ " mm; quedo a " ^ var.h ^ " mm"}
