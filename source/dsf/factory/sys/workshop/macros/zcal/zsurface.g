; zsurface.g -- THICKNESS of the material (WorkshopJog, request 2026-10-09: "warn
; if the material is the wrong one before cutting"). Called RIGHT AFTER
; a G30 that measured a surface (laserfocus.g, focushere.g,
; zprobepoint.g, homezhere.g).
;
; How: global.workshopZBed = height of the BED in the current Z frame. It is
; set by zbedref.g at the Z homing (G30 on the bed: bed = 0). Each G30
; moves the zero to the measured surface; sensors.probes[0].lastStopHeight is
; where the probe stopped in the PREVIOUS frame, so:
;   surface (previous frame) = lastStopHeight - triggerHeight
;   thickness = surface - bed
;   bed in the new frame = bed - surface
; If the reference is not valid (no Z homing, G92 Z by hand, etc.)
; nothing is computed (global.workshopThickness = -1).
;
; Use:  M98 P"0:/sys/workshop/macros/zcal/zsurface.g" T3 N"MDF 3mm"
;   T = expected thickness in mm (optional; 0 = do not compare)
;   N = name of the material for the warning (optional)
;   K = 1: compare also without bed compensation (mesh); by default it is only compared with the mesh on

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if !exists(global.workshopZBedOk)
    global workshopZBedOk = false
if !exists(global.workshopZBed)
    global workshopZBed = 0
if !exists(global.workshopThickness)
    global workshopThickness = -1

var s = sensors.probes[0].lastStopHeight - sensors.probes[0].triggerHeight

; Fine adjustment of the active ZONE (Zones > Active zone > Z height > Calibrate,
; request 2026-10-09 "calibrate the height of the zones by probe
; type"): global.workshopZAdj[zone] is loaded by sys/workshop/macros/zcal/zcal.g for the current
; mode. +a = the real surface is a mm HIGHER than what the probe
; measured: Z0 goes up by a (the tool ends up a mm further away).
if exists(global.workshopZAdj)
    if move.workplaceNumber < #global.workshopZAdj
        var za = global.workshopZAdj[move.workplaceNumber]
        if var.za != 0
            G92 Z{move.axes[2].userPosition - var.za}
            set var.s = var.s + var.za
            if var.en
                M118 P0 S{"Zone fine adjustment: " ^ var.za ^ " mm"}
            else
                M118 P0 S{"Ajuste fino de la zona: " ^ var.za ^ " mm"}
; NOTE (2026-10-15): this macro never uses M99 any more. In RepRapFirmware an M99 inside an "if" of a macro that was
; called with M98 also drops the variables of the macro that called it (laserfocus.g failed with "unknown variable 'en'"
; right after this macro). Everything below is nested instead.
if !global.workshopZBedOk
    set global.workshopThickness = -1
    if var.en
        M118 P0 S{"Thickness: no bed reference (home Z to be able to measure it)"}
    else
        M118 P0 S{"Grosor: sin referencia de cama (hace homing de Z para poder medirlo)"}
else
    set global.workshopThickness = floor((var.s - global.workshopZBed) * 100 + 0.5) / 100
    set global.workshopZBed = global.workshopZBed - var.s
    ; the thickness as text with 2 decimals (RRF prints decimals with 7
    ; digits: "-0.1600000"; request 2026-10-10 "why does it have so many decimals")
    var g100 = floor(abs(global.workshopThickness) * 100 + 0.5)
    var gabs = floor(var.g100 / 100) ^ "." ^ (mod(var.g100, 100) < 10 ? "0" : "") ^ mod(var.g100, 100)
    var gtxt = (global.workshopThickness < 0 ? "-" : "") ^ var.gabs
    var t = exists(param.T) ? param.T : 0
    ; 2026-10-16: without bed compensation this number is NOT the thickness, so it is not announced as one (the user did not
    ; understand "Thickness: not compared ... -2.25 mm"). The message below says what was really measured.
    var comparable = (exists(param.K) && param.K > 0) || move.compensation.type == "mesh"
    if var.t == 0 || var.comparable
        if var.en
            M118 P0 S{"Measured thickness: " ^ var.gtxt ^ " mm above the bed of the Z homing"}
        else
            M118 P0 S{"Grosor medido: " ^ var.gtxt ^ " mm sobre la cama del homing de Z"}
    if var.t > 0
        var nm = exists(param.N) ? param.N : (var.en ? "the material" : "el material")
        ; 2026-10-15: the thickness is the height difference between the point of the Z homing and this point. It is only the
        ; thickness of the material if the bed is level between the two points, i.e. with the bed compensation (mesh) on.
        ; Without it the comparison would warn "wrong material" for a material that is right (the boards of two areas of
        ; a bed that is not level). K1 forces the comparison.
        if !var.comparable
            ; what was measured: the surface is X mm below / above the point where Z was homed. It says nothing about the thickness
            ; (the bed is not level) and it does not matter for the focus: the laser is left at the height from THIS surface.
            ; (2026-10-16: three short messages; the single long one made RRF fail with "Failed to serialize code (too long?)"
            ; and the macro stopped at that line)
            if var.en
                var m1 = "Surface measured " ^ var.gabs ^ " mm " ^ (global.workshopThickness < 0 ? "below" : "above") ^ " the point where Z was homed."
                M118 P0 S{var.m1}
                var m2 = "It is not the thickness of " ^ var.nm ^ " (" ^ var.t ^ " mm): the bed has no compensation."
                M118 P0 S{var.m2}
                M118 P0 S{"The focus is correct: it is measured from this surface."}
            else
                var m1 = "Superficie medida " ^ var.gabs ^ " mm " ^ (global.workshopThickness < 0 ? "mas abajo" : "mas arriba") ^ " que el punto del homing de Z."
                M118 P0 S{var.m1}
                var m2 = "No es el grosor de " ^ var.nm ^ " (" ^ var.t ^ " mm): la cama no tiene compensacion."
                M118 P0 S{var.m2}
                M118 P0 S{"El foco queda bien: se mide desde esta superficie."}
        elif global.workshopThickness < 1.0
            ; (almost) zero: Z was homed on this same material (or the bed was not clear): what was measured is only the
            ; difference of height between the point of the Z homing and this point, not the thickness. It cannot be
            ; compared, only warned.
            if var.en
                M118 P0 S{"Thickness: couldn't compare with " ^ var.t ^ " mm (was Z homed on the material? then " ^ var.gtxt ^ " mm is only the height difference between the two points)"}
            else
                M118 P0 S{"Grosor: no se pudo comparar con " ^ var.t ^ " mm (el homing de Z fue sobre el material? entonces " ^ var.gtxt ^ " mm es solo la diferencia de altura entre los dos puntos)"}
        elif abs(global.workshopThickness - var.t) > max(0.6, var.t * 0.2)
            var tmsg1 = "Se midio " ^ var.gtxt ^ " mm de grosor, pero " ^ var.nm ^ " es de " ^ var.t ^ " mm. Material equivocado? OK = seguir igual, Cancelar = parar."
            if var.en
                set var.tmsg1 = "Measured " ^ var.gtxt ^ " mm thick, but " ^ var.nm ^ " is " ^ var.t ^ " mm. Wrong material? OK = continue anyway, Cancel = stop."
            M291 P{var.tmsg1} R{var.en ? ("Check the material") : ("Revisar el material")} S3
