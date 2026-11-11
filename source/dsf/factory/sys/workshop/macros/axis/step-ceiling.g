; sys/workshop/macros/axis/step-ceiling.g -- WorkshopMotors (Motors > Measure > Step
; ceiling). One run of the measurement of the REAL step rate ceiling of the board:
;   1. raises the microstepping of the axis to M (e.g. 256): the board has to generate
;      many more pulses per mm, so high rates are reached with the axis
;      moving at a normal speed (no risk of losing steps)
;   2. goes back and forth N times D mm at F mm/min
;   3. restores the microstepping and the limits
; The page compares the M122 hiccups (accumulated by the backend,
; motorReport.hiccups_total) before and after each run: the first run
; with hiccups is above the ceiling.
;
; THIS MOVES THE MACHINE. Needs the axis homed. After measuring it is worth
; homing (going back to the normal microstepping can shift a fraction).
; Use: M98 P"0:/sys/workshop/macros/axis/step-ceiling.g" A"X" F9000 D300 N3 M256

if !exists(global.workshopCeilingPending)
  global workshopCeilingPending = false
if !exists(global.workshopCeilingAxis)
  global workshopCeilingAxis = ""
if !exists(global.workshopCeilingMicro)
  global workshopCeilingMicro = 16
if !exists(global.workshopCeilingInterp)
  global workshopCeilingInterp = 1
if !exists(global.workshopCeilingV)
  global workshopCeilingV = 0
if !exists(global.workshopCeilingAcc)
  global workshopCeilingAcc = 0
if !exists(global.workshopCeilingMode)
  global workshopCeilingMode = ""

; a previous run that was cut left the test microstepping/limits: restore
if global.workshopCeilingPending
  if global.workshopCeilingMode == state.machineMode && global.workshopCeilingAxis != ""
    M98 P"0:/sys/workshop/macros/axis/axis-microstep.g" L{global.workshopCeilingAxis} M{global.workshopCeilingMicro} I{global.workshopCeilingInterp}
    M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L{global.workshopCeilingAxis} V{global.workshopCeilingV} C{global.workshopCeilingAcc}
  set global.workshopCeilingPending = false

if exists(param.R)
  M99                                           ; R1 = only restore

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
  abort {var.en ? ("Step ceiling: a job is running") : ("Techo de pulsos: hay un trabajo en curso")}
if state.status == "halted" || state.status == "off"
  abort {var.en ? ("Step ceiling: the machine is not ready") : ("Techo de pulsos: la maquina no esta lista")}
if !exists(param.A) || !exists(param.F) || !exists(param.M)
  abort {var.en ? ("Step ceiling: A, F or M missing") : ("Techo de pulsos: faltan A, F o M")}
var i = -1
while iterations < #move.axes
  if move.axes[iterations].letter == param.A
    set var.i = iterations
    break
if var.i < 0
  abort {var.en ? ("Step ceiling: there is no axis " ^ param.A) : ("Techo de pulsos: no existe el eje " ^ param.A)}
if !move.axes[var.i].homed
  abort {var.en ? ("Step ceiling: home " ^ param.A ^ " first") : ("Techo de pulsos: primero haz homing de " ^ param.A)}
if param.M < 1 || param.M > 256
  abort {var.en ? ("Step ceiling: M out of range (1 to 256)") : ("Techo de pulsos: M fuera de rango (1 a 256)")}

var reps = 3
if exists(param.N)
  set var.reps = max(1, min(param.N, 20))
var inicio = move.axes[var.i].min + 15
var dist = move.axes[var.i].max - 10 - var.inicio
if exists(param.D)
  set var.dist = min(param.D, var.dist)
if var.dist < 20
  abort {var.en ? ("Step ceiling: travel too short") : ("Techo de pulsos: recorrido demasiado corto")}
var vPrev = move.axes[var.i].speed
var aPrev = move.axes[var.i].acceleration
var vel = max(60, min(param.F, var.vPrev))     ; never faster than configured

; raise Z 5 mm (if there is room) so nothing is dragged (not when Z is measured)
var zUp = 0
if param.A != "Z"
  set var.zUp = max(0, min(5, move.axes[2].max - move.axes[2].machinePosition))
if var.zUp > 0
  G91
  G1 Z{var.zUp} F600 S0
  G90

M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio} F3000
M400

set global.workshopCeilingAxis = param.A
set global.workshopCeilingMicro = move.axes[var.i].microstepping.value
set global.workshopCeilingInterp = move.axes[var.i].microstepping.interpolated ? 1 : 0
set global.workshopCeilingV = var.vPrev
set global.workshopCeilingAcc = var.aPrev
set global.workshopCeilingMode = state.machineMode
set global.workshopCeilingPending = true
M98 P"0:/sys/workshop/macros/axis/axis-microstep.g" L{param.A} M{param.M} I1

while iterations < var.reps
  M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio + var.dist} F{var.vel}
  M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio} F{var.vel}
M400

M98 P"0:/sys/workshop/macros/axis/axis-microstep.g" L{param.A} M{global.workshopCeilingMicro} I{global.workshopCeilingInterp}
M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L{param.A} V{var.vPrev} C{var.aPrev}
set global.workshopCeilingPending = false

if var.zUp > 0
  G91
  G1 Z{-var.zUp} F600 S0
  G90
if var.en
  echo "Step ceiling: run " ^ param.A ^ " at " ^ var.vel ^ " mm/min with 1/" ^ param.M ^ " done"
else
  echo "Techo de pulsos: tramo " ^ param.A ^ " a " ^ var.vel ^ " mm/min con 1/" ^ param.M ^ " terminado"
