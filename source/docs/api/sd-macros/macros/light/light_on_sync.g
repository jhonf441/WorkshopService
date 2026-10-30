; Working light on through WorkshopService (2026-10-13: API, no custom code).
; The service runs the operation light.set and keeps its own state (the pages) in step with the machine.
; Needs WorkshopService 2.0 (it writes service-call.g at start).
M98 P"0:/sys/workshop/macros/service-call.g" S"light.set" A"on=true" Q1
