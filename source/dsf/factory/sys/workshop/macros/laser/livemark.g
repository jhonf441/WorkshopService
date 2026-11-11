; livemark.g -- tells the service that a LIVE job starts (only when it is one).
; The last line of every material macro: M98 P"0:/sys/workshop/macros/laser/livemark.g" N"<material name>"
; When the job is LIVE (a program sends it through the bridge: no file is running on the machine) it calls the job.start
; operation of the service (the service marks the job: jog and zones stay blocked, Activity logs it). When the job is a
; G-code file it does nothing. A macro cannot talk to the bridge with M118 (the bridge only reads what the program
; sends); it uses service-call.g like any other macro. Everything else a material needs stays in its own macro.
; N = name shown for the live job (optional)
; 2026-10-17: only when the material macro was sent by a program. The same macro run from the web page (HTTP channel: Measure and
; focus, a material button in the Mesa) is a preparation, not a job: it used to open a live job before any cutting started.
; 2026-10-18: if laserfocus.g did not reach its end (probe not triggered, probe error...) the job must not go on: abort (cancels a file job, and the
; error of this macro makes the bridge refuse the rest of a live job).
if exists(global.workshopFocusOk) && !global.workshopFocusOk
    abort "Focus not set (laserfocus.g did not finish: the Z probe did not trigger or the probe reported an error). The job was stopped / El foco no quedo fijado (laserfocus.g no termino): trabajo detenido."
if job.file.fileName == null && inputs[state.thisInput].name != "HTTP"
    var nombre = exists(param.N) ? param.N : "Live job"
    M98 P"0:/sys/workshop/macros/system/service-call.g" S"job.start" A{"name=" ^ var.nombre} W0 Q1
