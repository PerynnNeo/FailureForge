"""Engineer-specified steady rod boundary changes and evidence for scenario discovery."""
import re
from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AMBIENT = "right_ambient_temperature_k"
FILM = "right_film_coefficient_w_m2k"
FIELDS = {
    AMBIENT: ("thermal.end.ambient", "Right-end ambient temperature", "K"),
    FILM: ("thermal.end.film", "Right-end film coefficient", "W/(m²·K)"),
}
VERSION = "thermal-boundaries-1"
MODEL = "Engineer-specified thermal boundaries"


class ThermalChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=True)
    ambient_value: float | None = None
    ambient_unit: Literal["K", "°C"] = "K"
    end_film_w_m2k: float | None = Field(default=None, ge=0, le=1e7)
    fan_rpm: float | None = Field(default=None, ge=0)
    fan_calibration: str | None = Field(default=None, min_length=1, max_length=400)

    @property
    def temperature_k(self):
        if self.ambient_value is None:
            return None
        return self.ambient_value + (273.15 if self.ambient_unit == "°C" else 0)

    @model_validator(mode="after")
    def valid_temperature(self):
        if self.temperature_k is not None and not 0 < self.temperature_k <= 1e5:
            raise ValueError("Enter an absolute ambient temperature above 0 K and at most 100,000 K.")
        return self


def thermal_intent(task):
    return bool(_FAN.search(task) or re.search(r"\b(ambient|enclosure|cooling|convection|end[- ]face|film coefficient)\b", task, re.I))


_QUANTITY = r"(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?P<unit>°\s*[CF]|celsius|fahrenheit|kelvin|[CKF])\b"
_SUBJECT = r"\b(?:enclosure(?:\s+(?:air|temperature))?|(?:right[- ]end\s+)?ambient(?:\s+(?:fluid|air|temperature))?)\s+"
_ABSOLUTE = r"(?:(?:warms?|heats?|rises?|increases?|drops?|changes?)\s+to|reaches?|(?:will be|is)(?:\s+at)?|at)\s+"
_DELTA = r"(?P<direction>warms?|heats?|rises?|increases?|cools?|drops?|decreases?)\s+by\s+"
_FAN = re.compile(r"\bfans?\b|(?<![a-z])rpm\b|\brevolutions? per minute\b", re.I)
_SPEED = re.compile(r"(?<![\w.,-])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:rpm|revolutions? per minute)\b", re.I)
_TRANSIENT = re.compile(r"\b(transient|ramp|pulsed?|intermittent|warm[- ]?up|duty cycle)\b|\b(?:in|for|after)\s+\d+\s*(?:s|seconds?|minutes?|hours?|ms)\b", re.I)


def _described_temperature(task, inputs):
    """Bind one unqualified temperature to its physical subject and distinguish an increment from a set point."""
    if len(re.findall(_QUANTITY, task, re.I)) != 1:
        return None
    candidate = re.search(_SUBJECT + "(?:" + _ABSOLUTE + "|" + _DELTA + ")" + _QUANTITY, task, re.I)
    if not candidate:
        return None
    tail = task[candidate.end():]
    comparison = re.match(r"\s+(warmer|hotter|cooler|colder)\b", tail, re.I)
    if comparison:
        if not re.search(r"\b(is|will be)\s+[+-]?(?:\d|\.)", candidate.group(), re.I):
            return None
        tail = tail[comparison.end():]
        if comparison_to := re.match(r"\s+than\s+", tail, re.I):
            origin = re.match(r"(?:the\s+)?(?:selected\s+)?(?:baseline|reference)\b", tail[comparison_to.end():], re.I)
            if not origin:
                return None
            tail = tail[comparison_to.end() + origin.end():]
    if re.match(r"\s*(?:[-–—±~]|(?:or|to|through|above|below|higher|lower|more|less|per|relative|over|within|than)\b|/)", tail, re.I):
        return None
    if _TRANSIENT.search(task):
        return None
    if re.search(r"\b(?:not|never|between|uncertain|unknown|roughly|approximately|permitted|maximum|minimum|threshold|limit|allowable)\b", task, re.I):
        return None
    magnitude = float(candidate["value"])
    unit = candidate["unit"].lower().replace("°", "").strip()
    if unit not in ("k", "kelvin", "c", "celsius"):
        return None
    is_celsius = unit in ("c", "celsius")
    direction = comparison[1] if comparison else candidate["direction"]
    if direction:
        if magnitude < 0 or AMBIENT not in inputs:
            return None
        increase = not direction.lower().startswith(("cool", "cold", "drop", "decrease"))
        target = inputs[AMBIENT] + (magnitude if increase else -magnitude)
    else:
        target = magnitude + (273.15 if is_celsius else 0)
    if not 0 < target <= 1e5:
        return None
    return target, task[candidate.start():candidate.end() + (comparison.end() if comparison else 0)], bool(direction)


def boundary_facts(change, task, inputs):
    """Only explicit, unit-bearing controls reach the solver. Text can raise questions."""
    facts, targets, questions = [], {}, []
    described = _described_temperature(task, inputs)
    if change.ambient_value is not None:
        facts.append((AMBIENT, "Requested external fluid temperature", change.ambient_value, change.ambient_unit))
        targets[AMBIENT] = change.temperature_k
    elif described:
        target, phrase, relative = described
        description = "Ambient derived from the signed change to the reference" if relative else "Requested absolute ambient"
        facts.append((AMBIENT, description, target, "K"))
        facts.append(("ambient_description", "Source words for the boundary change", phrase, ""))
        targets[AMBIENT] = target
    if change.end_film_w_m2k is not None:
        facts.append((FILM, "Requested end-face film coefficient", change.end_film_w_m2k, FIELDS[FILM][2]))
    if change.fan_rpm is not None:
        facts.append(("fan_rpm", "Requested fan speed", change.fan_rpm, "RPM"))
    if change.fan_calibration:
        facts.append(("fan_calibration", "Source for the installed fan calibration", change.fan_calibration, ""))
    fan = change.fan_rpm is not None or bool(change.fan_calibration) or bool(_FAN.search(task))
    if _TRANSIENT.search(task):
        questions.append("When does the temperature change, and how quickly must the component respond? This solver reports equilibrium. A time-to-temperature test needs heat capacity, density, initial conditions and a transient solver.")
    stated_speeds = [float(v.replace(",", "")) for v in _SPEED.findall(task)]
    if fan and (change.fan_rpm is None or change.end_film_w_m2k is None or not change.fan_calibration):
        questions.append("What measured or documented relationship gives the right-end film coefficient (W/(m²·K)) at the requested fan speed in this installation? Enter the RPM, corresponding coefficient and calibration source.")
    elif fan and stated_speeds and change.fan_rpm not in stated_speeds:
        questions.append("The fan speed entered for this calibration differs from the speed in the description. Which operating point should the coefficient represent? Update the description or the RPM.")
    elif change.end_film_w_m2k is not None:
        targets[FILM] = change.end_film_w_m2k
    if inputs.get("right_temperature_k") is not None:
        questions.append("This reference fixes the right surface temperature. Can you supply a convective reference with the measured external fluid temperature and end-face film coefficient?")
        targets.clear()
    else:
        if AMBIENT not in targets and re.search(r"\b(ambient|enclosure|warmer|hotter|colder|cooler)\b", task, re.I):
            questions.append("What absolute external fluid temperature (K or °C) should replace the reference ambient at the right end?")
        if not fan and change.end_film_w_m2k is None and re.search(r"\b(film coefficient|end cooling)\b", task, re.I):
            questions.append("What end-face film coefficient (W/(m²·K)) represents the changed cooling condition?")
        if change.ambient_value is not None and described and not isclose(change.temperature_k, described[0], abs_tol=1e-9, rel_tol=0):
            questions.append("The ambient temperature entered differs from the temperature in the description. Which operating condition should be tested? Update one of the two values.")
            targets.pop(AMBIENT)
        for field, target in list(targets.items()):
            if target == inputs[field]:
                questions.append(f"The proposed {FIELDS[field][1].lower()} is already the reference value. What different operating value should be tested?")
                del targets[field]
            elif field == AMBIENT and inputs[FILM] == 0:
                questions.append("The right end is insulated (h = 0), so changing its ambient temperature has no effect. What positive reference film coefficient represents this installation?")
                del targets[field]
    if not questions and not targets:
        questions.append("What absolute temperature does the fluid at the right end reach (K or °C), or what end-face film coefficient (W/(m²·K)) should change?")
    return facts, targets, questions
