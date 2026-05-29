"""
CCRS → SWITRS Format Converter
================================
Converts California Crash Reporting System (CCRS) data
into the SWITRS compatible format.

CCRS tables:  Crash, Party, InjuredWitnessPassenger (IWP)
SWITRS tables: crash, party, victim

Usage:
    python ccrs_switrs_converter.py \
        --crash     ccrs_crash.csv \
        --party     ccrs_party.csv \
        --iwp       ccrs_iwp.csv \
        --vc-codes  vc_codes_table.csv \
        --out-dir   ./output

    Produces:
        output/crash.csv
        output/party.csv
        output/victim.csv
        output/unmapped_ccrs_fields.csv   (CCRS-only fields preserved for reference)

    --vc-codes is optional but strongly recommended. Without it, pcf_viol_category,
    pcf_violation, pcf_viol_subsection, oaf_viol_cat, oaf_viol_section, and
    oaf_viol_suffix will all be blank.

    Key CCRS → SWITRS field notes:
      Crash:  MilepostDirection → side_of_hwy
              MilepostDistance  → postmile
              collision_time: if CrashTime=0 and CrashTimeDescription=2500, uses 2500
      Party:  SobrietyDrugPhysicalCode1 → party_sobriety
              SobrietyDrugPhysicalCode2 → party_drug_physical
              AirbagCode                → party_safety_equip_1
              SafetyEquipmentCode       → party_safety_equip_2
              StatedAge blank           → 998
              alcohol_involved derived from SobrietyDrugPhysicalCode1 in (B,C,D)
              stwd_vehtype_at_fault derived from chp_veh_type_towing/towed logic
      Victim: PartyNumber (IWP)     → party_number
              SeatPosition (mapped) → victim_seating_position
              AirbagCode            → victim_safety_equip_1
              SafetyEquipmentCode   → victim_safety_equip_2
              Ejected (mapped)      → victim_ejected
"""

import argparse
import csv
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# FIELD MAPPING REFERENCE
# ---------------------------------------------------------------------------
#
# Format for direct mappings:  ccrs_field -> switrs_field
# Format for derived fields:   described inline with the compute_* helpers
#
# KEY:
#   [DIRECT]   – value copied as-is (possibly with code translation)
#   [DERIVED]  – computed from one or more CCRS fields
#   [PLACEHOLDER] – SWITRS field filled with a constant / empty because
#                   CCRS has no equivalent source
#   [NEW-CCRS] – field exists only in CCRS; written to unmapped output
#
# ── CRASH TABLE ──────────────────────────────────────────────────
#
#  SWITRS crash field          CCRS source field(s)            Notes
#  ─────────────────────────────  ──────────────────────────────  ──────────
#  case_id                        CollisionId                     [DIRECT] integer→string
#  accident_year                  CrashDateTime                   [DERIVED] extract year
#  proc_date                      ModifiedDate                    [DIRECT] reformat to YYYYMMDD
#  juris                          NCICCode                        [DIRECT]
#  collision_date                 CrashDateTime                   [DERIVED] extract date YYYYMMDD
#  collision_time                 CollisionTime                   [DIRECT] zero-pad to 4 chars
#  officer_id                     (not in CCRS)                   [PLACEHOLDER] blank
#  reporting_district             ReportingDistrictCode           [DIRECT]
#  day_of_week                    DayOfWeek                       [DERIVED] name→1-7 code
#  chp_shift                      (not in CCRS)                   [PLACEHOLDER] blank
#  population                     (deprecated in SWITRS)          [PLACEHOLDER] blank
#  cnty_city_loc                  CountyCode + CityCode           [DERIVED] combine
#  special_cond                   SpecialCondition                [DERIVED] map text values
#  beat_type / chp_beat_type      Beat                            [PLACEHOLDER] not directly mappable
#  beat_number                    Beat                            [DIRECT]
#  primary_rd                     PrimaryRd                       [DIRECT]
#  secondary_rd                   SecondaryRd                     [DIRECT]
#  distance                       SecondaryDistance               [DIRECT]
#  direction                      SecondaryDirection              [DIRECT]
#  intersection                   PrimaryRd+SecondaryRd+Distance  [DERIVED] blank distance → Y
#  weather_1                      Weather1                        [DIRECT] extract code letter
#  weather_2                      Weather2                        [DIRECT] extract code letter
#  state_hwy_ind                  IsHighwayRelated                [DERIVED] True→Y, False→N
#  tow_away                       IsTowAway                       [DERIVED] True→Y, False→N
#  collision_severity             InjuredWitnessPassenger table   [DERIVED] worst ExtentOfInjury
#  number_killed                  NumberKilled                    [DIRECT]
#  number_injured                 NumberInjured                   [DIRECT]
#  party_count                    Party table                     [DERIVED] count distinct PartyNumber per CollisionId
#  primary_coll_factor            PrimaryCollisionFactorCode      [DIRECT]
#  pcf_code_of_viol               (not in CCRS)                   [PLACEHOLDER] blank
#  pcf_viol_category              (not in CCRS)                   [PLACEHOLDER] blank
#  pcf_violation                  (not in CCRS)                   [PLACEHOLDER] blank
#  pcf_viol_subsection            (not in CCRS)                   [PLACEHOLDER] blank
#  hit_and_run                    HitRun                          [DIRECT] F/M/blank → F/M/N
#  type_of_collision              CollisionTypeCode               [DIRECT]
#  mviw                           MotorVehicleInvolvedWithCode     [DIRECT]
#  ped_action                     PedestrianActionCode            [DIRECT]
#  road_surface                   RoadwaySurfaceCode              [DIRECT] extract letter
#  road_cond_1                    RoadCondition1                  [DIRECT] extract letter
#  road_cond_2                    RoadCondition2                  [DIRECT] extract letter
#  lighting                       LightingCode                    [DIRECT]
#  control_device                 TrafficControlDeviceCode        [DIRECT] extract letter
#  pedestrian_accident            Party table                     [DERIVED] any party_type==PEDESTRIAN
#  bicycle_accident               Party table                     [DERIVED] any party_type==BICYCLIST
#  motorcycle_accident            Party table                     [DERIVED] stwd_vehicle_type==M (approximated via V1TypeDesc)
#  truck_accident                 Party table                     [DERIVED] stwd_vehicle_type==T (approximated via V1TypeDesc)
#  not_private_property           SpecialCondition                [DERIVED] not 'Private Property'
#  alcohol_involved               Party table                     [DERIVED] any SobrietyDrugPhysical B/C/D
#  stwd_vehtype_at_fault          Party table                     [DERIVED] Vehicle1TypeId of at-fault party
#  chp_veh_type_at_fault          Party table (V1TypeId)          [DERIVED]
#  count_severe_inj               IWP table                       [DERIVED] SUSPECTED SERIOUS INJURY
#  count_visible_inj              IWP table                       [DERIVED] SUSPECTED MINOR INJURY
#  count_complaint_pain           IWP table                       [DERIVED] POSSIBLE INJURY
#  count_ped_killed               IWP table                       [DERIVED] FATAL + Pedestrian
#  count_ped_injured              IWP table                       [DERIVED] injured + Pedestrian
#  count_bicyclist_killed         IWP table                       [DERIVED] FATAL + Bicyclist
#  count_bicyclist_injured        IWP table                       [DERIVED] injured + Bicyclist
#  count_mc_killed                Party table (vehicle type)      [DERIVED] motorcycle + killed
#  count_mc_injured               Party table (vehicle type)      [DERIVED] motorcycle + injured
#  latitude                       Latitude                        [DIRECT]
#  longitude                      Longitude                       [DIRECT]
#  local_report_number            ReportNumber                    [DIRECT]
#
# ── PARTY TABLE ─────────────────────────────────────────────────────────────
#
#  SWITRS party field             CCRS source field(s)            Notes
#  ─────────────────────────────  ──────────────────────────────  ──────────
#  case_id                        CollisionId                     [DIRECT]
#  party_number                   PartyNumber                     [DIRECT]
#  party_type                     PartyType                       [DERIVED] text→1-6 code
#  at_fault                       IsAtFault                       [DERIVED] True→Y, False→N
#  party_sex                      GenderCode                      [DIRECT]
#  party_age                      StatedAge                       [DIRECT]
#  party_sobriety                 SobrietyDrugPhysicalCode        [DIRECT] (A-D,G,H)
#  party_drug_physical            SobrietyDrugPhysicalCode        [DERIVED] E/F/H/I subset only
#  dir_of_travel                  DirectionOfTravel               [DIRECT]
#  party_safety_equip_1           SafetyEquipmentCode             [DIRECT]
#  party_safety_equip_2           (not split in CCRS)             [PLACEHOLDER] blank
#  finan_respons                  (not in CCRS)                   [PLACEHOLDER] blank
#  sp_info_1                      SpecialInformation (A)          [DERIVED] whole-token match for "A"
#  sp_info_2                      SpecialInformation (B/C/D/1-4)  [DERIVED] whole-token match for cell-phone code
#  sp_info_3                      SpecialInformation (E)          [DERIVED] whole-token match for "E" (was buggy; historically unreliable)
#  oaf_violation_code             (not in CCRS)                   [PLACEHOLDER] blank
#  oaf_viol_cat                   (not in CCRS)                   [PLACEHOLDER] blank
#  oaf_viol_section               (not in CCRS)                   [PLACEHOLDER] blank
#  oaf_viol_suffix                (not in CCRS)                   [PLACEHOLDER] blank
#  oaf_1                          OtherAssociateFactor (first)    [DERIVED] split on /
#  oaf_2                          OtherAssociateFactor (second)   [DERIVED] split on /
#  party_number_killed            (from IWP table)                [DERIVED] count per party
#  party_number_injured           (from IWP table)                [DERIVED] count per party
#  move_pre_acc                   MovementPrecCollCode            [DIRECT]
#  vehicle_year                   Vehicle1Year                    [DIRECT]
#  vehicle_make                   Vehicle1Make                    [DIRECT]
#  stwd_vehicle_type              Vehicle1TypeId                  [DERIVED] map to stwd codes
#  chp_veh_type_towing            Vehicle1TypeId                  [DIRECT]
#  chp_veh_type_towed             Vehicle2TypeId                  [DIRECT]
#  race                           RaceCode                        [DIRECT]
#  inattention                    Inattention                     [DERIVED] text→code
#  special_info_f                 (not in CCRS)                   [PLACEHOLDER] blank
#  special_info_g                 (not in CCRS)                   [PLACEHOLDER] blank
#  local_report_number            (join from Crash.ReportNumber)  [DERIVED]
#
# ── VICTIM TABLE ────────────────────────────────────────────────────────────
#
#  SWITRS victim field            CCRS source field(s)            Notes
#  ─────────────────────────────  ──────────────────────────────  ──────────
#  case_id                        CollisionId                     [DIRECT]
#  party_number                   (IWP doesn't store party#)      [PLACEHOLDER] blank / infer from InjuredPersonType
#  victim_role                    InjuredPersonType               [DERIVED] text→1-6 code
#  victim_sex                     Gender                          [DIRECT]
#  victim_age                     StatedAge                       [DIRECT]
#  victim_degree_of_injury        ExtentOfInjury                  [DERIVED] text→1-7 code
#  victim_seating_position        SeatPosition                    [DIRECT]
#  victim_safety_equip_1          AirBagCode + SafetyEquipmentCode[DIRECT]
#  victim_safety_equip_2          (single field in CCRS)          [PLACEHOLDER] blank
#  victim_ejected                 Ejected                         [DIRECT]
#  local_report_number            (join from Crash.ReportNumber)  [DERIVED]
#
# ── CCRS-ONLY FIELDS (no SWITRS equivalent) ─────────────────────────────────
# Crash:   ReportVersion, IsPreliminary, DispatchNotified, HasPhotographs,
#           IsDeleted, JudicialDistrict, PreparedDate, PrimaryCollisionFactorIsCited,
#           PrimaryCollisionPartyNumber, ReviewedDate, SecondaryUnitOfMeasure,
#           CreatedDate, IsCountyRoad, IsFreeway, CHP555Version,
#           NotificationDate, HasDigitalMediaFiles, EvidenceNumber,
#           IsLocationReferToNarrative, IsAOIOneSameAsLocation
# Party:   IsOnDutyEmergencyVehicle, IsHitAndRun, AirbagCode, StreetOrHighwayName,
#           SpeedLimit, DriverLicenseClass, DriverLicenseStateCode,
#           Vehicle1Color, Lane, ThruLane, TotalLane, IsDREConducted
# IWP:     Race, IsWitnessOnly, IsPassengerOnly, AirbagCode
# ---------------------------------------------------------------------------


# ── Code translation tables ──────────────────────────────────────────────────

DAY_OF_WEEK = {
    "Monday": "1", "Tuesday": "2", "Wednesday": "3",
    "Thursday": "4", "Friday": "5", "Saturday": "6", "Sunday": "7",
}

# Keys are nospace()+upper() so "Parked Vehicle" and "ParkedVehicle" both match
PARTY_TYPE_MAP = {
    "DRIVER":        "1",
    "PEDESTRIAN":    "2",
    "PARKEDVEHICLE": "3",
    "BICYCLIST":     "4",
    "OTHER":         "5",
    "OPERATOR":      "6",
}

# Keys are nospace()+upper() to handle both "OtherOperator" and "Other Operator"
VICTIM_ROLE_MAP = {
    "DRIVER":      "1",
    "PASSENGER":   "2",
    "PEDESTRIAN":  "3",
    "BICYCLIST":   "4",
    "OTHER":       "5",
    "OPERATOR":    "6",
}


# CCRS ExtentOfInjuryCode (code field) → SWITRS victim_degree_of_injury
# Values observed: Fatal, SevereInactive, OtherVisibleInactive,
#   ComplaintOfPainInactive, SuspectSerious, SuspectMinor, PossibleInjury
INJURY_CODE_MAP = {
    "FATAL":                    "1",
    "SEVEREINACTIVE":           "2",
    "OTHERVISIBLEINACTIVE":     "3",
    "COMPLAINTOFPAININACTIVE":  "4",
    "SUSPECTSERIOUS":           "5",
    "SUSPECTMINOR":             "6",
    "POSSIBLEINJURY":           "7",
    "NOINJURY":                 "0",
    "":                         "0",
}

# Which ExtentOfInjuryCode values count as INJURED (vs. killed vs. none)
INJURY_CODE_INJURED = {
    "POSSIBLEINJURY", "SUSPECTMINOR", "SUSPECTSERIOUS",
    "COMPLAINTOFPAININACTIVE", "OTHERVISIBLEINACTIVE", "SEVEREINACTIVE",
}
INJURY_CODE_KILLED = {"FATAL"}

# CCRS Ejected field values → SWITRS victim_ejected code
EJECTED_MAP = {
    "NOTEJECTED":       "0",
    "NOT EJECTED":      "0",
    "0":                "0",
    "FULLYEJECTED":     "1",
    "FULLY EJECTED":    "1",
    "1":                "1",
    "PARTIALLYEJECTED": "2",
    "PARTIALLY EJECTED":"2",
    "2":                "2",
    "UNKNOWN":          "3",
    "3":                "3",
    "":                 "-",
    "-":                "-",
}


# SeatPosition CCRS text → SWITRS victim_seating_position character
SEAT_POSITION_MAP = {
    "DRIVER":                          "1",
    "PASSENGERFRONTMIDDLE":            "2",
    "PASSENGER FRONT MIDDLE":          "2",
    "PASSENGERFRONTRIGHT":             "3",
    "PASSENGER FRONT RIGHT":           "3",
    "PASSENGERMIDDLELEFT":             "4",
    "PASSENGER MIDDLE LEFT":           "4",
    "PASSENGERMIDDLEMIDDLE":           "5",
    "PASSENGER MIDDLE MIDDLE":         "5",
    "PASSENGERMIDDLERIGHT":            "6",
    "PASSENGER MIDDLE RIGHT":          "6",
    "PASSENGERREARLEFT":               "A",
    "PASSENGER REAR LEFT":             "A",
    "PASSENGERREARMIDDLE":             "B",
    "PASSENGER REAR MIDDLE":           "B",
    "PASSENGERREARRIGHT":              "C",
    "PASSENGER REAR RIGHT":            "C",
    "REAROCCTRKORVANORSTATIONWAGON":   "8",
    "REAROCCTRKORVANORSTATIONWAGON":   "8",
    "REAR OCC TRK OR VAN OR STATION WAGON": "8",
    "UNKNOWN":                         "9",
    "OTHER":                           "0",   # may be overridden by SeatPositionOther
    "":                                "-",
}




def _safe_count(value):
    """
    Convert a CCRS count field (NumberKilled, NumberInjured) to a clean integer string.
    - Blank / None → "0"  (witness-only crashes have no party and store blank)
    - Negative values (CCRS uses -1 as a sentinel for unknown) → "0"
    - Valid integers → as-is string
    """
    v = (value or "").strip()
    if not v:
        return "0"
    try:
        n = int(v)
        return str(max(n, 0))
    except ValueError:
        return "0"

def _at_fault_code(value):
    """
    Convert CCRS IsAtFault to SWITRS at_fault code.
    True/1/Yes  → Y (at fault)
    False/0/No  → N (not at fault)
    Blank/other → N (CCRS blank means not at fault)
    """
    v = normalize(value)
    if v in ("TRUE", "1", "YES"):
        return "Y"
    return "N"


def _pad_chp_type(value):
    """
    Ensure CHP vehicle type codes are zero-padded to 2 digits.
    Single digit strings get a leading zero: "1" → "01", "9" → "09".
    Already 2+ chars or blank/dash passed through unchanged.
    """
    v = (value or "").strip()
    if v and v not in ("-",) and v.isdigit() and len(v) == 1:
        return "0" + v
    return v

def stwd_vehicle_type_from_chp(chp_towing, chp_towed):
    """
    Derive SWITRS statewide_vehicle_type from CHP vehicle type codes.
    Logic per spec provided by user.
    """
    t  = (chp_towing or "").strip()
    t2 = (chp_towed  or "").strip()
    has_towed = t2 not in ("", "-", None)

    if t in ("01", "07", "08", "71", "81"):
        return "B" if has_towed else "A"
    elif t in ("02", "03"):
        return "C"
    elif t in ("22", "23", "72", "73", "82", "83"):
        return "E" if has_towed else "D"
    elif t in ("21", "24", "25", "26", "27", "55", "56",
               "75", "76", "77", "78", "79", "85", "86", "87", "88", "89"):
        return "G" if has_towed else "F"
    elif t in ("13", "14", "15", "16", "17", "18"):
        return "H"
    elif t in ("09", "10", "11", "12", "19", "20"):
        return "I"
    elif t in ("41", "43", "48", "49", "98"):
        return "J"
    elif t in ("45",):
        return "K"
    elif t in ("04",):
        return "L"
    elif t in ("06", "44", "46", "47", "50", "51", "59", "91", "93", "94", "95", "96", "97"):
        return "M"
    elif t in ("60",):
        return "N"
    elif t in ("05",):
        return "O"
    elif t in ("", "-", "99"):
        return "-"
    return "M"   # unrecognised → Other Vehicle


def seat_position_code(seat_raw, seat_other_raw=""):
    """
    Map CCRS SeatPosition text to SWITRS victim_seating_position character.
    If value is 'Other', check SeatPositionOther for a number to use instead.
    """
    v = (seat_raw or "").strip()
    vu = v.upper().replace(" ", "")
    code = SEAT_POSITION_MAP.get(v.upper(), SEAT_POSITION_MAP.get(vu, "-"))
    # If Other and SeatPositionOther has a value, use that instead of 0
    if code == "0":
        other = (seat_other_raw or "").strip()
        if other:
            return other
    return code

INJURY_SEVERITY_MAP = {
    "FATAL INJURY": "1",
    "SUSPECTED SERIOUS INJURY": "2",
    "SUSPECTED MINOR INJURY": "3",
    "POSSIBLE INJURY": "4",
    "NO INJURY": "0",
}

INATTENTION_MAP = {
    "CELL PHONE HANDHELD": "A",
    "CELL PHONE HANDSFREE": "B",
    "ELECTRONIC_EQUIPMENT": "C",
    "RADIO/CD": "D",
    "SMOKING": "E",
    "EATING": "F",
    "CHILDREN": "G",
    "ANIMALS": "H",
    "PERSONAL HYGIENE": "I",
    "READING": "J",
    "OTHER": "K",
}

# CCRS Vehicle1TypeDesc → SWITRS statewide_vehicle_type (single letter)
# Source: SWITRS_Raw_Data_Tables.xlsx "statewide_vehicle_type" sheet
VEHICLE_TYPE_MAP = {
    "PASSENGER CAR":              "A",
    "PASSENGER CAR/STATION WAGON":"A",
    "STATION WAGON":              "A",
    "PASSENGER CAR W/ TRAILER":   "B",
    "MOTORCYCLE":                 "C",
    "SCOOTER":                    "C",
    "MOTORCYCLE/SCOOTER":         "C",
    "MOPED":                      "O",
    "PICKUP OR PANEL TRUCK":      "D",
    "PICKUP":                     "D",
    "PANEL TRUCK":                "D",
    "PICKUP/PANEL TRUCK WITH TRAILER": "E",
    "PICKUP OR PANEL TRUCK WITH TRAILER": "E",
    "TRUCK":                      "F",
    "TRUCK TRACTOR":              "F",
    "TRUCK OR TRUCK TRACTOR":     "F",
    "TRUCK WITH TRAILER":         "G",
    "TRUCK/TRUCK TRACTOR WITH TRAILER": "G",
    "TRUCK TRACTOR WITH TRAILER": "G",
    "SCHOOL BUS":                 "H",
    "SCHOOLBUS":                  "H",
    "BUS":                        "I",
    "OTHER BUS":                  "I",
    "TRANSIT BUS":                "I",
    "EMERGENCY VEHICLE":          "J",
    "HIGHWAY CONST. EQUIPMENT":   "K",
    "CONSTRUCTION EQUIPMENT":     "K",
    "BICYCLE":                    "L",
    "PEDESTRIAN":                 "N",
    "OTHER VEHICLE":              "M",
    "OTHER":                      "M",
}

# These maps match the CCRS text values (no letter-dash prefix in actual data).
# extract_code_letter() still handles the legacy "A-DAYLIGHT" style if it appears.
LIGHTING_MAP = {
    "DAYLIGHT":                      "A",
    "DUSK":                          "B",
    "DAWN":                          "B",
    "DUSK-DAWN":                     "B",
    "DARK-STREET LIGHTS":            "C",
    "DARK - STREET LIGHTS":          "C",
    "DARK-NO STREET LIGHTS":         "D",
    "DARK - NO STREET LIGHTS":       "D",
    "DARK-STREET LIGHTS NOT FUNCTIONING": "E",
    "DARK - STREET LIGHTS NOT FUNCTIONING": "E",
}

ROAD_SURFACE_MAP = {
    "DRY":                    "A",
    "WET":                    "B",
    "SNOWY":                  "C",
    "ICY":                    "C",
    "SNOWY-ICY":              "C",
    "SLIPPERY":               "D",
    "MUDDY":                  "D",
    "OILY":                   "D",
}

CONTROL_DEVICE_MAP = {
    "CONTROLS FUNCTIONING":        "A",
    "CONTROLS NOT FUNCTIONING":    "B",
    "CONTROLS OBSCURED":           "C",
    "NO CONTROLS PRESENT":         "D",
    "NO CONTROLS PRESENT/FACTOR":  "D",
}

# Road condition: substring matching against CCRS text (no letter-dash prefix in data).
# CCRS actual values are plain text like "No Unusual Condition", "Holes, Deep Ruts", etc.
# Each tuple: (search string uppercase, SWITRS code). More specific entries first.
ROAD_CONDITION_PREFIXES = [
    ("HOLES",              "A"),
    ("DEEP RUT",           "A"),
    ("LOOSE MATERIAL",     "B"),
    ("OBSTRUCTION",        "C"),
    ("CONSTRUCTION",       "D"),
    ("REPAIR ZONE",        "D"),
    ("REDUCED ROADWAY",    "E"),
    ("REDUCED WIDTH",      "E"),
    ("FLOODED",            "F"),
    ("NO UNUSUAL",         "H"),   # must be before "OTHER" to avoid false match
    ("OTHER",              "G"),
]

# OAF text→SWITRS single-letter code mapping.
# CCRS stores verbose text in Other Associate Factor; this maps to SWITRS oaf codes.
# Order matters: more specific patterns before general ones.
# Inattention sub-types (P-Y) are resolved by also checking the Inattention column.
OAF_TEXT_MAP = [
    # ── Specific inattention sub-types (checked when OAF text = "INATTENTION") ──
    # These are handled separately via the Inattention column; see map_oaf_codes().
    # ── Non-inattention OAF values ───────────────────────────────────────────────
    ("VIOLATION",                "A"),
    ("VC SECTION VIOLATED",      "A"),
    ("VISION OBSCUREMENT",       "E"),
    ("STOP & GO",                "G"),
    ("STOP AND GO",              "G"),
    ("ENTERING OR LEAVING RAMP", "H"),
    ("ENTERING/LEAVING RAMP",    "H"),
    ("PREVIOUS COLLISION",       "I"),
    ("PREV COLLISION",           "I"),
    ("UNFAMILIAR WITH ROAD",     "J"),
    ("DEFECTIVE VEHICLE",        "K"),
    ("UNINVOLVED VEHICLE",       "L"),
    ("RUNAWAY VEHICLE",          "O"),
    ("NONE APPARENT",            "N"),
    ("NO APPARENT",              "N"),
    ("OTHER",                    "M"),   # keep after more specific entries
    ("INATTENTION",              "F"),   # generic inattention — overridden by sub-type below
]

# Inattention column text → SWITRS oaf code (P-Y range)
INATTENTION_OAF_MAP = {
    "CELL PHONE HANDHELD":  "P",
    "CELL PHONE HANDSFREE": "P",   # both handheld & handsfree → P (cell phone)
    "CELL PHONE":           "P",
    "ELECTRONIC_EQUIPMENT": "Q",
    "ELECTRONIC EQUIPMENT": "Q",
    "RADIO/CD":             "R",
    "RADIO":                "R",
    "SMOKING":              "S",
    "EATING":               "T",
    "CHILDREN":             "U",
    "ANIMALS":              "V",
    "ANIMAL":               "V",
    "PERSONAL HYGIENE":     "W",
    "READING":              "X",
    "OTHER":                "Y",
}


# ── Helper utilities ──────────────────────────────────────────────────────────

def normalize(value):
    """Strip and uppercase — used for most text comparisons."""
    return (value or "").strip().upper()


def nospace(value):
    """Strip, uppercase, AND remove all spaces — for CCRS enum values that
    may appear with or without spaces (e.g. 'ParkedVehicle' vs 'Parked Vehicle')."""
    return (value or "").strip().upper().replace(" ", "")


def road_condition_code(value):
    """
    Map CCRS road condition text to SWITRS single-letter code using substring matching.
    CCRS stores plain text without letter-dash prefix (e.g. "No Unusual Condition").
    Empty / dash / blank → "-"
    """
    v = (value or "").strip()
    if not v or v in ("-", ""):
        return "-"
    vu = v.upper()
    for substring, code in ROAD_CONDITION_PREFIXES:
        if substring in vu:
            return code
    return "-"


def map_oaf_codes(oaf_text, inattention_text):
    """
    Map CCRS Other Associate Factor text (+ Inattention column) to up to two
    SWITRS oaf_1 / oaf_2 single-letter codes.

    CCRS stores multiple OAF values separated by ' / '. Each segment is matched
    against OAF_TEXT_MAP. When the segment is an inattention variant and the
    Inattention column is populated, we upgrade from "F" to the specific P-Y code.

    Returns (oaf_1, oaf_2) — each is a single letter or "-".
    """
    if not oaf_text or not oaf_text.strip():
        return "-", "-"

    inatt_upper = normalize(inattention_text or "")
    segments = [s.strip().upper() for s in oaf_text.split("/") if s.strip()]
    codes = []

    for seg in segments[:2]:   # SWITRS only has oaf_1 and oaf_2
        code = "-"
        for pattern, mapped in OAF_TEXT_MAP:
            if pattern in seg:
                code = mapped
                break
        # If we matched generic INATTENTION (F), try to get the specific sub-type
        if code == "F" and inatt_upper:
            specific = INATTENTION_OAF_MAP.get(inatt_upper)
            if specific:
                code = specific
        codes.append(code)

    while len(codes) < 2:
        codes.append("-")
    return codes[0], codes[1]


def bool_to_yn(value):
    v = normalize(value)
    if v in ("TRUE", "1", "YES"):
        return "Y"
    if v in ("FALSE", "0", "NO"):
        return "N"
    return ""



def _pad_city_code(value):
    """
    Zero-pad city code to 4 digits if numeric, otherwise return as-is.
    e.g. "7" -> "0007", "19" -> "0019", "LA" -> "LA"
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v.isdigit():
        return v.zfill(4)
    return v

def extract_code_letter(value):
    """Pull the single leading letter from codes like 'A-DRY' or 'A - Clear'."""
    v = (value or "").strip()
    if v and v[0].isalpha():
        return v[0].upper()
    return ""


def zero_pad_time(value, width=4):
    v = (value or "").strip()
    return v.zfill(width) if v.isdigit() else v


def ccrs_datetime_to_date(value):
    """
    Extract YYYYMMDD from a CCRS datetime string.
    Handles: 1/18/2025 3:20:00 PM, 2025-01-18 15:20:00, 20250118, etc.
    """
    from datetime import datetime
    v = (value or "").strip()
    if not v:
        return ""
    for fmt in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%d %H:%M:%S",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(v, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    # Last resort: pull 8 leading digits
    digits = "".join(c for c in v if c.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return ""


def ccrs_datetime_to_time(value):
    """
    Extract HHMM (24-hour, zero-padded) from a CCRS datetime string.
    Returns empty string if no time component found.
    """
    from datetime import datetime
    v = (value or "").strip()
    if not v:
        return ""
    for fmt in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(v, fmt).strftime("%H%M")
        except ValueError:
            continue
    return ""


def ccrs_datetime_to_year(value):
    d = ccrs_datetime_to_date(value)
    return d[:4] if len(d) >= 4 else ""


def hit_run_convert(value):
    v = normalize(value)
    if v == "F":
        return "F"
    if v == "M":
        return "M"
    return "N"


def intersection_flag(primary_rd, secondary_rd, distance):
    """Y if crash is at intersection (distance blank/zero), N otherwise."""
    if not (primary_rd or "").strip():
        return ""
    if not (secondary_rd or "").strip():
        return "N"
    dist = (distance or "").strip()
    if dist in ("", "0", "0.0"):
        return "Y"
    return "N"


def worst_injury(injury_list):
    """
    Return the SWITRS collision_severity code for the most severe injury in a list.
    injury_list now contains degree codes ("0"-"7") already resolved by build_lookups.
    """
    # collision_severity uses 1-4 scale (1=fatal, 2=severe, 3=visible, 4=pain, 0=none)
    # victim_degree codes: 1=fatal, 2=severe, 3=visible, 4=pain, 5=suspectserious,
    #                      6=suspectminor, 7=possible, 0=none
    # Map victim degree → collision_severity
    deg_to_sev = {"1":"1","2":"2","5":"2","3":"3","6":"3","4":"4","7":"4","0":"0"}
    priority   = {"1":0, "2":1, "3":2, "4":3, "0":4}
    best_sev   = "0"
    best_rank  = 99
    for code in injury_list:
        sev  = deg_to_sev.get(str(code), "0")
        rank = priority.get(sev, 99)
        if rank < best_rank:
            best_rank = rank
            best_sev  = sev
    return best_sev


# ── CCRS-only fields to carry forward in unmapped output ─────────────────────

CCRS_CRASH_ONLY_FIELDS = [
    "ReportVersion", "IsPreliminary", "DispatchNotified", "HasPhotographs",
    "IsDeleted", "JudicialDistrict", "PreparedDate", "PrimaryCollisionFactorIsCited",
    "PrimaryCollisionPartyNumber", "ReviewedDate", "SecondaryUnitOfMeasure",
    "CreatedDate", "IsCountyRoad", "IsFreeWay", "CHP555Version",
    "NotificationDate", "HasDigitalMediaFiles", "EvidenceNumber",
    "IsLocationReferToNarrative", "IsAOIOneSameAsLocation",
]

CCRS_PARTY_ONLY_FIELDS = [
    "IsOnDutyEmergencyVehicle", "IsHitAndRun", "AirbagCode",
    "StreetOrHighwayName", "SpeedLimit", "DriverLicenseClass",
    "DriverLicenseStateCode", "Vehicle1Color", "Lane", "ThruLane",
    "TotalLane", "IsDREConducted",
]

CCRS_IWP_ONLY_FIELDS = [
    "Race", "IsWitnessOnly", "IsPassengerOnly", "AirbagCode",
]


# ── Main conversion logic ─────────────────────────────────────────────────────

def load_csv(path):
    """Load a CSV file, returning list of dicts with normalized (stripped) keys."""
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace from keys; skip None keys (trailing commas in header)
            rows.append({k.strip(): v for k, v in row.items() if k is not None})
    return rows


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows → {path}")


def build_lookups(party_rows, iwp_rows):
    """
    Pre-compute per-collision aggregates from party and IWP tables so they
    can be injected into the crash output without repeated passes.
    """
    # { collision_id: { field: value } }
    agg = {}

    def get(cid):
        if cid not in agg:
            agg[cid] = {
                "party_count": 0,
                "pedestrian_accident": "",
                "bicycle_accident": "",
                "motorcycle_accident": "",
                "truck_accident": "",
                "alcohol_involved": "",
                "stwd_vehtype_at_fault": "",
                "chp_veh_type_at_fault": "",
                "count_mc_killed": 0,
                "count_mc_injured": 0,
                "count_severe_inj": 0,
                "count_visible_inj": 0,
                "count_complaint_pain": 0,
                "count_ped_killed": 0,
                "count_ped_injured": 0,
                "count_bicyclist_killed": 0,
                "count_bicyclist_injured": 0,
                "collision_severity_list": [],
                # maps party_number → counts for victim rows
                "party_killed": {},
                "party_injured": {},
            }
        return agg[cid]

    for p in party_rows:
        cid = p.get("CollisionId", "").strip()
        if not cid:
            continue
        a = get(cid)
        a["party_count"] += 1

        ptype = nospace(p.get("PartyType", ""))
        if ptype == "PEDESTRIAN":
            a["pedestrian_accident"] = "Y"
        if ptype == "BICYCLIST":
            a["bicycle_accident"] = "Y"

        # Compute stwd_vehicle_type for this party (same logic as convert_party)
        chp_towing_bl = _pad_chp_type((p.get("Vehicle1TypeId", "") or p.get("ChpVehTypeTowing", "")).strip())
        chp_towed_bl  = _pad_chp_type((p.get("Vehicle2TypeId", "") or p.get("ChpVehTypeTowed",  "")).strip())
        stwd_bl = stwd_vehicle_type_from_chp(chp_towing_bl, chp_towed_bl)
        if stwd_bl in ("", "-"):
            v1desc_bl = normalize(p.get("Vehicle1TypeDesc", ""))
            stwd_bl = VEHICLE_TYPE_MAP.get(v1desc_bl, "")
            if not stwd_bl:
                for k, v in VEHICLE_TYPE_MAP.items():
                    if k in v1desc_bl:
                        stwd_bl = v
                        break
            stwd_bl = stwd_bl or "M"

        # motorcycle_accident: stwd C (Motorcycle/Scooter) or O (Moped)
        if stwd_bl in ("C", "O"):
            a["motorcycle_accident"] = "Y"
        # truck_accident: stwd F (Truck/Truck Tractor) or G (Truck with Trailer)
        if stwd_bl in ("F", "G"):
            a["truck_accident"] = "Y"

        # Use SobrietyDrugPhysicalCode1 per spec; fall back to combined field
        sobriety1 = normalize(
            p.get("SobrietyDrugPhysicalCode1", "") or p.get("SobrietyDrugPhysicalCode", "")
        )
        if sobriety1 in ("B", "C", "D"):
            a["alcohol_involved"] = "Y"

        is_fault = normalize(p.get("IsAtFault", ""))
        if is_fault in ("TRUE", "1", "YES"):
            a["stwd_vehtype_at_fault"] = stwd_vehicle_type_from_chp(chp_towing_bl, chp_towed_bl)
            a["chp_veh_type_at_fault"] = chp_towing_bl

        # Store this party's stwd type keyed by party_number for use in IWP loop
        pnum_bl = (p.get("Party Number", "") or p.get("PartyNumber", "")).strip()
        if pnum_bl:
            a.setdefault("party_stwd", {})[pnum_bl] = stwd_bl

    for iwp in iwp_rows:
        cid   = (iwp.get("Collision Id", "") or iwp.get("CollisionId", "")).strip()
        if not cid:
            continue
        a = get(cid)

        # Skip pure witnesses
        if normalize(iwp.get("IsWitnessOnly", "")) in ("TRUE", "1", "YES"):
            continue

        # Resolve injury code from the code field (preferred) then text fallback
        injury_code = normalize(
            iwp.get("ExtentOfInjuryCode", "") or ""
        ).replace(" ", "")

        # If code field is blank, attempt text-field fallback
        if not injury_code:
            injury_text = normalize(iwp.get("ExtentOfInjury", "")).replace(" ", "")
            # Map verbose text to code (e.g. "SUSPECTEDSERIOUSINJURY" won't match —
            # only exact code strings like "SUSPECTSERIOUS" will)
            if injury_text in INJURY_CODE_MAP:
                injury_code = injury_text

        # Determine killed/injured status
        is_killed  = injury_code in INJURY_CODE_KILLED
        is_injured = injury_code in INJURY_CODE_INJURED

        # Only IWP rows that represent an actual casualty (killed or injured) should
        # contribute to any aggregate count. Rows with blank, "NoInjury", or
        # unrecognised codes (e.g. unoccupied seat positions, passenger-only placeholder
        # rows) are skipped from all counts but still contribute to collision_severity
        # as degree "0" so the severity ranking works correctly.
        degree = INJURY_CODE_MAP.get(injury_code, "0")
        a["collision_severity_list"].append(degree)

        if not (is_killed or is_injured):
            continue   # no countable injury — skip all aggregate increments

        # Party-level killed/injured counts (used in party table)
        pnum = (iwp.get("Party Number", "") or iwp.get("PartyNumber", "")).strip()

        if pnum:
            if is_killed:
                a["party_killed"][pnum]  = a["party_killed"].get(pnum, 0)  + 1
            else:
                a["party_injured"][pnum] = a["party_injured"].get(pnum, 0) + 1

        # Collision-level person-type counts
        itype = normalize(iwp.get("InjuredPersonType", ""))
        if is_killed:
            if "PEDESTRIAN" in itype:
                a["count_ped_killed"] += 1
            if "BICYCLIST" in itype or "BICYCLE" in itype:
                a["count_bicyclist_killed"] += 1
        else:  # is_injured
            if "PEDESTRIAN" in itype:
                a["count_ped_injured"] += 1
            if "BICYCLIST" in itype or "BICYCLE" in itype:
                a["count_bicyclist_injured"] += 1

        # Motorcyclist killed/injured — look up the victim's party stwd type
        if pnum:
            victim_stwd = a.get("party_stwd", {}).get(pnum, "")
            if victim_stwd in ("C", "O"):   # Motorcycle/Scooter or Moped
                if is_killed:
                    a["count_mc_killed"] += 1
                else:
                    a["count_mc_injured"] += 1

        # Severity bucket counts
        if injury_code in ("SUSPECTSERIOUS", "SEVEREINACTIVE"):
            a["count_severe_inj"] += 1
        elif injury_code in ("SUSPECTMINOR", "OTHERVISIBLEINACTIVE"):
            a["count_visible_inj"] += 1
        elif injury_code in ("POSSIBLEINJURY", "COMPLAINTOFPAININACTIVE"):
            a["count_complaint_pain"] += 1

    return agg



# ── VC Code parsing and lookup ────────────────────────────────────────────────
#
# CCRS stores the violation as a messy free-text field, e.g.:
#   "VC 22107", "VC 22450(a)", "21658CVC", "23152A", "UNSAFE BACKING"
# We normalize these to vc_code_full format (e.g. "22107", "22450A", "23152A")
# then look them up in the vc_codes_table CSV to get:
#   pcf  → maps to pcf_viol_category (2-digit string)
#   oaf  → maps to oaf_viol_cat (2-digit string)
#   vc_code (int) → pcf_violation / oaf_viol_section (the section number)
#   sub  → pcf_viol_subsection / oaf_viol_suffix (single letter or blank)
#
# The vc_codes_table.csv columns are:
#   vc_code (int), sub (str), pcf (str), oaf (str), id (int), vc_code_full (str)
#
# oaf_violation_code is always "C" (Vehicle Code) for VC sections.
# oaf_1 / oaf_2 are the SWITRS oaf category codes from the "oaf" sheet —
#   that sheet maps oaf_viol_cat values to the single-letter oaf_1 codes.
#   Since we don't have that mapping yet, we store oaf_viol_cat and leave
#   oaf_1/oaf_2 to be resolved when the SWITRS Raw Data Tables xlsx is available.
#
# Similarly, pcf_viol_category comes from the "pcf_viol_cat" sheet.
# We store the raw pcf value from vc_codes_table and refine when xlsx is available.

import re as _re

def _normalize_vc_code_full(raw):
    """
    Convert messy CCRS violation text to vc_code_full format for lookup.

    Handles all observed patterns:
      "VC 22107"                       -> "22107"
      "VC 22450(a)"                    -> "22450A"
      "VC 23152(A)"                    -> "23152A"
      "21658CVC"                       -> "21658"
      "23152A"                         -> "23152A"
      "21658(a)"                       -> "21658A"
      "VC 21650.1"                     -> "21650"   (decimal stripped per spec)
      "21801 (a) CVC"                  -> "21801A"
      "VC 21651(a)(1)"                 -> "21651A"  (secondary paren dropped)
      "22350 VC"                       -> "22350"
      "23152(a) CVC"                   -> "23152A"
      "21806A"                         -> "21806A"
      "VC 22350 UNSAFE SPEED:..."      -> "22350"   (trailing text stripped)
      "VC 21658(A) UNSAFE LANE..."     -> "21658A"
      "UNSAFE BACKING"                 -> None      (no leading digit group)
      "UNSAFE TURNING MOVEMENT"        -> None

    Returns normalized uppercase string or None if not a VC section number.
    """
    if not raw:
        return None
    v = raw.strip().upper()

    # Strip VC / CVC markers wherever they appear
    v = _re.sub(r"\bCVC\b", " ", v)
    v = _re.sub(r"\bVC\b",  " ", v)
    v = v.strip()

    # Find the FIRST occurrence of a VC section number in what remains.
    # Pattern: digits, optional decimal group (dropped), optional letter suffix
    #   (\d+)            – section digits
    #   (?:\.\d+)?       – decimal tail like .1 → ignored (spec: strip it)
    #   (?:              – optional suffix, two sub-patterns:
    #     \s*\(([A-Z])\) – parenthesised  "(A)"
    #     |              – or
    #     \s*([A-Z])(?![A-Z\d])  – bare letter "A" not followed by letter/digit
    #                              (avoids grabbing first letter of words like "UNSAFE")
    #   )?
    m = _re.search(
        r"(\d+)(?:\.\d+)?(?:\s*\(([A-Z])\)|\s*([A-Z])(?![A-Z\d]))?",
        v
    )
    if not m:
        return None

    section = m.group(1)
    suffix  = m.group(2) or m.group(3) or ""
    return section + suffix if suffix else section


def load_vc_codes(csv_path):
    """
    Load vc_codes_table.csv and return a dict keyed by normalized vc_code_full.
    Each value: {"vc_code": int, "sub": str, "pcf": str, "oaf": str, "vc_code_full": str}
    """
    if not csv_path or not os.path.exists(csv_path):
        return {}
    lookup = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("vc_code_full") or "").strip().upper()
            if key:
                lookup[key] = {
                    "vc_code":      row.get("vc_code", "").strip(),
                    "sub":          row.get("sub", "").strip(),
                    "pcf":          row.get("pcf", "").strip(),
                    "oaf":          row.get("oaf", "").strip(),
                    "vc_code_full": row.get("vc_code_full", "").strip(),
                }
    return lookup


def parse_ccrs_violation(raw_violation, vc_lookup):
    """
    Parse a CCRS Primary Collision Factor Violation field and return a dict of
    SWITRS party/crash fields derived from it.

    Returns dict with keys:
      pcf_code_of_viol     - "C" if Vehicle Code, else "-"
      pcf_viol_category    - 2-char string from vc_codes.pcf (e.g. "01", "09")
      pcf_violation        - numeric section only, up to 5 digits (e.g. "22107")
      pcf_viol_subsection  - single letter suffix or ""
      oaf_violation_code   - "C" (Vehicle Code) or "-"
      oaf_viol_cat         - 2-char from vc_codes.oaf
      oaf_viol_section     - same as pcf_violation (section number)
      oaf_viol_suffix      - same as pcf_viol_subsection
      _raw_normalized      - the normalized key used for lookup (debug)
      _matched             - True if found in vc_codes table
    """
    result = {
        "pcf_code_of_viol":    "-",
        "pcf_viol_category":   "",
        "pcf_violation":       "",
        "pcf_viol_subsection": "",
        "oaf_violation_code":  "-",
        "oaf_viol_cat":        "",
        "oaf_viol_section":    "",
        "oaf_viol_suffix":     "",
        "_raw_normalized":     "",
        "_matched":            False,
    }
    if not raw_violation or not raw_violation.strip():
        return result

    normalized = _normalize_vc_code_full(raw_violation.strip())
    result["_raw_normalized"] = normalized or raw_violation.strip()

    if normalized is None:
        # Non-VC text value (e.g. "UNSAFE BACKING", "UNSAFE TURNING MOVEMENT")
        # These are not VC sections — leave numeric fields blank, code = "-"
        return result

    # It is a VC section — code is always "C" (Vehicle Code)
    result["pcf_code_of_viol"]   = "C"
    result["oaf_violation_code"] = "C"

    # Extract numeric section and suffix from normalized key
    m = _re.match(r"^(\d+(?:\.\d+)?)([A-Z]?)$", normalized)
    if m:
        section, suffix = m.group(1), m.group(2)
        result["pcf_violation"]       = section[:7]   # allow decimals like 21650.1
        result["pcf_viol_subsection"] = suffix
        result["oaf_viol_section"]    = section[:7]
        result["oaf_viol_suffix"]     = suffix

    # Attempt lookup in vc_codes table
    row = vc_lookup.get(normalized.upper())
    if row:
        result["pcf_viol_category"] = row["pcf"]
        result["oaf_viol_cat"]      = row["oaf"]
        result["_matched"]          = True
    else:
        # Try without suffix as fallback (some entries in table omit suffix)
        if m and m.group(2):
            fallback = m.group(1)
            row2 = vc_lookup.get(fallback.upper())
            if row2:
                result["pcf_viol_category"] = row2["pcf"]
                result["oaf_viol_cat"]      = row2["oaf"]
                result["_matched"]          = True

    return result



def _resolve_collision_time(row):
    """
    Determine collision_time for SWITRS crash table.
    Priority:
      1. CollisionTime / Collision Time field if non-zero
      2. Time extracted from CrashDateTime
      3. Special case: if computed time is "0000", check Crash Time Description —
         if that field equals "2500", use "2500" (unknown time code); else keep "0000".
    """
    raw_ct = (row.get("Collision Time", "") or row.get("CollisionTime", "")).strip()
    t = zero_pad_time(raw_ct) if raw_ct else ""
    if not t:
        t = ccrs_datetime_to_time(row.get("Crash Date Time", "") or row.get("CrashDateTime", ""))
    # Special case: time of 0 may mean "not known" — check description field
    if t in ("0", "00", "000", "0000"):
        crash_time_desc = (
            row.get("Crash Time Description", "") or
            row.get("CrashTimeDescription", "") or ""
        ).strip()
        if crash_time_desc == "2500":
            return "2500"
    return t


def _is_chp_record(report_number, ncic_code, crash_year):
    """
    Determine if a crash record was filed by CHP based on the report number format.

    CHP report numbers follow the pattern: JURIS-YEAR-XXXXX
      e.g. "9525-2025-00004" where "9525" matches the NCIC code
       and "2025" matches the crash year extracted from CrashDateTime.

    Returns True if pattern matches, False otherwise.
    """
    rn = (report_number or "").strip()
    ncic = (ncic_code or "").strip()
    year = (crash_year or "").strip()
    if not rn or not ncic or not year:
        return False
    parts = rn.split("-")
    if len(parts) < 3:
        return False
    return parts[0] == ncic and parts[1] == year


def _chp_beat_class(report_number, ncic_code, crash_year):
    """
    Return SWITRS chp_beat_class:
      1 = CHP Primary (report number matches JURIS-YEAR-XXXXX pattern)
      0 = Not CHP
    Note: value 2 (CHP Other) is not determinable from CCRS data alone.
    """
    return "1" if _is_chp_record(report_number, ncic_code, crash_year) else "0"

def convert_crash(crash_rows, agg, report_number_map, vc_lookup=None):
    """Convert CCRS Crash rows → SWITRS crash rows."""
    out = []
    for row in crash_rows:
        cid = row.get("CollisionId", "").strip() or row.get("Collision Id", "").strip()
        a = agg.get(cid, {})

        collision_severity_list = a.get("collision_severity_list", [])
        severity = worst_injury(collision_severity_list)

        # Special condition: map CCRS SpecialCondition text → SWITRS 0-6 code
        # CCRS values are slash-separated, e.g. "Counter Report / Private Property"
        # SWITRS codes derivable from text:
        #   1 = School Bus Collision (on public road, pupils present)
        #   3 = No Pupils on School Bus (not on public road)
        #   0 = everything else (Counter Report, Fatal, Courtesy, etc.)
        # Codes 2,5,6 derive from CHP beat — not available in SpecialCondition text.
        special_cond_raw = normalize(row.get("Special Condition", "") or row.get("SpecialCondition", ""))
        sc_tokens = {t.strip() for t in special_cond_raw.split("/")}
        if "SCHOOL BUS COLLISION" in special_cond_raw and "NO PUPILS ON SCHOOL BUS" not in special_cond_raw:
            special_cond = "1"
        elif "NO PUPILS ON SCHOOL BUS" in special_cond_raw:
            special_cond = "3"
        else:
            special_cond = "0"

        # not_private_property: blank when crash is on private property
        not_private_property = "" if "PRIVATE PROPERTY" in special_cond_raw else "Y"

        primary_rd = (row.get("Primary Rd", "") or row.get("PrimaryRd", "")
                      or row.get("PrimaryRoad", "") or row.get("Primary Road", ""))
        secondary_rd = (row.get("Secondary Rd", "") or row.get("SecondaryRd", "")
                        or row.get("SecondaryRoad", "") or row.get("Secondary Road", ""))
        sec_distance_raw = (row.get("SecondaryDistance", "") or "").strip()
        sec_uom = normalize(row.get("SecondaryUnitOfMeasure", "") or row.get("Secondary Unit Of Measure", ""))
        # Convert miles → feet if unit of measure is "M" (miles)
        if sec_uom == "M" and sec_distance_raw:
            try:
                sec_distance = str(round(float(sec_distance_raw) * 5280))
            except ValueError:
                sec_distance = sec_distance_raw
        else:
            sec_distance = sec_distance_raw

        # Parse the Primary Collision Factor Violation for VC code lookups
        _pcf_viol_raw = (
            row.get("Primary Collision Factor Violation", "")
            or row.get("PrimaryCollisionFactorViolation", "")
            or row.get("PCFViolation", "")
        )
        _vc = parse_ccrs_violation(_pcf_viol_raw, vc_lookup or {})

        acc = {
            # ── Identifiers ──────────────────────────────────────
            "case_id":              cid,
            "local_report_number":  row.get("Report Number", "") or row.get("ReportNumber", ""),

            # ── Temporal ─────────────────────────────────────────
            "accident_year":        ccrs_datetime_to_year(row.get("Crash Date Time", "") or row.get("CrashDateTime", "")),
            "proc_date":            ccrs_datetime_to_date(
                                        row.get("PreparedDate", "") or row.get("ModifiedDate", "")
                                    ),
            "collision_date":       ccrs_datetime_to_date(row.get("Crash Date Time", "") or row.get("CrashDateTime", "")),
            "collision_time":       _resolve_collision_time(row),
            "day_of_week":          DAY_OF_WEEK.get(
                                        (row.get("Day Of Week", "") or row.get("Day of Week", "") or row.get("DayOfWeek", "") or "").strip().title()
                                    , ""),

            # ── Agency / geography ───────────────────────────────
            "juris":                row.get("NCIC Code", "") or row.get("NCICCode", ""),
            "officer_id":           "",   # not in CCRS
            "reporting_district":   row.get("ReportingDistrict", "") or row.get("ReportingDistrictCode", ""),
            "chp_shift":            "",   # not in CCRS
            "population":           "",   # deprecated
            "cnty_city_loc":        _pad_city_code(
                                        row.get("CityCode", "") or row.get("City Code", "") or ""
                                    ),
            "beat_type":            "",   # cannot reliably map from CCRS Beat
            "chp_beat_type":        "",
            "chp_beat_class":       _chp_beat_class(
                                        row.get("Report Number", "") or row.get("ReportNumber", ""),
                                        row.get("NCIC Code", "") or row.get("NCICCode", ""),
                                        ccrs_datetime_to_year(row.get("Crash Date Time", "") or row.get("CrashDateTime", "")),
                                    ),
            "city_division_lapd":   "",
            "beat_number":          row.get("Beat", ""),

            # ── Location ─────────────────────────────────────────
            "primary_rd":           primary_rd,
            "secondary_rd":         secondary_rd,
            "distance":             sec_distance,
            "direction":            row.get("SecondaryDirection", ""),
            "intersection":         intersection_flag(primary_rd, secondary_rd, sec_distance),
            "latitude":             row.get("Latitude", ""),
            "longitude":            row.get("Longitude", ""),

            # ── Environment ──────────────────────────────────────
            "weather_1":            extract_code_letter(row.get("Weather 1", "") or row.get("Weather1", "")),
            "weather_2":            extract_code_letter(row.get("Weather 2", "") or row.get("Weather2", "")) or "-",
            "state_hwy_ind":        bool_to_yn(row.get("IsHighwayRelated", "")),
            "road_surface":         extract_code_letter(ROAD_SURFACE_MAP.get(
                                        normalize(row.get("RoadwaySurfaceCode", "")),
                                        row.get("RoadwaySurfaceCode", ""))),
            "road_cond_1":          road_condition_code(row.get("Road Condition 1", "") or row.get("RoadCondition1", "")),
            "road_cond_2":          road_condition_code(row.get("Road Condition 2", "") or row.get("RoadCondition2", "")),
            "lighting":             extract_code_letter(row.get("LightingCode", "")),
            "control_device":       extract_code_letter(row.get("TrafficControlDeviceCode", "")),

            # ── Crash characteristics ─────────────────────────────
            "tow_away":             bool_to_yn(row.get("IsTowAway", "")),
            "collision_severity":   severity,
            "number_killed":        _safe_count(row.get("NumberKilled", "")),
            "number_injured":       _safe_count(row.get("NumberInjured", "")),
            "party_count":          str(a.get("party_count", "")),
            "primary_coll_factor":  extract_code_letter(
                                        row.get("PrimaryCollisionFactorCode", "")
                                        or row.get("Primary Collision Factor Code", "")
                                        or row.get(" Primary Collision Factor Code", "")
                                    ),
            "pcf_code_of_viol":     _vc["pcf_code_of_viol"],
            "pcf_viol_category":    _vc["pcf_viol_category"],
            "pcf_violation":        _vc["pcf_violation"],
            "pcf_viol_subsection":  _vc["pcf_viol_subsection"],
            "hit_and_run":          hit_run_convert(row.get("HitRun", "")),
            "type_of_collision":    extract_code_letter(row.get("CollisionTypeCode", "") or row.get("Collision Type Code", "")),
            "mviw":                 extract_code_letter(row.get("MotorVehicleInvolvedWithCode", "")),
            "ped_action":           extract_code_letter(row.get("PedestrianActionCode", "")),
            "special_cond":         special_cond,
            "not_private_property": not_private_property,

            # ── Derived from Party ────────────────────────────────
            "pedestrian_accident":  a.get("pedestrian_accident", ""),
            "bicycle_accident":     a.get("bicycle_accident", ""),
            "motorcycle_accident":  a.get("motorcycle_accident", ""),
            "truck_accident":       a.get("truck_accident", ""),
            "alcohol_involved":     a.get("alcohol_involved", ""),
            "stwd_vehtype_at_fault": a.get("stwd_vehtype_at_fault", ""),
            "chp_vehtype_at_fault": a.get("chp_veh_type_at_fault", ""),

            # ── Derived from IWP ──────────────────────────────────
            "count_severe_inj":         str(a.get("count_severe_inj", 0)),
            "count_visible_inj":        str(a.get("count_visible_inj", 0)),
            "count_complaint_pain":     str(a.get("count_complaint_pain", 0)),
            "count_ped_killed":         str(a.get("count_ped_killed", 0)),
            "count_ped_injured":        str(a.get("count_ped_injured", 0)),
            "count_bicyclist_killed":   str(a.get("count_bicyclist_killed", 0)),
            "count_bicyclist_injured":  str(a.get("count_bicyclist_injured", 0)),
            "count_mc_killed":          str(a.get("count_mc_killed", 0)),
            "count_mc_injured":         str(a.get("count_mc_injured", 0)),

            # ── Deprecated Caltrans / milepost fields ─────────────
            "caltrans_county": "", "caltrans_district": "", "state_route": "",
            "route_suffix": "", "postmile_prefix": "",
            "postmile":     row.get("MilepostDistance", "") or row.get("Milepost Distance", ""),
            "location_type": "", "ramp_intersection": "",
            "side_of_hwy":  row.get("MilepostDirection", "") or row.get("Milepost Direction", ""),
            "chp_road_type": "", "primary_ramp": "-", "secondary_ramp": "-",
        }
        out.append(acc)
    return out


def convert_party(party_rows, report_number_map, vc_lookup=None, agg=None):
    """Convert CCRS Party rows → SWITRS party rows."""
    out = []
    for row in party_rows:
        cid = row.get("CollisionId", "").strip()
        pnum = row.get("Party Number", "").strip() or row.get("PartyNumber", "").strip()


        # Map Other Associate Factor text + Inattention column → oaf_1 / oaf_2 codes
        oaf_raw       = row.get("Other Associate Factor", "") or row.get("OtherAssociateFactor", "")
        inatt_raw     = row.get("Inattention", "") or row.get("InattentionType", "")
        oaf_1, oaf_2  = map_oaf_codes(oaf_raw, inatt_raw)

        # Parse primary collision factor violation for pcf/oaf VC lookups
        _pcf_viol_raw = (
            row.get("Primary Collision Factor Violation", "")
            or row.get("PrimaryCollisionFactorViolation", "")
            or row.get("PCFViolation", "")
        )
        _vc = parse_ccrs_violation(_pcf_viol_raw, vc_lookup or {})

        # SpecialInformation: split out sp_info slots
        # CCRS stores raw code tokens (A, B, C, D, 1, 2, 3, 4, E) in this field,
        # potentially multiple values separated by spaces or commas.
        # We extract the set of single-char/single-digit tokens to match exactly —
        # substring matching ("E" in sp_raw) is incorrect because every description
        # containing the letter E would false-match.
        sp_raw = normalize(row.get("Special Information", "") or row.get("SpecialInformation", ""))
        # Tokenise: split on whitespace and commas, keep only 1-char tokens
        sp_tokens = {t.strip(" ,;") for t in sp_raw.replace(",", " ").split() if len(t.strip(" ,;")) == 1}

        # sp_info_1: "A" = Hazardous Materials
        sp_info_1 = "A" if "A" in sp_tokens else ""

        # sp_info_2: cell-phone code (1/2/3/4 take priority over legacy B/C/D)
        sp_info_2 = ""
        for code in ["1", "2", "3", "4", "B", "C", "D"]:
            if code in sp_tokens:
                sp_info_2 = code
                break

        # sp_info_3: "E" = School Bus Related
        # NOTE: historically contaminated in CCRS exports due to a substring-match bug.
        # Now uses correct whole-token matching. The reverse converter treats this field
        # as unreliable in older output files.
        sp_info_3 = "E" if "E" in sp_tokens else ""

        # SobrietyDrugPhysicalCode1 → party_sobriety (drinking status)
        # SobrietyDrugPhysicalCode2 → party_drug_physical (drug/physical impairment)
        sobriety1 = normalize(
            row.get("SobrietyDrugPhysicalCode1", "") or row.get("SobrietyDrugPhysicalCode", "")
        )
        sobriety2 = normalize(row.get("SobrietyDrugPhysicalCode2", ""))
        party_sobriety      = sobriety1 if sobriety1 in ("A","B","C","D","G","H") else ""
        # If Code2 present use it; else fall back to Code1 for drug/physical range
        if sobriety2 in ("E","F","I","H"):
            party_drug_physical = sobriety2
        elif sobriety1 in ("E","F","I"):
            party_drug_physical = sobriety1
        else:
            party_drug_physical = ""

        # stwd_vehicle_type derived from CHP vehicle type codes (same logic as crash table)
        chp_towing_party = _pad_chp_type(
            (row.get("Vehicle1TypeId", "") or row.get("ChpVehTypeTowing", "")).strip()
        )
        chp_towed_party = _pad_chp_type(
            (row.get("Vehicle2TypeId", "") or row.get("ChpVehTypeTowed", "")).strip()
        )
        stwd_type = stwd_vehicle_type_from_chp(chp_towing_party, chp_towed_party)
        # Fall back to Vehicle1TypeDesc text match only when no CHP towing code present
        if not chp_towing_party or chp_towing_party in ("-",):
            v1desc = normalize(row.get("Vehicle1TypeDesc", ""))
            stwd_type = VEHICLE_TYPE_MAP.get(v1desc, "")
            if not stwd_type:
                for k, v in VEHICLE_TYPE_MAP.items():
                    if k in v1desc:
                        stwd_type = v
                        break
            stwd_type = stwd_type or "M"

        _pagg = (agg or {}).get(cid, {})

        p = {
            "case_id":              cid,
            "party_number":         pnum,
            "party_type":           PARTY_TYPE_MAP.get(nospace(row.get("PartyType", "")), ""),
            "at_fault":             _at_fault_code(row.get("IsAtFault", "")),
            "party_sex":            extract_code_letter(row.get("GenderCode", "")) or "-",
            "party_age":            (row.get("StatedAge", "") or "").strip() or "998",
            "party_sobriety":       party_sobriety or "-",
            "party_drug_physical":  party_drug_physical or "-",
            "dir_of_travel":        extract_code_letter(row.get("DirectionOfTravel", "")) or "-",
            "party_safety_equip_1": extract_code_letter(
                                        row.get("AirbagCode", "") or row.get("AirBagCode", "") or
                                        row.get("AirBagCodeDescription", "")
                                    ) or "-",
            "party_safety_equip_2": extract_code_letter(
                                        row.get("SafetyEquipmentCode", "") or
                                        row.get("SafetyEquipmentCode and Description", "")
                                    ) or "-",
            "finan_respons":        "",  # not in CCRS
            "sp_info_1":            sp_info_1,
            "sp_info_2":            sp_info_2,
            "sp_info_3":            sp_info_3,
            "oaf_violation_code":   _vc["oaf_violation_code"],
            "oaf_viol_cat":         _vc["oaf_viol_cat"] or "-",
            "oaf_viol_section":     _vc["oaf_viol_section"] or "-",
            "oaf_viol_suffix":      _vc["oaf_viol_suffix"],
            "oaf_1":                oaf_1,
            "oaf_2":                oaf_2,
            "party_number_killed":  str(_pagg.get("party_killed",  {}).get(pnum, 0)),
            "party_number_injured": str(_pagg.get("party_injured", {}).get(pnum, 0)),
            "move_pre_acc":         extract_code_letter(row.get("MovementPrecCollCode", "") or row.get("MovementPrecCollCode and Description", "")),
            "vehicle_year":         row.get("Vehicle1Year", ""),
            "vehicle_make":         row.get("Vehicle1Make", ""),
            "stwd_vehicle_type":    stwd_type,
            "chp_veh_type_towing":  _pad_chp_type((row.get("Vehicle1TypeId", "") or row.get("ChpVehTypeTowing", "")).strip()),
            "chp_veh_type_towed":   _pad_chp_type((row.get("Vehicle2TypeId", "") or row.get("ChpVehTypeTowed",  "")).strip()),
            "race":                 extract_code_letter(row.get("RaceCode", "") or row.get("RaceCode and Desc", "")),
            "inattention":          INATTENTION_MAP.get(normalize(inatt_raw), ""),
            "special_info_f":       "",  # not in CCRS
            "special_info_g":       "",
            "local_report_number":  report_number_map.get(cid, ""),
        }
        out.append(p)
    return out


def convert_victim(iwp_rows, report_number_map, party_rows=None):
    """
    Convert CCRS InjuredWitnessPassenger rows → SWITRS victim rows.

    Field sources (updated):
      party_number             ← PartyNumber field directly from IWP table
      victim_role              ← InjuredPersonType (nospace match)
      victim_degree_of_injury  ← ExtentOfInjuryCode (code) or ExtentOfInjury (text)
      victim_safety_equip_1    ← AirbagCode field in IWP
      victim_safety_equip_2    ← SafetyEquipmentCode field in IWP
      victim_seating_position  ← SeatPosition mapped via SEAT_POSITION_MAP
                                  (if Other, check SeatPositionOther first)
      victim_ejected           ← Ejected mapped via EJECTED_MAP
    """
    out = []
    for row in iwp_rows:
        cid = (row.get("Collision Id", "") or row.get("CollisionId", "")).strip()

        # Skip pure witnesses
        if nospace(row.get("IsWitnessOnly", "")) in ("TRUE", "1", "YES"):
            continue

        # ── party_number — taken directly from IWP PartyNumber field ─────────
        party_number = (
            row.get("PartyNumber", "") or row.get("Party Number", "") or ""
        ).strip()

        # ── victim_degree_of_injury ───────────────────────────────────────────
        injury_code = nospace(row.get("ExtentOfInjuryCode", "") or "")
        if injury_code in INJURY_CODE_MAP:
            degree = INJURY_CODE_MAP[injury_code]
        else:
            injury_text = normalize(row.get("ExtentOfInjury", ""))
            degree = INJURY_SEVERITY_MAP.get(injury_text, "0")

        # ── victim_role ───────────────────────────────────────────────────────
        itype_ns = nospace(row.get("InjuredPersonType", ""))
        role = VICTIM_ROLE_MAP.get(itype_ns, "")
        if not role:
            if "PEDESTRIAN" in itype_ns:              role = "3"
            elif "BICYCLIST" in itype_ns or "BICYCLE" in itype_ns: role = "4"
            elif "PASSENGER" in itype_ns:             role = "2"
            elif "DRIVER" in itype_ns:                role = "1"
            elif "OPERATOR" in itype_ns:              role = "6"
            elif "OTHER" in itype_ns:                 role = "5"

        # ── victim_safety_equip_1 — AirbagCode ───────────────────────────────
        equip1 = extract_code_letter(
            row.get("AirbagCode", "") or row.get("AirBagCode", "") or
            row.get("AirBagCode And Desc", "") or row.get("AirBagCodeAndDesc", "")
        )

        # ── victim_safety_equip_2 — SafetyEquipmentCode ──────────────────────
        equip2 = extract_code_letter(
            row.get("SafetyEquipmentCode", "") or
            row.get("SafetyEquipmentCode and Desc", "") or
            row.get("SafetyEquipmentCodeAndDesc", "")
        )

        # ── victim_seating_position — mapped via SEAT_POSITION_MAP ───────────
        seat_raw   = (row.get("SeatPosition", "") or "").strip()
        seat_other = (row.get("SeatPositionOther", "") or "").strip()
        seat_pos   = seat_position_code(seat_raw, seat_other)

        # ── victim_ejected — mapped via EJECTED_MAP ───────────────────────────
        ejected_ns = nospace(row.get("Ejected", "") or "")
        ejected = EJECTED_MAP.get(ejected_ns, "-")

        # ── victim_age — blank → 998 ─────────────────────────────────────────
        victim_age = (row.get("StatedAge", "") or "").strip() or "998"

        v = {
            "case_id":                  cid,
            "party_number":             party_number,
            "victim_role":              role,
            "victim_sex":               extract_code_letter(row.get("Gender", "") or row.get("GenderCode", "")),
            "victim_age":               victim_age,
            "victim_degree_of_injury":  degree,
            "victim_seating_position":  seat_pos,
            "victim_safety_equip_1":    equip1,
            "victim_safety_equip_2":    equip2,
            "victim_ejected":           ejected,
            "local_report_number":      report_number_map.get(cid, ""),
        }
        out.append(v)
    return out


def build_unmapped_ccrs(crash_rows, party_rows, iwp_rows):
    """Collect CCRS-only fields and write to a separate CSV for archival."""
    rows = []
    for row in crash_rows:
        cid = row.get("CollisionId", "").strip() or row.get("Collision Id", "").strip()
        r = {"SourceTable": "Crash", "CollisionId": cid}
        for f in CCRS_CRASH_ONLY_FIELDS:
            r[f] = row.get(f, "")
        rows.append(r)

    for row in party_rows:
        cid = row.get("CollisionId", "").strip()
        pnum = row.get("Party Number", "").strip() or row.get("PartyNumber", "").strip()
        r = {"SourceTable": "Party", "CollisionId": cid, "PartyNumber": pnum}
        for f in CCRS_PARTY_ONLY_FIELDS:
            r[f] = row.get(f, "")
        rows.append(r)

    for row in iwp_rows:
        cid = (row.get("Collision Id", "") or row.get("CollisionId", "")).strip()
        r = {"SourceTable": "IWP", "CollisionId": cid}
        for f in CCRS_IWP_ONLY_FIELDS:
            r[f] = row.get(f, "")
        rows.append(r)

    return rows


# ── SWITRS output schemas ─────────────────────────────────────────────────────

CRASH_FIELDS = [
    "case_id", "accident_year", "proc_date", "juris", "collision_date",
    "collision_time", "officer_id", "reporting_district", "day_of_week",
    "chp_shift", "population", "cnty_city_loc", "special_cond", "beat_type",
    "chp_beat_type", "city_division_lapd", "chp_beat_class", "beat_number",
    "primary_rd", "secondary_rd", "distance", "direction", "intersection",
    "weather_1", "weather_2", "state_hwy_ind", "caltrans_county",
    "caltrans_district", "state_route", "route_suffix", "postmile_prefix",
    "postmile", "location_type", "ramp_intersection", "side_of_hwy",
    "tow_away", "collision_severity", "number_killed", "number_injured",
    "party_count", "primary_coll_factor", "pcf_code_of_viol",
    "pcf_viol_category", "pcf_violation", "pcf_viol_subsection",
    "hit_and_run", "type_of_collision", "mviw", "ped_action", "road_surface",
    "road_cond_1", "road_cond_2", "lighting", "control_device", "chp_road_type",
    "pedestrian_accident", "bicycle_accident", "motorcycle_accident",
    "truck_accident", "not_private_property", "alcohol_involved",
    "stwd_vehtype_at_fault", "chp_vehtype_at_fault", "count_severe_inj",
    "count_visible_inj", "count_complaint_pain", "count_ped_killed",
    "count_ped_injured", "count_bicyclist_killed", "count_bicyclist_injured",
    "count_mc_killed", "count_mc_injured", "primary_ramp", "secondary_ramp",
    "latitude", "longitude", "local_report_number",
]

PARTY_FIELDS = [
    "case_id", "party_number", "party_type", "at_fault", "party_sex",
    "party_age", "party_sobriety", "party_drug_physical", "dir_of_travel",
    "party_safety_equip_1", "party_safety_equip_2", "finan_respons",
    "sp_info_1", "sp_info_2", "sp_info_3", "oaf_violation_code",
    "oaf_viol_cat", "oaf_viol_section", "oaf_viol_suffix", "oaf_1", "oaf_2",
    "party_number_killed", "party_number_injured", "move_pre_acc",
    "vehicle_year", "vehicle_make", "stwd_vehicle_type", "chp_veh_type_towing",
    "chp_veh_type_towed", "race", "inattention", "special_info_f",
    "special_info_g", "local_report_number",
]

VICTIM_FIELDS = [
    "case_id", "party_number", "victim_role", "victim_sex", "victim_age",
    "victim_degree_of_injury", "victim_seating_position",
    "victim_safety_equip_1", "victim_safety_equip_2", "victim_ejected",
    "local_report_number",
]

UNMAPPED_FIELDS = (
    ["SourceTable", "CollisionId", "PartyNumber"]
    + CCRS_CRASH_ONLY_FIELDS
    + CCRS_PARTY_ONLY_FIELDS
    + CCRS_IWP_ONLY_FIELDS
)



DISCREPANCY_FIELDS = [
    "collision_id", "report_number", "crash_date",
    "ccrs_number_killed", "ccrs_number_injured",
    "iwp_killed_count", "iwp_injured_count",
    "iwp_total_casualty_rows",
    "discrepancy_type", "notes",
]


def check_discrepancies(crash_rows, agg, report_number_map):
    """
    Compare CCRS crash-table NumberKilled / NumberInjured against the counts
    actually derived from IWP rows, and return a list of discrepancy dicts.

    A discrepancy is flagged when:
      - iwp_killed_count  != ccrs_number_killed   (mismatch on killed)
      - iwp_injured_count != ccrs_number_injured  (mismatch on injured)

    The IWP counts are the sum of party_killed / party_injured across all parties
    for that collision, which is the same data used to populate count_mc_killed,
    count_ped_killed, etc.  Any excess over the CCRS header counts is evidence
    of duplicate IWP rows in the source data.
    """
    rows = []
    for row in crash_rows:
        cid = row.get("CollisionId", "").strip() or row.get("Collision Id", "").strip()
        if not cid:
            continue

        ccrs_killed  = _safe_count(row.get("NumberKilled",  ""))
        ccrs_injured = _safe_count(row.get("NumberInjured", ""))

        a = agg.get(cid, {})
        # Sum killed / injured counts across all parties for this collision
        iwp_killed  = sum(a.get("party_killed",  {}).values())
        iwp_injured = sum(a.get("party_injured", {}).values())
        iwp_total   = iwp_killed + iwp_injured

        killed_match  = iwp_killed  == int(ccrs_killed)
        injured_match = iwp_injured == int(ccrs_injured)

        if killed_match and injured_match:
            continue   # no discrepancy

        # Classify the type
        types = []
        if not killed_match:
            types.append(
                f"killed: IWP={iwp_killed} vs CCRS={ccrs_killed}"
                + (" (IWP HIGHER — possible duplicates)" if iwp_killed > int(ccrs_killed) else " (IWP LOWER — possible missing IWP rows)")
            )
        if not injured_match:
            types.append(
                f"injured: IWP={iwp_injured} vs CCRS={ccrs_injured}"
                + (" (IWP HIGHER — possible duplicates)" if iwp_injured > int(ccrs_injured) else " (IWP LOWER — possible missing IWP rows)")
            )

        rows.append({
            "collision_id":          cid,
            "report_number":         report_number_map.get(cid, ""),
            "crash_date":            ccrs_datetime_to_date(row.get("Crash Date Time", "") or row.get("CrashDateTime", "")),
            "ccrs_number_killed":    ccrs_killed,
            "ccrs_number_injured":   ccrs_injured,
            "iwp_killed_count":      str(iwp_killed),
            "iwp_injured_count":     str(iwp_injured),
            "iwp_total_casualty_rows": str(iwp_total),
            "discrepancy_type":      " | ".join(types),
            "notes":                 "IWP counts derived from non-witness, non-NoInjury IWP rows only",
        })
    return rows

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert CCRS exports to SWITRS format.")
    parser.add_argument("--crash",   required=True, help="Path to CCRS Crash CSV")
    parser.add_argument("--party",   required=True, help="Path to CCRS Party CSV")
    parser.add_argument("--iwp",     required=True, help="Path to CCRS InjuredWitnessPassenger CSV")
    parser.add_argument("--out-dir",   default="./switrs_output", help="Output directory")
    parser.add_argument("--vc-codes",  default=None,              help="Path to vc_codes_table.csv (optional but recommended)")
    args = parser.parse_args()

    print("Loading CCRS data files...")
    crash_rows = load_csv(args.crash)
    party_rows = load_csv(args.party)
    iwp_rows   = load_csv(args.iwp)
    print(f"  Crash rows:  {len(crash_rows)}")
    print(f"  Party rows:  {len(party_rows)}")
    print(f"  IWP rows:    {len(iwp_rows)}")

    print("Loading VC codes lookup table...")
    vc_lookup = load_vc_codes(args.vc_codes) if args.vc_codes else {}
    if vc_lookup:
        print(f"  Loaded {len(vc_lookup)} VC code entries")
    else:
        print("  No vc_codes file provided — pcf/oaf category fields will be blank")

    print("Building aggregation lookups...")
    agg = build_lookups(party_rows, iwp_rows)

    # Map CollisionId → ReportNumber for joins
    report_number_map = {}
    for row in crash_rows:
        cid = row.get("CollisionId", "").strip() or row.get("Collision Id", "").strip()
        rn  = row.get("Report Number", "").strip() or row.get("ReportNumber", "").strip()
        if cid:
            report_number_map[cid] = rn

    print("Converting tables...")
    crash_rows    = convert_crash(crash_rows, agg, report_number_map, vc_lookup)
    party_out        = convert_party(party_rows, report_number_map, vc_lookup, agg)
    victim_out       = convert_victim(iwp_rows, report_number_map, party_rows)
    unmapped_rows    = build_unmapped_ccrs(crash_rows, party_rows, iwp_rows)
    discrepancy_rows = check_discrepancies(crash_rows, agg, report_number_map)

    out = args.out_dir
    write_csv(f"{out}/crash.csv",            CRASH_FIELDS,     crash_rows)
    write_csv(f"{out}/party.csv",               PARTY_FIELDS,        party_out)
    write_csv(f"{out}/victim.csv",              VICTIM_FIELDS,        victim_out)
    write_csv(f"{out}/unmapped_ccrs_fields.csv", UNMAPPED_FIELDS,    unmapped_rows)
    write_csv(f"{out}/data_quality_log.csv",    DISCREPANCY_FIELDS,  discrepancy_rows)

    print("\nDone. Summary:")
    print(f"  crash.csv            → {len(crash_rows)} rows")
    print(f"  party.csv               → {len(party_out)} rows")
    print(f"  victim.csv              → {len(victim_out)} rows")
    print(f"  unmapped_ccrs_fields.csv→ {len(unmapped_rows)} rows  (CCRS-only fields preserved here)")
    print(f"  data_quality_log.csv    → {len(discrepancy_rows)} rows  (IWP vs crash-header count mismatches)")
    if discrepancy_rows:
        print(f"  ⚠  {len(discrepancy_rows)} collision(s) have IWP casualty counts that don't match NumberKilled/NumberInjured in the crash file.")
        print(f"     See data_quality_log.csv for details.")


if __name__ == "__main__":
    main()
