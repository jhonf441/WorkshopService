; sys/workshop/macros/axis/axis-limits.g -- WorkshopMotors: sets M203 (maximum speed,
; mm/min) and M201 (acceleration, mm/s2) of ONE axis by its letter.
; Use: M98 P"0:/sys/workshop/macros/axis/axis-limits.g" L"Z" V600 C100

if !exists(param.L) || !exists(param.V) || !exists(param.C)
  abort "axis-limits: L, V or C missing"
if param.L == "X"
  M203 X{param.V}
  M201 X{param.C}
elif param.L == "Y"
  M203 Y{param.V}
  M201 Y{param.C}
elif param.L == "Z"
  M203 Z{param.V}
  M201 Z{param.C}
elif param.L == "U"
  M203 U{param.V}
  M201 U{param.C}
elif param.L == "V"
  M203 V{param.V}
  M201 V{param.C}
elif param.L == "W"
  M203 W{param.V}
  M201 W{param.C}
elif param.L == "A"
  M203 A{param.V}
  M201 A{param.C}
elif param.L == "B"
  M203 B{param.V}
  M201 B{param.C}
elif param.L == "C"
  M203 C{param.V}
  M201 C{param.C}
else
  abort "axis-limits: unknown axis"
