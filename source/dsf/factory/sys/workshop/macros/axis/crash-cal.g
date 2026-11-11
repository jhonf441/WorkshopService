; sys/workshop/macros/axis/crash-cal.g -- WorkshopMotors (Motors page > Crash)
; Calibrates the sensitivity of the stall detection (StallGuard, M915) used by
; the "without limits" mode of the jog (request 2026-10-10: "I put my hand to stop it
; and the motor did not stop").
;
; Goes back and forth through FREE SPACE in X or in Y with the current and the speed of
; the without-limits mode, trying finer and finer sensitivities (lower S = more
; sensitive). The first one that gives a FALSE stall (nothing in the way) is
; too sensitive: the result is the last one without a stall + a margin.
; driver-stall.g (created by WorkshopService) with global.crashCal only counts in
; global.crashCalHit: it stops nothing.
;
; THIS MOVES THE MACHINE. Needs the axis homed. Laser off (S0).
; Use: M98 P"0:/sys/workshop/macros/axis/crash-cal.g" A"X" V25 W15 C50 H100 S16 B-12 L120
;   A axis (X or Y), V test speed mm/s (the maximum of the without-limits mode),
;   W second speed mm/s (slower, 0 = no), C current %, H minimum full
;   steps/s of M915, S initial sensitivity (the least sensitive),
;   B the most sensitive one to try, L travel mm
; Leaves the result in global.crashCalRes (recommended sensitivity or -999 if
; the initial one already gives false stalls) and global.crashCalFake (the first false one).
; global.crashCalState (shown by the Motors page) follows the DWC language.

if !exists(global.crashCal)
  global crashCal = false
if !exists(global.crashCalHit)
  global crashCalHit = 0
if !exists(global.choqueCalSens)
  global choqueCalSens = 0
if !exists(global.crashCalRes)
  global crashCalRes = null
if !exists(global.crashCalFake)
  global crashCalFake = null
if !exists(global.crashCalPending)
  global crashCalPending = ""
if !exists(global.crashCalState)
  global crashCalState = ""

; a previous calibration that was cut left the test current and M915
if global.crashCalPending != ""
  M913 X100 Y100
  M915 X Y R0
  set global.crashCal = false
  set global.crashCalPending = ""

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if !exists(param.A) || (param.A != "X" && param.A != "Y")
  abort {var.en ? ("Crash calibration: A has to be X or Y") : ("Calibrar choque: A tiene que ser X o Y")}
if state.status == "processing" || state.status == "paused" || state.status == "simulating"
  abort {var.en ? ("Crash calibration: a job is running") : ("Calibrar choque: hay un trabajo en curso")}
if exists(global.jogFree) && global.jogFree
  abort {var.en ? ("Crash calibration: leave the without-limits mode of the jog first") : ("Calibrar choque: primero sal del modo sin limites del jog")}
var i = 0
if param.A == "Y"
  set var.i = 1
if !move.axes[var.i].homed
  abort {var.en ? ("Crash calibration: home " ^ param.A ^ " first") : ("Calibrar choque: primero haz homing de " ^ param.A)}

var v = 25
if exists(param.V)
  set var.v = max(2, min(param.V, 200))
var w = 0
if exists(param.W)
  set var.w = max(0, min(param.W, var.v))
var corr = 50
if exists(param.C)
  set var.corr = max(20, min(param.C, 100))
var h = 100
if exists(param.H)
  set var.h = max(20, min(param.H, 400))
var s = 16
if exists(param.S)
  set var.s = max(-60, min(param.S, 63))
var sEnd = -12
if exists(param.B)
  set var.sEnd = max(-64, min(param.B, var.s))
var largo = 120
if exists(param.L)
  set var.largo = max(30, min(param.L, 400))

; test stretch: around where it is, inside the travel (10 mm margin)
var p0 = move.axes[var.i].machinePosition
var lo = move.axes[var.i].min + 10
var hi = move.axes[var.i].max - 10
if var.hi - var.lo < var.largo
  set var.largo = var.hi - var.lo
if var.largo < 30
  abort {var.en ? ("Crash calibration: axis " ^ param.A ^ " is too short for the test") : ("Calibrar choque: el eje " ^ param.A ^ " es muy corto para la prueba")}
var a = max(var.lo, min(var.p0 - var.largo / 2, var.hi - var.largo))
var b = var.a + var.largo

set global.crashCalRes = null
set global.crashCalFake = null
set global.crashCalState = var.en ? "going to the start" : "yendo al inicio"
M400
G90
if param.A == "X"
  G53 G1 X{var.a} F3000 S0
else
  G53 G1 Y{var.a} F3000 S0
M400

set global.crashCalPending = param.A
if param.A == "X"
  M913 X{var.corr}
else
  M913 Y{var.corr}
set global.crashCal = true

var ok = null
while var.s >= var.sEnd
  set global.choqueCalSens = var.s
  set global.crashCalHit = 0
  set global.crashCalState = (var.en ? "trying " : "probando ") ^ var.s
  if param.A == "X"
    M915 X S{var.s} F1 H{var.h} R2
  else
    M915 Y S{var.s} F1 H{var.h} R2
  G4 P200
  ; two back-and-forth runs at the jog speed (+ a slow one if asked)
  while iterations < 2
    if param.A == "X"
      G53 G1 X{var.b} F{var.v * 60} S0
      G53 G1 X{var.a} F{var.v * 60} S0
    else
      G53 G1 Y{var.b} F{var.v * 60} S0
      G53 G1 Y{var.a} F{var.v * 60} S0
  if var.w > 0
    if param.A == "X"
      G53 G1 X{var.b} F{var.w * 60} S0
      G53 G1 X{var.a} F{var.w * 60} S0
    else
      G53 G1 Y{var.b} F{var.w * 60} S0
      G53 G1 Y{var.a} F{var.w * 60} S0
  M400
  G4 P300
  if global.crashCalHit > 0
    set global.crashCalFake = var.s
    break
  set var.ok = var.s
  set var.s = var.s - 2

; leave everything as it was
set global.crashCal = false
if param.A == "X"
  M915 X R0
  M913 X100
else
  M915 Y R0
  M913 Y100
set global.crashCalPending = ""
set global.crashCalState = var.en ? "coming back" : "volviendo"
if param.A == "X"
  G53 G1 X{var.p0} F3000 S0
else
  G53 G1 Y{var.p0} F3000 S0
M400

; result: the last one without a stall + 2 of margin (less sensitive)
if var.ok == null
  set global.crashCalRes = -999
  set global.crashCalState = var.en ? "done: the initial sensitivity already gives false stalls" : "listo: ya la sensibilidad inicial da choques falsos"
else
  set global.crashCalRes = var.ok + 2
  set global.crashCalState = var.en ? "done" : "listo"
