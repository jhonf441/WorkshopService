; sys/workshop/macros/axis/axis-test.g -- WorkshopMotors (Motors page > Test)
; Lost steps test of ONE axis at a given speed/acceleration:
;   1. measures the reference of the axis:
;        - axes with a physical endstop (X, Y, new axes): where the
;          switch triggers (axis-measure.g, G1 H4)
;        - Z (uses the BLTouch as endstop): the height of the bed
;          with G30 S-1 where the head is (axis-probe.g)
;   2. sets the test M203/M201 and goes back and forth N times D mm
;   3. restores M203/M201 and measures again
; If the difference is above the threshold (0.1 mm with a switch, 0.03 mm with the
; probe) the motor lost steps: that speed/acceleration is NOT safe.
; Each test adds a line to 0:/sys/workshop/data/axis-test.csv (files created
; before 2026-10-13 keep their Spanish header; the page reads the columns by position).
;
; THIS MOVES THE MACHINE. Needs the axis homed (and X/Y/Z for Z).
; Use: M98 P"0:/sys/workshop/macros/axis/axis-test.g" A"X" F12000 C1000 D300 N5
;   A axis letter, F speed mm/min, C acceleration mm/s2,
;   D travel mm (cut to the length of the axis), N back-and-forth runs

if !exists(global.workshopTestPending)
  global workshopTestPending = false
if !exists(global.workshopTestAxis)
  global workshopTestAxis = ""
if !exists(global.workshopTestV)
  global workshopTestV = 0
if !exists(global.workshopTestAcc)
  global workshopTestAcc = 0
if !exists(global.workshopTestMode)
  global workshopTestMode = ""
if !exists(global.workshopTestLast)
  global workshopTestLast = ""
var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)

; A previous test that was cut (Stop, error) left the test limits
; set: restore them, unless the mode changed (the mode file
; already set its own).
if global.workshopTestPending
  if global.workshopTestMode == state.machineMode && global.workshopTestAxis != ""
    M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L{global.workshopTestAxis} V{global.workshopTestV} C{global.workshopTestAcc}
  set global.workshopTestPending = false

if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
  abort {var.en ? ("Axis test: a job is running") : ("Prueba de ejes: hay un trabajo en curso")}
if state.status == "halted" || state.status == "off"
  abort {var.en ? ("Axis test: the machine is not ready") : ("Prueba de ejes: la maquina no esta lista")}
if !exists(param.A)
  abort {var.en ? ("Axis test: A missing (axis letter)") : ("Prueba de ejes: falta A (letra del eje)")}
var i = -1
while iterations < #move.axes
  if move.axes[iterations].letter == param.A
    set var.i = iterations
    break
if var.i < 0
  abort {var.en ? ("Axis test: there is no axis " ^ param.A) : ("Prueba de ejes: no existe el eje " ^ param.A)}
if !exists(param.F) || !exists(param.C)
  abort {var.en ? ("Axis test: F (mm/min) or C (mm/s2) missing") : ("Prueba de ejes: faltan F (mm/min) o C (mm/s2)")}
if !move.axes[var.i].homed
  abort {var.en ? ("Axis test: home " ^ param.A ^ " first") : ("Prueba de ejes: primero haz homing de " ^ param.A)}

; how the reference of this axis is measured
var metodo = "ninguno"
if var.i < #sensors.endstops && sensors.endstops[var.i] != null
  if sensors.endstops[var.i].type == "inputPin"
    set var.metodo = "switch"
  elif param.A == "Z" && sensors.endstops[var.i].type == "zProbeAsEndstop"
    set var.metodo = "sonda"
if var.metodo == "ninguno"
  abort {var.en ? ("Axis test: " ^ param.A ^ " has no endstop or probe to measure with") : ("Prueba de ejes: " ^ param.A ^ " no tiene final de carrera ni sonda para medir")}
if var.metodo == "sonda"
  if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Axis test: for Z home X, Y and Z first") : ("Prueba de ejes: para Z primero haz homing de X, Y y Z")}

var vel = max(30, min(param.F, 36000))
var acc = max(5, min(param.C, 20000))
var reps = 5
if exists(param.N)
  set var.reps = max(1, min(param.N, 50))
var inicio = move.axes[var.i].min + 15
var dist = move.axes[var.i].max - 10 - var.inicio
if var.metodo == "sonda"
  ; Z: above the bed with room for the probe, never below 10 mm
  set var.inicio = max(10, move.axes[var.i].min + 10)
  set var.dist = move.axes[var.i].max - 5 - var.inicio
if exists(param.D)
  set var.dist = min(param.D, var.dist)
if var.dist < 5
  abort {var.en ? ("Axis test: travel too short") : ("Prueba de ejes: recorrido demasiado corto")}

; raise Z up to 5 mm (if there is room) so nothing is dragged (not in the Z test)
var zUp = 0
if param.A != "Z"
  set var.zUp = max(0, min(5, move.axes[2].max - move.axes[2].machinePosition))
if var.zUp > 0
  G91
  G1 Z{var.zUp} F600 S0
  G90

if var.metodo == "switch"
  M98 P"0:/sys/workshop/macros/axis/axis-measure.g" A{param.A}
else
  M98 P"0:/sys/workshop/macros/axis/axis-probe.g"
var antes = global.workshopMeasurement

; test limits (the current ones are saved in case it is cut)
var vPrev = move.axes[var.i].speed
var aPrev = move.axes[var.i].acceleration
set global.workshopTestAxis = param.A
set global.workshopTestV = var.vPrev
set global.workshopTestAcc = var.aPrev
set global.workshopTestMode = state.machineMode
set global.workshopTestPending = true
M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L{param.A} V{max(var.vel, var.vPrev)} C{var.acc}
M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio} F{min(3000, max(var.vPrev, 300))}

while iterations < var.reps
  M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio + var.dist} F{var.vel}
  M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.inicio} F{var.vel}
M400

; restore the limits
M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L{param.A} V{var.vPrev} C{var.aPrev}
set global.workshopTestPending = false

if var.metodo == "switch"
  M98 P"0:/sys/workshop/macros/axis/axis-measure.g" A{param.A}
else
  M98 P"0:/sys/workshop/macros/axis/axis-probe.g"
var despues = global.workshopMeasurement
var dif = var.despues - var.antes

if var.zUp > 0
  G91
  G1 Z{-var.zUp} F600 S0
  G90

if !fileexists("0:/sys/workshop/data/axis-test.csv")
  echo >"0:/sys/workshop/data/axis-test.csv" "date,mode,axis,speed_mm_min,accel_mm_s2,travel_mm,repetitions,before_mm,after_mm,difference_mm"
var csv = state.time ^ "," ^ state.machineMode ^ "," ^ param.A
set var.csv = var.csv ^ "," ^ var.vel ^ "," ^ var.acc ^ "," ^ var.dist
set var.csv = var.csv ^ "," ^ var.reps ^ "," ^ var.antes
set var.csv = var.csv ^ "," ^ var.despues ^ "," ^ var.dif
echo >>"0:/sys/workshop/data/axis-test.csv" var.csv
set global.workshopTestLast = param.A ^ "," ^ var.vel ^ "," ^ var.acc ^ "," ^ var.dif
if var.en
  echo "Test " ^ param.A ^ " (" ^ var.metodo ^ ") at " ^ var.vel ^ " mm/min and " ^ var.acc ^ " mm/s2: difference " ^ var.dif ^ " mm"
else
  echo "Prueba " ^ param.A ^ " (" ^ var.metodo ^ ") a " ^ var.vel ^ " mm/min y " ^ var.acc ^ " mm/s2: diferencia " ^ var.dif ^ " mm"
