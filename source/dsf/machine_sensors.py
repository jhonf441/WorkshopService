"""The temperature sensors a bed zone can have (RepRapFirmware 3.x `M308`), for the plan config.bed_heaters (machine_beds.py).

One table, `PRESETS`: preset -> the kind of pin it reads (the capability of the board pin: `temp` = a thermistor input temp0..temp3 with its pull-up resistor,
`spi` = the chip select of an SPI temperature chip (spi.cs0..), `adc` = any pin that can read a voltage). `sensor_text` builds the `Y"..."` part of the M308 line
with the parameters of the type, checked. Every type and parameter here comes from the official Duet3D documentation (GCode dictionary, M308, and the pages
"Connecting thermistors and PT1000", "Connecting PT100", "Connecting thermocouples") and from the RRF 3.6 sources (src/Heating/Sensors); nothing is guessed:

    thermistor           Y"thermistor" T<ohm at 25 C> B<beta> [C<Steinhart-Hart C>]
    pt1000               Y"pt1000"
    thermocouple         Y"thermocouple-max31855"                 (type K only: the chip decides)
    tc-max31856          Y"thermocouple-max31856" K"<letter>" F<50|60>     (letters B E J K N R S T; K is the firmware default)
    pt100                Y"rtd-max31865" R<ohm> W<2|3|4> F<50|60>          (MAX31865 daughterboard; reference resistor default 400)
    linear-analog        Y"linear-analog" F<0|1> B<value at 0 V> C<value at full scale>

Not offered, and why: a PT1000 on the MAX31865 (RRF reads that chip with the PT100 table only: the resistance is kept in a 16 bit number of hundredths of ohm,
so a PT1000 would overflow; a PT1000 goes on a temperature input), DS18B20 and LM75 (RRF 3.6 has no such sensor type and the documentation does not list them),
DHT / BME / drivers / MCU temperature (not bed sensors), current-loop (needs an MCP3204 on SPI) and the ADS131 daughterboard.
Pure: nothing here talks to the board (tests: test_machine_sensors.py).
"""
import re

import machine_patch as pt

# preset -> the capability the pin needs (see machine_tool.BOARD_PINS)
PRESETS = {"thermistor": "temp", "pt1000": "temp", "thermocouple": "spi", "tc-max31856": "spi", "pt100": "spi", "linear-analog": "adc"}
# the keys each preset accepts besides preset and pin: anything else is refused (a field that would be silently ignored is a wrong line)
EXTRA_KEYS = {"thermistor": ("t", "b", "c"), "pt1000": (), "thermocouple": (), "tc-max31856": ("type", "mains"),
              "pt100": ("wires", "mains", "ref"), "linear-analog": ("low", "high", "filtered")}
THERMISTOR_T = (1000, 10000000)
THERMISTOR_B = (1000, 10000)
# Steinhart-Hart C: the Duet documentation gives 7.06e-8 (E3D) and says default 0; this bound is ours (a wrong exponent would be a wrong temperature)
THERMISTOR_C = (-1e-6, 1e-6)
TC_TYPES = "BEJKNRST"
MAINS = (50, 60)
WIRES = (2, 3, 4)
# the reference resistor of the MAX31865 board is 400 ohm by default (430 on other boards); the firmware keeps the measured resistance in an uint16 of
# hundredths of ohm, so the reference cannot be above 655 ohm: the bound is ours (100 to 600)
RTD_REF = (100, 600)
# linear-analog: what the sensor reads at 0 V and at full scale (no default: a made up range reads a wrong temperature)
ANALOG_RANGE = (-273, 1500)
TEMP_PIN = re.compile(r"^!?\^?temp\d+$")


class SensorError(ValueError):
    """code = a code of the contract, field = the field of the sensor spec it is about (the caller adds the prefix)."""

    def __init__(self, code, field=""):
        super().__init__(code)
        self.code, self.field = code, field


def _num(v, lo, hi, code, field, whole=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or (whole and int(v) != v):
        raise SensorError(code, field)
    return v


def _sci(v):
    """A small number as G-code text without losing it (num_text keeps 3 places and would turn 7.06e-8 into 0): 7.06e-8."""
    return re.sub(r"e([+-])0*(\d)", r"e\1\2", "%.6g" % v)


def need(preset):
    """The capability the pin of this sensor type needs; thermistor-like when the type is unknown."""
    return PRESETS.get(preset, "temp")


def _thermistor(item):
    if all(item.get(k) is None for k in ("t", "b", "c")):
        return 'Y"thermistor" T100000 B3950'
    t = _num(item.get("t", 100000), THERMISTOR_T[0], THERMISTOR_T[1], "values", "t")
    b = _num(item.get("b", 3950), THERMISTOR_B[0], THERMISTOR_B[1], "values", "b")
    text = 'Y"thermistor" T%s B%s' % (pt.num_text(t), pt.num_text(b))
    if item.get("c") is not None:
        text += " C%s" % _sci(_num(item["c"], THERMISTOR_C[0], THERMISTOR_C[1], "therm_c", "c"))
    return text


def _mains(item):
    if item.get("mains") is None:
        return ""
    if isinstance(item["mains"], bool) or item["mains"] not in MAINS:
        raise SensorError("mains", "mains")
    return " F%d" % item["mains"]


def _max31856(item):
    text = 'Y"thermocouple-max31856"'
    kind = item.get("type")
    if kind is not None:
        if not isinstance(kind, str) or len(kind) != 1 or kind not in TC_TYPES:
            raise SensorError("tc_type", "type")
        text += ' K"%s"' % kind
    return text + _mains(item)


def _max31865(item):
    text = 'Y"rtd-max31865"'
    if item.get("ref") is not None:
        text += " R%s" % pt.num_text(_num(item["ref"], RTD_REF[0], RTD_REF[1], "rtd_ref", "ref"))
    if item.get("wires") is not None:
        if isinstance(item["wires"], bool) or item["wires"] not in WIRES:
            raise SensorError("wires", "wires")
        text += " W%d" % item["wires"]
    return text + _mains(item)


def _linear(item, pin):
    low = _num(item.get("low"), ANALOG_RANGE[0], ANALOG_RANGE[1], "analog_range", "low")
    high = _num(item.get("high"), ANALOG_RANGE[0], ANALOG_RANGE[1], "analog_range", "high")
    if low >= high:
        raise SensorError("analog_range", "high")
    on_temp = TEMP_PIN.match(str(pin or "").strip()) is not None
    filtered = item.get("filtered", on_temp)
    if not isinstance(filtered, bool):
        raise SensorError("values", "filtered")
    if filtered and not on_temp:
        raise SensorError("analog_filter", "filtered")  # the firmware: F1 only on a port made for thermistors
    return 'Y"linear-analog" F%d B%s C%s' % (1 if filtered else 0, pt.num_text(low), pt.num_text(high))


def sensor_text(preset, item, pin=None):
    """The `Y"..." ...` part of the M308 line of a preset, with its checked parameters. Raises SensorError (code, field relative to the sensor)."""
    if preset not in PRESETS:
        raise SensorError("values", "preset")
    for key in item:
        if key not in ("preset", "pin") and key not in EXTRA_KEYS[preset]:
            raise SensorError("values", key)
    if preset == "thermistor":
        return _thermistor(item)
    if preset == "pt1000":
        return 'Y"pt1000"'
    if preset == "thermocouple":
        return 'Y"thermocouple-max31855"'
    if preset == "tc-max31856":
        return _max31856(item)
    if preset == "pt100":
        return _max31865(item)
    return _linear(item, pin)
