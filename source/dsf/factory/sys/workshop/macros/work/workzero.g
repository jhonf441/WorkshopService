; workzero.g
; Called by the "Go To Zero" button of the CNC Movement panel of DWC
; (M98 P"workzero.g"). Takes X/Y to the zero of the active workplace
; (G54..G59). For safety it first raises Z to a safe height above the
; work zero, and leaves it there (it does not go down to Z0 so the tool
; does not dig in / hit the part).

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)
var safeZ = 5                                   ; mm above the Z work zero

if !move.axes[0].homed || !move.axes[1].homed
    abort {var.en ? ("Go to zero: home X and Y first") : ("Ir a cero: primero hace homing de X e Y")}

M400                                            ; wait for any previous move to finish
G90                                             ; absolute coordinates

if move.axes[2].homed
    var zOffset = move.axes[2].workplaceOffsets[move.workplaceNumber]
    var zMaxUser = move.axes[2].max - var.zOffset         ; Z maximum expressed in work coordinates
    var zTarget = min(max(move.axes[2].userPosition, var.safeZ), var.zMaxUser)
    G0 Z{var.zTarget}

G0 X0 Y0
M400                                            ; report (and let the page read the position again) only on arrival
if var.en
    M118 P0 S{"At work zero G" ^ (54 + move.workplaceNumber) ^ " (X0 Y0)"}
else
    M118 P0 S{"En el cero de trabajo G" ^ (54 + move.workplaceNumber) ^ " (X0 Y0)"}
