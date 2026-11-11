; handcorner.g -- measures WHERE the head was left (moved by hand, see
; sys/workshop/macros/work/handfree.g) by going to the physical X and Y endstops and
; measuring how far it travelled. Leaves the result in BED coordinates (= point
; where the POINTER was) in global.handCornerX / handCornerY, and leaves X/Y
; homed (G28 X Y) at the end.
;
;   point = position of the endstop (M208 min, like the homing
;           with G1 H1) + distance travelled until touching it
;
; Expected precision ~ +-0.4 mm: when energised, the rotor jumps to the nearest
; equilibrium point (up to 2 full steps = 0.4 mm with 80 steps/mm
; at 16 microsteps). Enough to delimit the cut area; for the origin
; of a part use the jog.
;
; G1 H4 (RRF 3.2+): ends the move when the endstop triggers and
; UPDATES the position (it does not overwrite it with the limit like H1) -- that is
; why the distance can be measured as a difference of positions.
;
; LASER: every G1 carries an explicit S0. In Laser mode (M452) a G1 with S
; turns the laser on, and a previous M3 Snnn without M5 sets the default power
; of the G1s without S. S0 = zero power; in CNC/FFF S is ignored.
; (G28 uses sys/homex.g / homey.g, which move with G1 H1 without S -- like
; any normal homing of the machine.)

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var fastF = 3000            ; mm/min towards the endstop (first pass)
var slowF = 300             ; mm/min second pass (the one used to measure)
var backoff = 5             ; mm of back-off between passes

if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Capture corner: a job is running") : ("Capturar esquina: hay un trabajo en curso")}

if !exists(global.handCornerX)
    global handCornerX = null
if !exists(global.handCornerY)
    global handCornerY = null
set global.handCornerX = null           ; invalidates the previous measurement until this one ends
set global.handCornerY = null

M17 X Y                     ; energise X/Y where the head was left
if exists(global.motorsLoose)
  set global.motorsLoose = false
G4 P300                     ; let the rotor settle
M400

var travelX = move.axes[0].max - move.axes[0].min + 20
var travelY = move.axes[1].max - move.axes[1].min + 20

G91
G1 H2 Z5 F600 S0            ; raise 5 mm before moving X/Y (like homex.g / homey.g)

; --- X
var x0 = move.axes[0].machinePosition
G1 H4 X{-var.travelX} F{var.fastF} S0
M400
if !sensors.endstops[0].triggered
    abort {var.en ? ("Capture corner: X travelled all the way without hitting the endstop. Check the X switch.") : ("Capturar esquina: X recorrio todo sin tocar el final de carrera. Revisar el switch de X.")}
G1 H2 X{var.backoff} F{var.fastF} S0
G1 H4 X{-(var.backoff + 2)} F{var.slowF} S0
M400
if !sensors.endstops[0].triggered
    abort {var.en ? ("Capture corner: the second X pass did not hit the endstop.") : ("Capturar esquina: la segunda pasada de X no toco el final de carrera.")}
var distX = var.x0 - move.axes[0].machinePosition

; --- Y
var y0 = move.axes[1].machinePosition
G1 H4 Y{-var.travelY} F{var.fastF} S0
M400
if !sensors.endstops[1].triggered
    abort {var.en ? ("Capture corner: Y travelled all the way without hitting the endstop. Check the Y switch.") : ("Capturar esquina: Y recorrio todo sin tocar el final de carrera. Revisar el switch de Y.")}
G1 H2 Y{var.backoff} F{var.fastF} S0
G1 H4 Y{-(var.backoff + 2)} F{var.slowF} S0
M400
if !sensors.endstops[1].triggered
    abort {var.en ? ("Capture corner: the second Y pass did not hit the endstop.") : ("Capturar esquina: la segunda pasada de Y no toco el final de carrera.")}
var distY = var.y0 - move.axes[1].machinePosition

G1 H2 Z-5 F600 S0           ; Z back to where it was
G90

; A distance ~0 or larger than the travel = it did not hit the endstop
; where expected (cable, switch, head already against the end): do not save.
if var.distX < -0.5 || var.distX > var.travelX - 1 || var.distY < -0.5 || var.distY > var.travelY - 1
    var tmsg1 = "Capturar esquina: medicion invalida (X " ^ var.distX ^ " mm, Y " ^ var.distY ^ " mm). Revisar finales de carrera."
    if var.en
        set var.tmsg1 = "Capture corner: invalid measurement (X " ^ var.distX ^ " mm, Y " ^ var.distY ^ " mm). Check the endstops."
    abort {var.tmsg1}

set global.handCornerX = move.axes[0].min + var.distX
set global.handCornerY = move.axes[1].min + var.distY

G28 X Y                     ; leave X/Y with a normal homing (it is already against the endstops)
if var.en
    M118 P0 S{"Corner measured: pointer at X" ^ global.handCornerX ^ " Y" ^ global.handCornerY ^ " (+-0.4 mm)"}
else
    M118 P0 S{"Esquina medida: puntero en X" ^ global.handCornerX ^ " Y" ^ global.handCornerY ^ " (+-0.4 mm)"}
