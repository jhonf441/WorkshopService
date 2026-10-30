; Motion parameters (odd formatting on purpose)
M584 X0.0 Y0.1 Z0.2:0.3 E0.4         ; drives
M569 P0.0 S0 D3 ; X direction and mode
M569  P0.1 S0 T2.5:2.5:5:0   ; Y with a step timing that must stay
M569 P1 S1       ; board 0 driver 1 again: the later one wins
M569 P0.4 S1 D4 ; closed loop
M569.1 P1.0 T1 ; closed loop setup (never touched)
M906  X1200   Y1200 Z1500:1500 E800 I30 ;currents
M906 Z1800 ; second definition
M913 X60 Y60 ; percent
M203 X18000 Y18000 Z600 E3600 ; speeds
M203 S1 Z10 ; in mm/s: not rewritten
M201 X500 Y500 Z100 E5000
M566 X600 Y600 Z60 E300
M205 X600 Y600 ; job jerk
M593 P"zvd" F43.5 ;shaper
M425 X0.1 ; backlash
M556 S100 X0.3 Y0.1 Z-0.2
