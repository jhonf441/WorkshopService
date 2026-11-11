; language.g -- language of the messages of the workshop macros (WorkshopJog).
; The page (05-i18n.js) calls it with the DWC language when it changes:
;   M98 P"0:/sys/workshop/macros/system/language.g" L"en"     (or L"es")
; The macros read global.workshopLanguage ("en" = English, anything else = Spanish).
if !exists(param.L)
    abort "language.g: L missing (en / es)"
if !exists(global.workshopLanguage)
    global workshopLanguage = param.L
else
    set global.workshopLanguage = param.L
