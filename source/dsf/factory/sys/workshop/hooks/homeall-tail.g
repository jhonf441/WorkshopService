; homeall-tail.g -- target of the "homeall-tail" hook of sys/homeall.g (managed block of the workshop). Owned by the WorkshopWorkbench plugin.
; Same call, in the same place, as the line the block replaces: the bed reference after homing.

if fileexists("0:/sys/workshop/macros/zcal/zbedref.g")
    M98 P"0:/sys/workshop/macros/zcal/zbedref.g"
