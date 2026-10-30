; Configuration file for Duet 3 (odd formatting on purpose)
G21                                   ; mm
M584 X0.0 Y0.1 Z0.2:0.3 E0.4         ; drives
M92  X80.00   Y80.00 Z400 E415.5 ;steps
M92 X160                       ; defined twice: the later one wins
M350 X16 Y16 Z16 I1
	M208 X-12:553 Y0:465   ; limits
M208 Z0:300
M558 P9 C"io3.in" H5 F500:120 T3000 ; the probe
G31 P500   X57.26 Y41.21 Z2.14   ; the probe offsets (no K = probe 0)
M563 P0 S"Laser X1 Y2"
G10 P0 X0 Y0 Z0
G10 L2 P1 X10 Y20 Z0 ; G54
M98 P"modes.g"
