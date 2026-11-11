; boot.g -- target of the "boot" hook of sys/config.g (managed block of the workshop). Owned by the WorkshopPrinting plugin.
; It reproduces, with the paths of the new layout, the start-up lines that config.g had: mode state, automatic mode, work origins.

if !exists(global.selectedMode)
    if fileexists("0:/sys/workshop/data/modestate.g")
        M98 P"0:/sys/workshop/data/modestate.g"
if fileexists("0:/sys/workshop/modes/automodeselect.g")
    M98 P"0:/sys/workshop/modes/automodeselect.g"
if fileexists("0:/sys/workshop/macros/work/workplaces.g")
    M98 P"0:/sys/workshop/macros/work/workplaces.g"
