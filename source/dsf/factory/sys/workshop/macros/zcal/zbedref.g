; zbedref.g -- the surface just measured by the Z homing (G30 at the
; centre of the bed) becomes the BED reference to measure thicknesses
; (see zsurface.g). homez.g and homeall.g call it after their G30.
if !exists(global.workshopZBed)
    global workshopZBed = 0
if !exists(global.workshopZBedOk)
    global workshopZBedOk = true
set global.workshopZBed = 0
set global.workshopZBedOk = true
