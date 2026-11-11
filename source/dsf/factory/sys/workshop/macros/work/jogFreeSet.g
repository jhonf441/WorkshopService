; jogFreeSet.g -- "without limits" mode of the jog (no homing / outside M208).
; The backend (WorkshopService, jog_move.py) calls it on entering: M98 P"0:/sys/workshop/macros/work/jogFreeSet.g" A1
; Creates the variables and marks the mode as active with a heartbeat. The rest
; (M564 S0 H0, M913, M915) is sent by the backend after this macro, and restored
; on leaving. If the backend stops sending the heartbeat
; (global.jogFreeTs), sys/workshop/macros/work/jogFreeFailsafe.g restores everything by itself.

if !exists(global.jogFree)
    global jogFree = false
if !exists(global.jogFreeTs)
    global jogFreeTs = 0

if exists(param.A) && param.A == 1
    set global.jogFreeTs = state.upTime
    set global.jogFree = true
else
    set global.jogFree = false
