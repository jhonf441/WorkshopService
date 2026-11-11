; bedzones-set.g -- BACKUP of the "Bed zones" section of Printing: sets the temperature of the bed zones from the board alone, with
; WorkshopService stopped. The service is what splits a slicer's "M140 S60" (no bed number) across the zones; without it that code only reaches bed 0.
;
;     M98 P"0:/sys/workshop/macros/work/bedzones-set.g" S60        every active zone to 60 C (plus its offset)
;     M98 P"0:/sys/workshop/macros/work/bedzones-set.g" S0         every zone of the settings off, active or not (a stop reaches all of them)
;     M98 P"0:/sys/workshop/macros/work/bedzones-set.g" S60 B2     ONLY bed 2, exactly 60 C (no offset), the way the page's per-zone setpoint does
;
; Param S: temperature in C (0 or less turns the zones off). Param B (optional): one bed number instead of all the active zones.
; The bed is B and NOT P: in M98 the P is the name of this file, so a macro never receives a P (a P written after the file name is lost and ALL the zones are set).
; The service is the brain of the feature: the settings (which beds are zones, their offsets, the maximum) live in the service and it copies them to
; 0:/sys/workshop/config/bedzones.g every time they change and at start. This macro only READS that copy, so it does what the service would do. Without
; the copy (it never ran) it takes every bed heater the board reports, no offsets and the maxTemp below.
; The firmware keeps its own protection and this macro never goes around it: the PID, the M143 limit and the fault detection of every heater are RRF's, and
; a temperature at or over the M143 limit of a heater is refused here BEFORE anything is sent. It does not wait for the temperature (use M116).

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var maxTemp = 110    ; C: only when the service never wrote bedzones.g; otherwise the maximum of the Bed zones settings is used
var copy = fileexists("0:/sys/workshop/config/bedzones.g")
if var.copy
    M98 P"0:/sys/workshop/config/bedzones.g"
    set var.maxTemp = global.bedZonesMax

if !exists(param.S)
    abort {var.en ? ("Bed zones: temperature missing (S60 heats, S0 turns off)") : ("Zonas de cama: falta la temperatura (S60 calienta, S0 apaga)")}

if exists(param.B) && param.B < 0
    abort {var.en ? ("Bed zones: the bed number (B) cannot be negative") : ("Zonas de cama: el numero de cama (B) no puede ser negativo")}

var only = exists(param.B) ? param.B : -1   ; the one bed to set, or -1 for all the active zones
var off = param.S <= 0
if !var.off && param.S > var.maxTemp
    abort {var.en ? ("Bed zones: " ^ param.S ^ " C is over the maximum of " ^ var.maxTemp ^ " C. Nothing was sent") : ("Zonas de cama: " ^ param.S ^ " C pasa del maximo de " ^ var.maxTemp ^ " C. No se envio nada")}

; first look: every zone that will be set exists, is under the maximum and under the M143 limit of its heater, so a refusal never leaves the bed half set
var found = 0
while iterations < #heat.bedHeaters
    if heat.bedHeaters[iterations] >= 0
        var zone = true
        var offset = 0
        if var.copy
            M98 P"0:/sys/workshop/config/bedzones.g" B{iterations}
            set var.zone = (var.only >= 0 || var.off) ? global.bedZonesKnown : global.bedZonesActive   ; turning off reaches every listed zone, like the service's stop
            set var.offset = var.only >= 0 ? 0 : global.bedZonesOffset
        if var.zone && (var.only < 0 || var.only == iterations)
            set var.found = var.found + 1
            if !var.off
                var target = max(param.S + var.offset, 0)
                var limit = heat.heaters[heat.bedHeaters[iterations]].max   ; the M143 limit of this zone's heater
                ; one abort per language: RRF refuses a line with an argument of 250 characters or more
                if var.target > var.maxTemp
                    if var.en
                        abort {"Bed zones: bed " ^ iterations ^ " would get " ^ var.target ^ " C, over the maximum of " ^ var.maxTemp ^ " C. Nothing was sent"}
                    abort {"Zonas de cama: la cama " ^ iterations ^ " recibiria " ^ var.target ^ " C, mas del maximo de " ^ var.maxTemp ^ " C. No se envio nada"}
                if var.target >= var.limit
                    if var.en
                        abort {"Bed zones: bed " ^ iterations ^ " has a limit of " ^ var.limit ^ " C (M143). Nothing was sent"}
                    abort {"Zonas de cama: la cama " ^ iterations ^ " tiene un tope de " ^ var.limit ^ " C (M143). No se envio nada"}

if var.found == 0
    abort {var.en ? ("Bed zones: no active bed zone matches that request") : ("Zonas de cama: ninguna zona de cama activa coincide con ese pedido")}

; second look: send it
while iterations < #heat.bedHeaters
    if heat.bedHeaters[iterations] >= 0
        var zone = true
        var offset = 0
        if var.copy
            M98 P"0:/sys/workshop/config/bedzones.g" B{iterations}
            set var.zone = (var.only >= 0 || var.off) ? global.bedZonesKnown : global.bedZonesActive   ; turning off reaches every listed zone, like the service's stop
            set var.offset = var.only >= 0 ? 0 : global.bedZonesOffset
        if var.zone && (var.only < 0 || var.only == iterations)
            if var.off
                M140 P{iterations} S-273.15
            else
                M140 P{iterations} S{max(param.S + var.offset, 0)}

if var.en
    M118 P0 S{"Bed zones: " ^ var.found ^ " set (" ^ (var.off ? "off" : param.S ^ " C") ^ ")"}
else
    M118 P0 S{"Zonas de cama: " ^ var.found ^ " ajustadas (" ^ (var.off ? "apagadas" : param.S ^ " C") ^ ")"}
