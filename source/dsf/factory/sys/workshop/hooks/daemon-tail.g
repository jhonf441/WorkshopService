; daemon-tail.g -- target of the "daemon-tail" hook of sys/daemon.g (managed block of the workshop). Owned by the WorkshopJog plugin.
; daemon.g runs this on every loop, so it must stay short and must NOT end with M99 (each M99 leaves "Aborted macro file" in the DSF log).
; It replaces the line that called the failsafe of the jog without limits directly.

if fileexists("0:/sys/workshop/macros/work/jogFreeFailsafe.g")
    M98 P"0:/sys/workshop/macros/work/jogFreeFailsafe.g"
