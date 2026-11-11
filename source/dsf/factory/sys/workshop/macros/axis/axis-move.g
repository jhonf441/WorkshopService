; sys/workshop/macros/axis/axis-move.g -- WorkshopMotors: moves ONE axis by its letter (the
; G-codes do not take the axis letter from a variable, so it branches).
;   L axis letter ("X","Y","Z","U","V","W","A","B","C")
;   P MACHINE position (G53) to go to
;   F speed mm/min
; Use: M98 P"0:/sys/workshop/macros/axis/axis-move.g" L"U" P100 F3000
; Every G1 carries S0 (in Laser mode a G1 with S turns the laser on).

if !exists(param.L) || !exists(param.P) || !exists(param.F)
  abort "axis-move: L, P or F missing"
G90                             ; absolute: the calling channel may have been left in G91 (jog, loose G91/G1/G90); when the macro ends it goes back to the previous mode by itself
if param.L == "X"
  G53 G1 X{param.P} F{param.F} S0
elif param.L == "Y"
  G53 G1 Y{param.P} F{param.F} S0
elif param.L == "Z"
  G53 G1 Z{param.P} F{param.F} S0
elif param.L == "U"
  G53 G1 U{param.P} F{param.F} S0
elif param.L == "V"
  G53 G1 V{param.P} F{param.F} S0
elif param.L == "W"
  G53 G1 W{param.P} F{param.F} S0
elif param.L == "A"
  G53 G1 A{param.P} F{param.F} S0
elif param.L == "B"
  G53 G1 B{param.P} F{param.F} S0
elif param.L == "C"
  G53 G1 C{param.P} F{param.F} S0
else
  abort "axis-move: unknown axis"
