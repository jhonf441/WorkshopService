; sys/workshop/macros/system/rs485-read.g -- WorkshopRS485 ("RS485 port of the Duet" bus)
; Reads Modbus registers with the RepRapFirmware master and leaves the result
; in global.rs485Reading (null = no answer / error), which the plugin reads.
; Use: M98 P"0:/sys/workshop/macros/system/rs485-read.g" Q<port> A<address> F<3|4> R<register> B<count>
if !exists(global.rs485Reading)
    global rs485Reading = null
set global.rs485Reading = null
M261.1 P{param.Q} A{param.A} F{param.F} R{param.R} B{param.B} V"dato"
set global.rs485Reading = var.dato
