; sys/workshop/macros/axis/axis-touch.g -- WorkshopMotors: moves ONE axis D mm (relative) with
; G1 H4: it stops when its endstop triggers and UPDATES the position (it does not
; overwrite it with the limit, like H1), so lost steps can be seen.
; Use: M98 P"0:/sys/workshop/macros/axis/axis-touch.g" L"X" D-20

if !exists(param.L) || !exists(param.D)
  abort "axis-touch: L or D missing"
G91
if param.L == "X"
  G1 H4 X{param.D} F300 S0
elif param.L == "Y"
  G1 H4 Y{param.D} F300 S0
elif param.L == "Z"
  G1 H4 Z{param.D} F300 S0
elif param.L == "U"
  G1 H4 U{param.D} F300 S0
elif param.L == "V"
  G1 H4 V{param.D} F300 S0
elif param.L == "W"
  G1 H4 W{param.D} F300 S0
elif param.L == "A"
  G1 H4 A{param.D} F300 S0
elif param.L == "B"
  G1 H4 B{param.D} F300 S0
elif param.L == "C"
  G1 H4 C{param.D} F300 S0
else
  G90
  abort "axis-touch: unknown axis"
G90
M400
