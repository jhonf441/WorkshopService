; focusref.g -- relates the lens box of the laser with the probe: how high is the laser reference above the surface
; when the box edge TOUCHES the material.
;
; Use (the person does the first step with the jog, then says "go"):
;   1. put the protective box of the lens touching the material (just touching, no pressure) and leave it there;
;   2. M98 P"0:/sys/workshop/macros/focus/focusref.g"      (optional: Z<machine Z where the box touches>)
;
; What it does (nothing here ever presses the box into the material):
;   - remembers Z where the box touches (zt), lifts 15 mm, deploys the probe (the pin of a BLTouch; other probes need nothing)
;     and comes down in small steps, reading the probe each step;
;   - it never goes below zt + 0.05: if the probe has not triggered by then, it stops and says so;
;   - when it triggers at Z = zr, the reference was at the trigger height T (G31 Z) above the surface, so with the box
;     touching it is at   h0 = T - (zr - zt)   above the surface;
;   - leaves the pin stowed, the head 5 mm above zt, and the result in 0:/sys/workshop/data/focusref.json.
; The focus height for a thickness t is then  H = h0 - lever(t)  (lever of the table of the laser maker).
; The laser stays OFF the whole time (M5, every G1 with S0).

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var lift = 15                                   ; mm above the touching position to start from
var coarse = 0.5                                ; coarse step down (mm)
var fine = 0.05                                 ; fine step (mm)

if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
    abort {var.en ? ("Focus reference: home all axes first") : ("Referencia de foco: primero hace homing de todos los ejes")}
if exists(job.file.fileName) && job.file.fileName != null
    abort {var.en ? ("Focus reference: there is a job running") : ("Referencia de foco: hay un trabajo en curso")}
if !exists(sensors.probes[0])
    abort {var.en ? ("Focus reference: there is no probe configured") : ("Referencia de foco: no hay sonda configurada")}

M5                                              ; laser off
var zt = exists(param.Z) ? param.Z : move.axes[2].machinePosition   ; the box touches the material here (Z = machine Z, if you already know it)
if var.zt + var.lift > move.axes[2].max
    abort {var.en ? ("Focus reference: not enough Z travel above this position") : ("Referencia de foco: no hay recorrido de Z sobre esta posicion")}
var trigH = -sensors.probes[0].offsets[2]       ; trigger height T of the probe (G31 Z)
var servo = #sensors.probes > 0 && sensors.probes[0] != null && sensors.probes[0].type == 9   ; only a BLTouch (probe type 9) has a servo pin: a switch, piezo or other probe gets no M280 / M401 / M402

if var.servo
    M280 P0 S160                                ; clear a possible alarm of the BLTouch (raises the pin)
    G4 P300
    M402
    G4 P300
M400
G90
G53 G1 Z{var.zt + var.lift} F600 S0
M400
if var.servo
    M401                                        ; deploy the pin
    G4 P500

; coarse pass: down in steps of var.coarse until the probe triggers or the touching position is reached
var z = var.zt + var.lift
var hit = false
while var.z > var.zt + 0.05 && !var.hit
    set var.z = max(var.zt + 0.05, var.z - var.coarse)
    G53 G1 Z{var.z} F300 S0
    M400
    if sensors.probes[0].value[0] >= sensors.probes[0].threshold
        set var.hit = true

if var.hit
    ; fine pass: back up one coarse step and come down in small steps
    set var.z = var.z + var.coarse
    G53 G1 Z{var.z} F300 S0
    M400
    set var.hit = false
    while var.z > var.zt + 0.05 && !var.hit
        set var.z = max(var.zt + 0.05, var.z - var.fine)
        G53 G1 Z{var.z} F60 S0
        M400
        G4 P150
        if sensors.probes[0].value[0] >= sensors.probes[0].threshold
            set var.hit = true

if var.servo
    M402                                        ; stow the pin
    G4 P300
M400
G53 G1 Z{var.zt + 5} F600 S0
M400

var d = var.z - var.zt                          ; how far ABOVE the touching position the probe triggers
var h0 = var.trigH - var.d                      ; height of the reference above the surface with the box touching

; the result file first (short lines: RRF refuses an argument of more than 255 characters)
echo >"0:/sys/workshop/data/focusref.json" "{"
echo >>"0:/sys/workshop/data/focusref.json" {"""reachable"": " ^ (var.hit ? "true" : "false") ^ ","}
echo >>"0:/sys/workshop/data/focusref.json" {"""zTouch"": " ^ var.zt ^ ", ""zTrigger"": " ^ var.z ^ ","}
echo >>"0:/sys/workshop/data/focusref.json" {"""d"": " ^ var.d ^ ", ""triggerHeight"": " ^ var.trigH ^ ","}
echo >>"0:/sys/workshop/data/focusref.json" {"""h0"": " ^ var.h0}
echo >>"0:/sys/workshop/data/focusref.json" "}"

if var.hit
    if var.en
        M118 P0 S{"Focus reference: box touching at Z" ^ var.zt}
        M118 P0 S{"The probe triggers " ^ var.d ^ " mm above that (T=" ^ var.trigH ^ ")"}
        M118 P0 S{"With the box touching the reference is " ^ var.h0 ^ " mm above the surface"}
    else
        M118 P0 S{"Referencia de foco: caja tocando en Z" ^ var.zt}
        M118 P0 S{"La sonda dispara " ^ var.d ^ " mm por encima (T=" ^ var.trigH ^ ")"}
        M118 P0 S{"Con la caja tocando la referencia esta a " ^ var.h0 ^ " mm sobre la superficie"}
else
    if var.en
        M118 P0 S"Focus reference: the probe did not trigger before the box touched. Nothing was pressed."
    else
        M118 P0 S"Referencia de foco: la sonda no disparo antes de que la caja tocara. No se presiono nada."
