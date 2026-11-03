"""Power loss of Machine v2: `machine.power.get` (read only).

What the configuration does when the supply drops, as the machine has it now:
  - the M911 line of the configuration (S = voltage that triggers it, R = voltage the machine must regain to resume, P = the commands it runs);
  - whether RepRapFirmware left `0:/sys/resurrect.g` (written while a file job runs, used by M916 to resume it) and whether there is
    a `0:/sys/resurrect-prologue.g` (RRF runs it before resurrect.g);
  - the supply voltage now (`boards[0].vIn`).
Changing S and R is `machine.config.plan` kind `config.m911` (administrator); the P commands are never written from here.
"""
import machine_patch as pt
import machine_patch_motion as pm
from workshop_api import READ, WRITE, Arg, Op

CONFIG = "0:/sys/config.g"
RESURRECT = "0:/sys/resurrect.g"
PROLOGUE = "0:/sys/resurrect-prologue.g"


def read_m911(text):
    """{"s", "r", "commands"} of the effective (last) M911 line, or None. A key is missing when the line lacks it."""
    _, ls = pt.split_lines(text)
    found = [pt.tmap(code) for _, code in pt.live_lines(ls) if pt.command_word(code)[0] == "M911"]
    if not found:
        return None
    t, out = found[-1], {}
    for key, c in (("s", "S"), ("r", "R")):
        v = pm._first_float(t.get(c))
        if v is not None:
            out[key] = v
    if t.get("P", "").startswith('"'):
        out["commands"] = t["P"].strip('"')
    return out


def _volts(om):
    boards = (om or {}).get("boards") or []
    v = boards[0].get("vIn") if boards and isinstance(boards[0], dict) else None
    v = v.get("current") if isinstance(v, dict) else v
    return round(v, 1) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


MAX_TEXT = 8000   # characters of a file the page can show (the rest is cut, `truncated`)

# The standard resurrect-prologue.g: what the workshop wants before RRF resumes a job (laser / CNC ask, FFF resumes almost alone).
PROLOGUE_TEMPLATE = """; resurrect-prologue.g
; RepRapFirmware ejecuta este archivo automáticamente (si existe)
; ANTES del resurrect.g autogenerado, cuando reanudas un trabajo
; después de un corte de luz (o un M916/M918). En este punto config.g
; ya corrió en este arranque nuevo, así que global.selectedMode ya
; tiene el modo que estaba activo cuando se cortó la luz.
;
; - FFF: reanuda de forma bastante automática, como cualquier
;   impresora: solo re-homea X/Y, espera temperatura, y deshace la
;   retracción que hizo el M911 de config.g al cortarse la luz.
; - Láser / CNC: NO reanuda solo. Apaga el husillo/láser y la bomba
;   por si acaso, y PIDE CONFIRMACIÓN explícita antes de seguir:
;   reanudar un corte sin revisar la pieza y el entorno primero es
;   peligroso (la herramienta puede quedar justo donde estaba, a
;   punto de volver a encender el láser o el husillo).

if global.selectedMode = "Laser" || global.selectedMode = "CNC"
    M5                                   ; asegura que el husillo/láser esté apagado
    if global.selectedMode = "Laser"
        M42 P7 S0                        ; apaga también la bomba de aire

    M291 R"Recuperación tras corte de luz" P{"Estabas en modo " ^ global.selectedMode ^ ". Verifica que la pieza, la herramienta y el entorno estén en orden ANTES de continuar."} S4 K{"Sí, reanudar", "No, cancelar"} T0

    if input = 1
        M291 R"Cancelado" P"El trabajo quedó cancelado por seguridad. Revisa la máquina antes de empezar de nuevo." S1 T0
        M0                                ; cancela el trabajo (dispara cancel.g: apaga todo y deja en posición segura)

else
    M116                                  ; espera a que la cama/extrusor vuelvan a su temperatura
    G28 X Y                               ; rehomea X/Y por seguridad (asume que Z no se movió durante el corte)
    M83                                   ; extrusión relativa
    G1 E5 F1800 S0                        ; deshace la retracción de 5mm que hizo el M911 al cortarse la luz
"""


def _live(text):
    """The lines that do something: no comment, no blank, the trailing comment cut."""
    out = []
    for ln in str(text or "").splitlines():
        code = ln.split(";", 1)[0].strip()
        if code:
            out.append(code)
    return out


def _clip(text):
    t = str(text or "")
    return t[:MAX_TEXT], len(t) > MAX_TEXT


def read_resurrect(text):
    """What a resurrect.g says: the job (M23), where in the file it was (M26 S), the header comments and the G92 position."""
    lines = str(text or "").splitlines()
    job = next((ln.split('"')[1] for ln in lines if ln.startswith("M23 ") and '"' in ln), None)
    position = None
    g92 = {}
    for ln in _live(text):
        words = ln.split()
        if words[0] == "M26":
            for w in words[1:]:
                if w[:1] == "S" and w[1:].isdigit():
                    position = int(w[1:])
        elif words[0] == "G92":
            for w in words[1:]:
                if w[:1] in "XYZUVWABC":
                    try:
                        g92[w[0]] = float(w[1:])
                    except ValueError:
                        pass
    header = [ln.lstrip("; ").strip() for ln in lines if ln.startswith(";")][:3]
    return {"job": job, "position_bytes": position, "header": header, "g92": g92}


def read_prologue(text):
    """What a resurrect-prologue.g does, by what it contains: the modes it speaks of and the commands it runs."""
    live = _live(text)
    words = set(ln.split()[0] for ln in live)
    body = chr(10).join(live)
    return {"laser": '"Laser"' in body, "cnc": '"CNC"' in body, "other_modes": any(ln == "else" for ln in live),
            "stops_tool": "M5" in words, "air_off": any(ln.startswith("M42 P7 S0") for ln in live), "asks": "M291" in words and "K{" in body,
            "cancels": "M0" in words, "rehomes": "G28" in words, "waits_heat": "M116" in words}


RESUME_MODES = ("Laser", "CNC", "FFF")
ACK_KEYS = ("piece", "tool", "area")   # laser / CNC: the part is where it was, the tool is the right one, the area is clear


def mode_of(om):
    return str(((om or {}).get("state") or {}).get("machineMode") or "")


def resume_checks(om, view, exists):
    """What has to be true before the job can be resumed, one row each {id, ok, block}: a row with block false only informs. The page shows them
    all at once and runs them again every time it reads; nothing here moves the machine."""
    mode = mode_of(om)
    status = str(((om or {}).get("state") or {}).get("status") or "")
    res, m = view["resurrect"], view.get("m911") or {}
    volts, restore = view["volts_now"], m.get("r")
    rows = [
        ("resurrect", bool(res["exists"] and res["job"] and res["position_bytes"] is not None), True),     # a file that says what job and where
        ("job_file", bool(res["job"] and exists(res["job"])), True),                                       # and the job file is still on the card
        ("idle", status == "idle", True),                                                                  # not running, not paused, not halted
        ("mode", mode in RESUME_MODES, True),
        ("supply", volts is not None and restore is not None and volts >= restore, True),                  # the supply is back above the restore voltage
        ("prologue", bool(view["prologue"]["exists"]), mode in ("Laser", "CNC")),                          # without it laser / CNC resume without asking
    ]
    checks = [{"id": i, "ok": ok, "block": block} for i, ok, block in rows]
    return {"checks": checks, "can_resume": all(c["ok"] or not c["block"] for c in checks), "mode": mode, "needs_ack": mode in ("Laser", "CNC")}


def power_view(om, read, exists=None):
    cfg = read(CONFIG)
    res, pro = read(RESURRECT), read(PROLOGUE)
    rtext, rcut = _clip(res)
    ptext, pcut = _clip(pro)
    r_info = read_resurrect(res) if res is not None else {"job": None, "position_bytes": None, "header": [], "g92": {}}
    view = {"config_read": cfg is not None, "m911": read_m911(cfg) if cfg is not None else None, "volts_now": _volts(om),
            "resurrect": dict({"exists": res is not None, "bytes": len(res.encode("utf-8", "replace")) if res is not None else 0,
                               "text": rtext, "truncated": rcut}, **r_info),
            "prologue": {"exists": pro is not None, "bytes": len(pro.encode("utf-8", "replace")) if pro is not None else 0,
                         "text": ptext, "truncated": pcut, "summary": read_prologue(pro) if pro is not None else None,
                         "is_standard": pro is not None and _live(pro) == _live(PROLOGUE_TEMPLATE)}}
    view["resume"] = resume_checks(om, view, exists or (lambda p: read(p) is not None))
    return view


def _exists(path):
    import os
    import sd_paths
    try:
        return os.path.isfile(sd_paths.sd(path))
    except Exception:  # noqa: BLE001
        return False


def _power_op(args, ctx):
    import machine_ops as mo
    return power_view(mo.model(), mo.read_sd, _exists)


def resume_refusal(res, ack):
    """The code that stops a resume ("" = it can go): the first blocking check that fails, then the missing acknowledgements (laser / CNC)."""
    for c in res["checks"]:
        if c["block"] and not c["ok"]:
            return c["id"]
    if res["needs_ack"] and not all((ack or {}).get(k) is True for k in ACK_KEYS):
        return "ack_required"
    return ""


def _resume_op(args, ctx):
    """Resumes the job of resurrect.g (M916) once every check passes and, in laser / CNC, the person acknowledged the three points. The service
    does what the page cannot be trusted with: it reads the machine again, checks again and only then sends the one template of the closed list."""
    import audit
    import identity
    import machine_ops as mo
    from messages import M
    from workshop_api import ApiError
    om = mo.model()
    view = power_view(om, mo.read_sd, _exists)
    ack = args.get("ack") if isinstance(args.get("ack"), dict) else {}
    why = resume_refusal(view["resume"], ack)
    if why:
        raise ApiError("refused", M("machine_power_resume_refuse_" + why), reason=why)
    sent, detail = mo.apply_template(om, "resume_print")   # the one place that sends a template of the closed list (never raises)
    if not sent:
        raise ApiError("failed", M("machine_power_resume_not_sent"), reason=detail.split(":")[0] or "not_sent")
    audit.event("machine.power.resume", {"job": view["resurrect"]["job"], "mode": view["resume"]["mode"], "ack": {k: ack.get(k) is True for k in ACK_KEYS}}, identity.actor(ctx))
    return {"sent": True, "mode": view["resume"]["mode"], "job": view["resurrect"]["job"]}


def ops():
    return [Op("machine.power.get", _power_op, READ, {},
               "What the machine does when the supply drops: the M911 line of the configuration (cut voltage S, restore voltage R, commands P), "
               "whether resurrect.g (left by a job that was running) and resurrect-prologue.g exist, and the supply voltage now. "
               "Changing S and R is machine.config.plan config.m911 (administrator). It also says whether the interrupted job can be resumed "
               "(resume.checks) and what the person has to acknowledge (resume.needs_ack).", log=False),
            Op("machine.power.resume", _resume_op, WRITE, {"ack": Arg("obj", desc="Laser / CNC: {piece, tool, area} all true (the part is where it was, the tool is the right one, the area is clear).")},
               "Resumes the job left by a power cut (M916: the prologue runs first, in laser / CNC it asks again on the machine). The service checks again "
               "that the machine is idle, the supply is back, the job file is on the card and the prologue exists; it sends nothing otherwise.")]
