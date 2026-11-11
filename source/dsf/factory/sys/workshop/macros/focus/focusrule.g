; focusrule.g -- focus height by thickness (the maker table of the laser + the geometry of the machine).
;
; Use:  M98 P"0:/sys/workshop/macros/focus/focusrule.g" T6        ->  global.focusRuleH = height H (mm above the surface)
;
; H = tab - edge - lever(T), rounded to 0.1 mm
;   tab    the tab of the lens box: with lever 0 the focus is that many mm under the edge of the box (8.0 on the reference laser)
;   edge   the reference of the laser (what the probe measures) is that many mm UNDER the edge of the box (0.533 on the reference laser)
;   lever  table of the maker: under 5 mm = 0, 5 = 2, 8 = 4, 10 = 5, 12 = 6, 15 or more = 7; interpolated between rows
; tab and edge are the geometry of THE MACHINE: they live in 0:/sys/workshop/config/focus.json (geometry.focusBelowBoxEdge and
; geometry.boxEdgeAboveReference), measured with focusref.g. RRF cannot read JSON, so this macro loads the same two numbers from
; 0:/sys/workshop/config/focus.g (global.focusTab, global.focusBoxEdge). Keep both files equal: the page reads the json and warns when they differ.

var en = exists(global.workshopLanguage) ? (global.workshopLanguage == "en") : false   ; messages in English (DWC language, see sys/workshop/macros/system/language.g)

if !exists(param.T)
    abort {var.en ? ("focusrule: T (thickness in mm) missing") : ("focusrule: falta T (grosor en mm)")}
if param.T <= 0 || param.T > 100
    abort {var.en ? ("focusrule: T" ^ param.T ^ " out of range (0 to 100 mm)") : ("focusrule: T" ^ param.T ^ " fuera de rango (0 a 100 mm)")}
M98 P"0:/sys/workshop/config/focus.g"           ; the geometry of the machine (tab, edge)
if !exists(global.focusTab) || !exists(global.focusBoxEdge)
    abort {var.en ? ("focusrule: the geometry is missing (0:/sys/workshop/config/focus.g)") : ("focusrule: falta la geometria (0:/sys/workshop/config/focus.g)")}
if !exists(global.focusRuleH)
    global focusRuleH = 0

var t = param.T
var lever = 0
if var.t >= 15
    set var.lever = 7
elif var.t >= 12
    set var.lever = 6 + (var.t - 12) / 3
elif var.t >= 10
    set var.lever = 5 + (var.t - 10) / 2
elif var.t >= 8
    set var.lever = 4 + (var.t - 8) / 2
elif var.t >= 5
    set var.lever = 2 + (var.t - 5) * 2 / 3
var h = floor((global.focusTab - global.focusBoxEdge - var.lever) * 10 + 0.5) / 10
; the same range as laserfocus.g and focushere.g (0.3 to 60 mm: the table gives 0.467 for 15 mm or more with the reference laser). A wrong geometry
; (focus.g) or a typo in T must not send the head to a height the laser is not focused for: nothing is moved here, the caller stops.
if var.h < 0.3 || var.h > 60
    ; RRF rejects an argument longer than 255 characters ("Keyword argument too long"): the message is built from two short expressions
    var m1 = var.en ? ("focusrule: focus height H" ^ var.h ^ " for T" ^ param.T) : ("focusrule: la altura de foco H" ^ var.h ^ " para T" ^ param.T)
    var m2 = var.en ? "is out of range (0.3 to 60 mm): check the geometry (0:/sys/workshop/config/focus.g)" : "esta fuera de rango (0.3 a 60 mm): revisa la geometria (0:/sys/workshop/config/focus.g)"
    abort {var.m1 ^ " " ^ var.m2}
set global.focusRuleH = var.h
