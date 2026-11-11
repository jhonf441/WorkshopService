; sys/workshop/macros/axis/axis-microstep.g -- WorkshopMotors: sets the microstepping (M350) of ONE
; axis by its letter. RRF adjusts the steps/mm by itself, so the position in mm
; does not change (it can shift a fraction of a step: home afterwards).
; Use: M98 P"0:/sys/workshop/macros/axis/axis-microstep.g" L"X" M256 I1

if !exists(param.L) || !exists(param.M)
  abort "axis-microstep: L or M missing"
var it = 1
if exists(param.I)
  set var.it = param.I
M400
if param.L == "X"
  M350 X{param.M} I{var.it}
elif param.L == "Y"
  M350 Y{param.M} I{var.it}
elif param.L == "Z"
  M350 Z{param.M} I{var.it}
elif param.L == "U"
  M350 U{param.M} I{var.it}
elif param.L == "V"
  M350 V{param.M} I{var.it}
elif param.L == "W"
  M350 W{param.M} I{var.it}
elif param.L == "A"
  M350 A{param.M} I{var.it}
elif param.L == "B"
  M350 B{param.M} I{var.it}
elif param.L == "C"
  M350 C{param.M} I{var.it}
else
  abort "axis-microstep: unknown axis"
