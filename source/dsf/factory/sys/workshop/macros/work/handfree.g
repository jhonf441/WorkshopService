; handfree.g -- "Release X/Y motors" to move the head BY HAND
; (cut area measurement, see sys/workshop/macros/work/handcorner.g).
;
; De-energises ONLY X and Y (Z stays firm, it does not fall). RRF marks X/Y as
; "not homed": the position is recovered with sys/workshop/macros/work/handcorner.g, which measures
; from where the head was left to the physical endstops.
;
; Move the head SLOWLY: turning a stepper fast by hand generates
; voltage that goes back to the driver.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
if state.status == "processing" || state.status == "paused" || state.status == "pausing" || state.status == "resuming" || state.status == "simulating"
    abort {var.en ? ("Release motors: a job is running") : ("Soltar motores: hay un trabajo en curso")}

M400
M18 X Y
; active risk (level 4): the Pi (riesgo.py) paints the LEDs and the red bar
; while X/Y are released (until capture or homing)
if !exists(global.motorsLoose)
  global motorsLoose = true
else
  set global.motorsLoose = true
if var.en
    M118 P0 S{"X/Y motors released: move the head by hand (slowly) and aim the POINTER at the corner. Then: Capture."}
else
    M118 P0 S{"Motores X/Y sueltos: mueve el cabezal a mano (despacio) y apunta el PUNTERO a la esquina. Despues: Capturar."}
