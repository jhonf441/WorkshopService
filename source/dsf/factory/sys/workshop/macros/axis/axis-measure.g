; sys/workshop/macros/axis/axis-measure.g -- WorkshopMotors (Motors page > Test)
; Measures at what position (according to the firmware) the PHYSICAL endstop
; of axis A triggers (any axis with a pin type M574, at the minimum or at the maximum),
; WITHOUT homing again: G1 H4 stops when the switch triggers but does not
; correct the position. If the motor lost steps, the number changes from
; the previous measurement. Result in global.workshopMeasurement (mm, machine).
; The axes that use the probe as endstop (Z with BLTouch) are measured
; with axis-probe.g.
; Use: M98 P"0:/sys/workshop/macros/axis/axis-measure.g" A"X"

if !exists(global.workshopMeasurement)
  global workshopMeasurement = 0
if !exists(param.A)
  abort "axis-measure: A missing (axis letter)"

var i = -1
while iterations < #move.axes
  if move.axes[iterations].letter == param.A
    set var.i = iterations
    break
if var.i < 0
  abort "axis-measure: there is no axis " ^ param.A
if var.i >= #sensors.endstops || sensors.endstops[var.i] == null
  abort "axis-measure: axis " ^ param.A ^ " has no endstop"
if sensors.endstops[var.i].type != "inputPin"
  abort "axis-measure: the endstop of " ^ param.A ^ " is not a switch (use axis-probe.g)"

var alto = sensors.endstops[var.i].highEnd
var arranque = move.axes[var.i].min + 8
if var.alto
  set var.arranque = move.axes[var.i].max - 8

; approach fast to 8 mm from the endstop
M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.arranque} F3000
M400
; go slowly towards the switch until it triggers (20 mm at most)
if var.alto
  M98 P"0:/sys/workshop/macros/axis/axis-touch.g" L{param.A} D20
else
  M98 P"0:/sys/workshop/macros/axis/axis-touch.g" L{param.A} D-20
if !sensors.endstops[var.i].triggered
  abort "axis-measure: " ^ param.A ^ " did not hit the endstop within 20 mm"
set global.workshopMeasurement = move.axes[var.i].machinePosition

; back to the starting point
M98 P"0:/sys/workshop/macros/axis/axis-move.g" L{param.A} P{var.arranque} F3000
M400
