# Laser interlocks (lid, extraction, key)

The service supports three OPTIONAL interlocks of the laser: the lid, the extraction and a key switch. Each one is a switch wired
to a general purpose input of the Duet 3. Without them the Workbench keeps the manual safety checklist.

**The protection of the hardware is done by the firmware.** The service only complements it: it refuses to start laser work
from its API while an interlock is not ready, shows the state, and raises an alarm if one opens during a job. A crashed
service, a program that writes G-code directly or a job started from DWC are not stopped by the service. Wire and configure
the firmware as below.

## RRF configuration (example)

In `config.g`, one input per interlock. The pin names are an example: use the ones you wired, and wire the switches so that an
open circuit, a cut wire or an unplugged connector reads as the UNSAFE level.

```
M950 J0 C"io3.in"      ; lid switch              -> sensors.gpIn[0]
M950 J1 C"io4.in"      ; extraction running      -> sensors.gpIn[1]
M950 J2 C"io5.in"      ; key switch              -> sensors.gpIn[2]
```

`M950 J<N>` creates `sensors.gpIn[N]`; the service reads its `value` (0 or 1) from the object model.

The stop lives in the firmware, with `M581` triggers (see the M581 / M582 pages of the RepRapFirmware documentation for the
version installed; the form below is the RRF 3 one). `T` is the trigger number (T0 emergency stop, T1 pause the print, T2 resume,
T3 and up run `sys/trigger<T>.g`), `S` the edge (1 rising, 0 falling), `C` the condition (0 always, 1 only when printing from
the SD, 2 whenever a job runs). The same physical pin can be given to `M950 J` and to `M581` only if your firmware version
accepts it; if it refuses, wire the switch to two inputs in parallel.

```
; lid opened (input goes low) while anything is running: run sys/trigger3.g
M581 P"io3.in" T3 S0 C0
; extraction lost: pause the job
M581 P"io4.in" T1 S0 C2
; key turned off: run sys/trigger5.g
M581 P"io5.in" T5 S0 C0
```

`sys/trigger3.g` (and `trigger5.g`) switch the laser off and stop the work:

```
M5                     ; laser off
M25                    ; pause a running job (M0 cancels it)
M118 P0 L2 S"Laser interlock open"
```

A trigger only fires on a CHANGE of the input. To refuse a start when the input already has the unsafe level, read it at the
beginning of the laser macros with `M582 T3` (runs the trigger macro if the input is in the triggering state now).

## Declare them to the service

With `profile.set` (admin; the Machine page when available):

```
{"changes": {"interlocks": {
   "lid":        {"gpin": 0, "active_when": "high", "label": "Lid"},
   "extraction": {"gpin": 1, "active_when": "high", "label": "Extraction"},
   "key":        {"gpin": 2, "active_when": "high", "label": "Key"}}}}
```

`gpin` is the N of `M950 J<N>`; `active_when` is the level at which the interlock is SATISFIED (lid closed...). Leave `gpin`
null for the ones you do not have. After that:

- `capabilities.get` reports `lid_interlock`, `extraction_interlock` and `key_interlock` as present, and the Workbench shows
  the interlock instead of asking the operator to tick the matching point of the list;
- `safety.status` returns `ok`, `open` or `unknown` for each one (`unknown` = the input does not exist or has no value, and
  counts as not ready);
- in Laser mode `job.start` and `frame.start` (laser) are refused with `interlock_open` while one is not ok;
- if one opens (or cannot be read) during a laser job, the protection guard sends an urgent `guard_alarm` (not more than once
  per `renotify_s` for the same interlock).
