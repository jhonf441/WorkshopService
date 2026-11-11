; zhere0.g -- "Z0 here" of WorkshopJog: G92 Z0 at the current position, and
; shifts the bed reference (zsurface.g) by the same amount, so the thickness of the
; material can still be measured afterwards.
if exists(global.workshopZBed)
    set global.workshopZBed = global.workshopZBed - move.axes[2].machinePosition
G92 Z0
