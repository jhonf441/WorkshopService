; jogFreeFailsafe.g -- ON-BOARD failsafe of the "without limits" mode of the jog.
; Call it from sys/daemon.g (which RepRapFirmware runs by itself, all the time):
;     M98 P"0:/sys/workshop/macros/work/jogFreeFailsafe.g"
; If the mode was left active and the backend stopped sending its heartbeat for more
; than 10 s (Raspberry Pi hung, plugin down, network cut), it puts back the
; limits and the mandatory homing, the current at 100 % and turns the stall
; detection off. So the mode can never stay active with nobody watching.
; No M99 on purpose: every M99 leaves "Aborted macro file" in the DSF
; log, and daemon.g calls this macro on every loop.

if exists(global.jogFree) && exists(global.jogFreeTs)
    if global.jogFree && state.upTime - global.jogFreeTs > 10
        M564 S1 H1
        M913 X100 Y100 Z100
        M915 X Y Z R0
        set global.jogFree = false
        if exists(global.workshopLanguage) && global.workshopLanguage == "en"
            M118 P0 S{"Jog without limits: no heartbeat from the jog for more than 10 s. Axis limits and homing were restored."}
        else
            M118 P0 S{"Jog sin limites: sin latido del jog por mas de 10 s. Se restauraron los limites y el homing obligatorio."}
