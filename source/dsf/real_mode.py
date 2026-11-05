"""The mode the machine is really in.

state.machineMode is what RepRapFirmware applies (M451 FFF, M452 Laser, M453 CNC). global.selectedMode is a variable
that the select*.g macros of the SD write before they run the M45x, so when the M45x fails (or the macro stops half way)
the variable says one mode and the machine is in another. The machine is the truth: global.selectedMode is used only
when the model has no known state.machineMode (a model read without the state tree, or a machine that does not have
the workshop variable the other way round)."""

MODES = ("FFF", "Laser", "CNC")


def pick(selected, machine):
    """The real mode from the two values of the object model (either can be None)."""
    if machine in MODES:
        return machine
    if selected in MODES:
        return selected
    return selected or machine or None


def of_model(om):
    """The same, from an object model dict ({"state": {...}, "global": {...}})."""
    om = om if isinstance(om, dict) else {}
    g = om.get("global") if isinstance(om.get("global"), dict) else {}
    st = om.get("state") if isinstance(om.get("state"), dict) else {}
    return pick(g.get("selectedMode"), st.get("machineMode"))
