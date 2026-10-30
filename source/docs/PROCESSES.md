# Internal processes and automations

What each background process of the WorkshopService backend is, what it is for, what happens if it stops,
what it relies on and where it is adjusted. The same text is shown, unfolded, in the service page
(Processes and automations > More detail). Each process sends a heartbeat on every good loop; if one dies it is
relaunched by itself. The page also shows its pace (average interval against the expected one), CPU,
loops, errors, relaunches and the last minutes of CPU and interval.

## Processes

### G-code interceptor (`interceptor`)

- **What it is:** Watches the M3, M4 and M5 G-codes that go through the board as they happen.
- **What it is for:** Turns the air assist on only when the laser turns on and off a few seconds after M5, so nobody has to remember it.
- **If it stops:** The air no longer turns on and off by itself; the laser keeps working the same. It restarts by itself.
- **What it relies on:** The DSF connection (code interception) and the air relay (output 7).
- **Where to adjust it:** Automations > Automatic air with the laser.

### Status lights (`status_light`)

- **What it is:** Paints the status zone of the LED strip and works out the indicator the screens show.
- **What it is for:** Shows at a glance what the machine is doing (idle, job, pause, risk) with a colour and an effect, on the strip and in the bar.
- **If it stops:** The status LEDs keep the last colour or the board fallback takes over; the screens stop showing the indicator.
- **What it relies on:** The board object model, the M150 commands and the rules of the Lights and status page.
- **Where to adjust it:** Lights and status page. It rests when that plugin is stopped.

### Energy meter (`consumo`)

- **What it is:** Reads the Tuya energy meter (W, V, A and accumulated kWh).
- **What it is for:** Stores the consumption history so the cost per day, month or job can be worked out.
- **If it stops:** No new readings are saved; the chart shows a gap. What was already saved is kept.
- **What it relies on:** The Tuya meter over the local network and the database.
- **Where to adjust it:** Power page (rate and meter). It rests when that plugin is stopped.

### Jobs and zones (`trabajos`)

- **What it is:** Detects when a job starts and ends, the mode changes or the work zone changes.
- **What it is for:** Feeds the Activity history, the phone alerts and the hours and energy per job.
- **If it stops:** Job starts and ends are not recorded; Activity and the alerts stop hearing about them.
- **What it relies on:** The machine state (single subscription) and the database.
- **Where to adjust it:** Activity page.

### Motors (`motors`)

- **What it is:** Works out the pulse frequency, RPM, speed and driver state of each motor.
- **What it is for:** Shows how close to its limit each motor works and whether a driver reports a problem.
- **If it stops:** The Motors page stops updating. Movement is not affected.
- **What it relies on:** The object model, M122 and a read-only read of the GSTAT register.
- **Where to adjust it:** Motors page. It rests when that plugin is stopped.

### Jog (`jog`)

- **What it is:** Moves the machine while a jog control is held.
- **What it is for:** Turns the knob, the arrows and the keyboard into short chained moves with the laser off.
- **If it stops:** Jog stops moving; the rest of the machine is unaffected. If the screen heartbeat stops arriving, the movement cuts itself.
- **What it relies on:** Its own connection to the board and the motion owner.
- **Where to adjust it:** Floating Jog panel.

### Board events (`eventos`)

- **What it is:** Watches the board messages: emergencies, pauses, errors and warnings.
- **What it is for:** Stores them in Activity and sends them to the phone when needed.
- **If it stops:** Emergency, pause and error alerts are lost while it is stopped.
- **What it relies on:** The object model messages (single subscription) and the notifier.
- **Where to adjust it:** Activity page > phone alerts.

### Job path (`traza`)

- **What it is:** Records the path of the running job.
- **What it is for:** Lets Zones > Job draw the path. It only records while someone is watching; otherwise it sleeps.
- **If it stops:** The job path is not drawn. The job itself is not affected.
- **What it relies on:** The object model (position) and files on the SD.
- **Where to adjust it:** Zones > Job.

### System health (`salud`)

- **What it is:** Measures the Pi temperature, WiFi, services and power supply.
- **What it is for:** Warns before something fails: high temperature, WiFi down, a stopped service or an unexpected reboot.
- **If it stops:** The Health page and its alerts stop updating.
- **What it relies on:** System commands (vcgencmd, nmcli, systemctl) and the object model.
- **Where to adjust it:** Health page (thresholds in the settings).

### Camera relay (`camara`)

- **What it is:** Shares the camera video with all screens and records the timelapses.
- **What it is for:** Prevents every screen from opening its own connection to the weak camera.
- **If it stops:** The shared video and new timelapses are lost.
- **What it relies on:** The ESP32-CAM camera, ffmpeg and the SD.
- **Where to adjust it:** Camera page. The relay is shared with Vision and Workbench.

### Timed shutdown (`temporizador`)

- **What it is:** Counts down the timed shutdown of the bar.
- **What it is for:** Turns everything off at the chosen time, without cutting a running job.
- **If it stops:** The scheduled shutdown does not run.
- **What it relies on:** The system clock and the power cut.
- **Where to adjust it:** Side bar > Shutdown.

### Active risk (`riesgo`)

- **What it is:** Detects when something leaves the machine without a protection: calibrations and released motors.
- **What it is for:** Warns on screens and LEDs for as long as the risk lasts and clears itself when it ends.
- **If it stops:** The risk is not announced. The board protections are unchanged.
- **What it relies on:** The object model and the flags set by the calibration macros.
- **Where to adjust it:** No settings: it turns on when calibrating or releasing motors.

### Configuration roll-back (`config_guard`)

- **What it is:** Watches the board start-up after a new configuration is saved.
- **What it is for:** Goes back to the previous configuration if the start-up fails or nobody confirms.
- **If it stops:** A bad configuration would not be reverted by itself.
- **What it relies on:** The config.g backup and the board state.
- **Where to adjust it:** Machine configurator.

### Motion owner (`motion`)

- **What it is:** Decides whether the machine may move or change its geometry, and why not.
- **What it is for:** Prevents two things from moving at once (jog, macros, job) and explains the block.
- **If it stops:** The pages do not know whether a move is in progress and may allow too much or too little.
- **What it relies on:** The object model, the screen heartbeats and the bridge.
- **Where to adjust it:** No settings: used by Jog, Zones and the macros.

### Machine state (DSF) (`suscripcion`)

- **What it is:** Keeps the single DSF subscription with the machine state.
- **What it is for:** It is the source every other process reads from, so nobody asks the board for the state on its own.
- **If it stops:** The processes keep old data until it reconnects, which it does by itself.
- **What it relies on:** The DSF socket.
- **Where to adjust it:** See patches/s and KB/s under 'Load this service puts on the Duet'.

### Black box (`caja_negra`)

- **What it is:** Writes a line every few seconds with load, CPU, RAM, temperature and state to the SD.
- **What it is for:** If the Pi hangs or is switched off by force, there is a record of the last moments.
- **If it stops:** No trail is kept; after a hang the cause will not be known.
- **What it relies on:** Files on the SD (two of 512 KB, rotating).
- **Where to adjust it:** Database and backups section.

## Automations

### Automatic air with the laser

- **What it does:** Turns the air assist on with M3 or M4 and off a few seconds after M5.
- **When it acts:** When the laser turns on in a cut (M3/M4).
- **Good to know:** With the switch off, the air is only handled by hand or by the program. The delay avoids turning the air off between two consecutive strokes.

### Status lights

- **What it does:** The status LED strip paints itself according to the mode and what the machine is doing.
- **When it acts:** When the machine state changes.
- **Good to know:** The lights are controlled in the Lights and status page; here you only see the result. With the manual lighting on, those LEDs are used by the work light.

### Turn everything off when done

- **What it does:** When the job ends it turns everything off and cuts the machine power.
- **When it acts:** When the running job ends, or the next one if there is none.
- **Good to know:** It is only armed and disarmed here or in the side bar; it never cuts a running job. It cuts the power through the Tuya meter: make sure nothing must stay on.

### Live job

- **What it does:** Marks the live job sent by an external program through the G-code bridge.
- **When it acts:** With BRIDGE JOB START at the start and BRIDGE JOB END at the end, or with the same message inside an M118.
- **Good to know:** The idle timeout closes a job that was left open and adds its hours and kWh. While there is one, jog and zones are locked so nothing moves the machine in the middle of the cut.
