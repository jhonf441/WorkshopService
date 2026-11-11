; sys/workshop/macros/axis/axis-probe.g -- WorkshopMotors (Motors page > Test, Z axis)
; For the axis that uses the probe as endstop (Z with BLTouch): measures
; with G30 S-1 the bed WHERE the head IS (it does not move X/Y; it touches at
; head + probe offset) and WITHOUT changing Z: it only reports at what height it
; triggered. If Z lost steps between two measurements, the height changes.
; Result in global.workshopMeasurement (mm, in the current Z frame).
; Use: M98 P"0:/sys/workshop/macros/axis/axis-probe.g"

if !exists(global.workshopMeasurement)
  global workshopMeasurement = 0
if #sensors.probes < 1 || sensors.probes[0] == null
  abort "axis-probe: there is no K0 probe"
if !move.axes[0].homed || !move.axes[1].homed || !move.axes[2].homed
  abort "axis-probe: home X, Y and Z first"

M280 P0 S160                    ; BLTouch: clear the alarm (raises the pin)
G4 P300
M402                            ; pin stowed
G4 P300
G90                             ; absolute: the calling channel may have been left in G91 (jog, loose G91/G1/G90); when the macro ends it goes back to the previous mode by itself
M400
G53 G1 Z{max(move.axes[2].machinePosition, 10)} F600 S0   ; room to deploy
M400
G30 S-1                         ; measure without changing Z
M400
set global.workshopMeasurement = sensors.probes[0].lastStopHeight
G53 G1 Z10 F600 S0
M400
