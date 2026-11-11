; workzeroaxis.g -- Go to the work zero on ONE axis only.
; Called by the floating jog (EmergencyFab.js, Advanced tab ->
; "Work zones / Go to zero"). Sibling of sys/workshop/macros/work/workzero.g (the
; "Go To Zero" of DWC, which moves X and Y together).
;
; Param A: 0 = X, 1 = Y, 2 = Z   (axis index in move.axes)
;
; X / Y: same safety rule as workzero.g -- before moving
; in the plane it raises Z to a safe height (safeZ above the work
; zero, or the current one if it is already higher, never above the maximum
; of the axis) and leaves it there.
; Z: GOES DOWN to Z0 of the active workplace (contact point:
; surface of the part/bed). It goes SLOWLY (zFeed) on purpose; the
; jog button asks for a double tap to confirm.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var safeZ = 5        ; mm above the Z work zero
var zFeed = 300      ; mm/min to go down to Z0

if !exists(param.A) || param.A < 0 || param.A > 2
    abort {var.en ? ("Go to zero: axis missing (A0=X, A1=Y, A2=Z)") : ("Ir a cero: falta el eje (A0=X, A1=Y, A2=Z)")}

if !move.axes[param.A].homed
    abort {var.en ? ("Go to zero: home " ^ move.axes[param.A].letter ^ " first") : ("Ir a cero: primero hace homing de " ^ move.axes[param.A].letter)}

M400                 ; wait for any previous move to finish
G90                  ; absolute coordinates

if param.A < 2
    if move.axes[2].homed
        var zOffset = move.axes[2].workplaceOffsets[move.workplaceNumber]
        var zMaxUser = move.axes[2].max - var.zOffset
        var zTarget = min(max(move.axes[2].userPosition, var.safeZ), var.zMaxUser)
        G0 Z{var.zTarget}
    if param.A == 0
        G0 X0
    else
        G0 Y0
else
    if state.machineMode == "Laser"
        G1 Z0 F{var.zFeed} S0   ; Laser mode only: S is the laser power there
    else
        G1 Z0 F{var.zFeed}      ; in CNC S is the spindle speed: do not touch it

M400
if var.en
    M118 P0 S{"At work zero G" ^ (54 + move.workplaceNumber) ^ " (" ^ move.axes[param.A].letter ^ "0)"}
else
    M118 P0 S{"En el cero de trabajo G" ^ (54 + move.workplaceNumber) ^ " (" ^ move.axes[param.A].letter ^ "0)"}
