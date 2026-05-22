# **CCRS ⇄ SWITRS Conversion Scripts: User Guide & Reference**

This repository contains lightweight Python scripts designed to convert traffic crash data between California's two primary crash reporting formats: **SWITRS** (Statewide Integrated Traffic Records System) and **CCRS** (California Crash Reporting System).

These scripts run natively in Python 3.8+ with **zero external library dependencies**, facilitating backward-compatible data analytics, historical comparisons, and modern workflow integration.

## **Table of Contents**

1. [Overview](#1-overview)  
2. [Background: CCRS and SWITRS](#2-background-ccrs-and-switrs)  
3. [CCRS → SWITRS Converter (ccrs\_switrs\_converter.py)](#3-ccrs--switrs-converter-ccrs_switrs_converterpy)  
    * [Command Usage](#31-command-usage)  
    * [Vehicle Code Lookup File (vc\_codes\_table.csv)](#32-vehicle-code-lookup-file-vc_codes_tablecsv)  
    * [Data Quality Diagnostic Log (data\_quality\_log.csv)](#33-data-quality-diagnostic-log-data_quality_logcsv)  
    * [CCRS → SWITRS Field Mapping Specifications](#34-accident-table-field-mappings)  
4. [SWITRS → CCRS Converter (switrs\_ccrs\_converter.py)](#4-switrs--ccrs-converter-switrs_ccrs_converterpy)  
    * [Command Usage](#41-command-usage)  
    * [SWITRS → CCRS Field Mapping Specifications](#42-crash-table-field-mappings)  
    * [Fields Not Recoverable from SWITRS](#45-fields-not-recoverable-from-switrs)  
5. [Limitations & Constraints](#5-limitations)  
6. [Requirements & Setup](#6-requirements-and-setup)  
7. [Support & Updates](#7-support-and-updates)

## **1. Overview**

| Script | Direction | Purpose |
| :---- | :---- | :---- |
| **ccrs\_switrs\_converter.py** | CCRS → SWITRS | Converts modern CCRS raw data exports into SWITRS-compatible CSV files, enabling integration with historical SWITRS analytical models, tools, and databases. |
| **switrs\_ccrs\_converter.py** | SWITRS → CCRS | Converts legacy SWITRS data into contemporary CCRS structures, allowing historical datasets to be loaded directly into CCRS-focused pipelines. |

Both scripts process standard CSV data files and export structured CSV outputs.

## **2. Background: CCRS and SWITRS**

### **2.1 SWITRS**

The **Statewide Integrated Traffic Records System (SWITRS)** is the California Highway Patrol's (CHP) historical crash data format. It organizes collision occurrences into three separate flat tables:

* **Crash** (one row per crash)  
* **Party** (one row per involved party, e.g., driver, pedestrian, bicyclist)  
* **Victim** (one row per injured or killed person)

*Note: SWITRS data is no longer available via the CHP's legacy I-SWITRS portal. Public access is primarily maintained through UC Berkeley's Transportation Injury Mapping System (TIMS). Many local law enforcement agencies maintain archival copies for historical analysis and litigation support.*

### **2.2 CCRS**

The **California Crash Reporting System (CCRS)** is the CHP's modern web platform replacing SWITRS, housing California's crash records from the past ten years. CCRS provides data in three corresponding export tables:

* **Crash** (corresponds to SWITRS crash)  
* **Party** (corresponds to SWITRS party)  
* **InjuredWitnessPassenger (IWP)** (corresponds to SWITRS victim)

CCRS uses distinct field names, altered coding values, and new fields that have no legacy SWITRS equivalent. It also omits various pre-calculated or computed fields that previously existed in SWITRS. Conversion between these formats requires careful schema mapping and value recoding.

## **3. CCRS → SWITRS Converter (ccrs\_switrs\_converter.py)**

This script reads three CCRS CSV data tables and an optional California Vehicle Code lookup table, yielding **five distinct output files**:

| Output File | Content |
| :---- | :---- |
| crash.csv | SWITRS-compatible crash table (one row per crash). |
| party.csv | SWITRS-compatible party table (one row per party). |
| victim.csv | SWITRS-compatible victim table (one row per injured or killed person). |
| unmapped\_ccrs\_fields.csv | Archival file preserving modern CCRS-only fields that do not possess a logical SWITRS equivalent. |
| data\_quality\_log.csv | Diagnostic log flagging collisions where actual IWP rows contradict the crash header's NumberKilled or NumberInjured field declarations. |

### **3.1 Command Usage**

#### **Minimum Usage (Without CVC Lookup):**

python ccrs\_switrs\_converter.py \\  
    \--crash   ccrs\_crash.csv   \\  
    \--party   ccrs\_party.csv   \\  
    \--iwp     ccrs\_iwp.csv     \\  
    \--out-dir ./switrs\_output

#### **Recommended Usage (With CVC Lookup for Violation Categories):**

python ccrs\_switrs\_converter.py \\  
    \--crash     ccrs\_crash.csv     \\  
    \--party     ccrs\_party.csv     \\  
    \--iwp       ccrs\_iwp.csv       \\  
    \--vc-codes  vc\_codes\_table.csv \\  
    \--out-dir   ./switrs\_output

### **3.2 Vehicle Code Lookup File (vc\_codes\_table.csv)**

The vc\_codes\_table.csv file maps raw California Vehicle Code (CVC) section strings to their corresponding two-digit SWITRS violation category codes used in the pcf\_viol\_category and oaf\_viol\_cat fields. 

This lookup table was compiled by UC Berkeley **SafeTREC** by accessing the CVC site at: https://leginfo.legislature.ca.gov/faces/codesTOCSelected.xhtml?tocCode=VEH&tocTitle=+Vehicle+Code+-+VEH. The lookup table attempts to assign violation codes for all the relevant CVC, but is subject to errors. Also the CVC code is not static, so any new codes that are added will not be included in this file. If this file is not supplied during conversion, pcf\_viol\_category and oaf\_viol\_cat will remain empty in the converted output tables.

#### **Column Mapping Definitions:**

* vc\_code (Integer): The base numeric CVC section (e.g., 22107, 23152).  
* sub (String): The subsection letter suffix, or 0 if none exists (e.g., A for 23152A).  
* pcf (String): Two-digit SWITRS pcf\_viol\_category code (e.g., 01, 03, 07, 08, 13).  
* oaf (String): Two-digit SWITRS oaf\_viol\_cat code (e.g., 20, 25, 28, 31, 38).  
* id (Integer): Internal unique row identifier.  
* vc\_code\_full (String): Combined canonical identifier (e.g., 22107, 21658A, 23152A).

#### **Sample Rows:**

| vc_code | sub | pcf | oaf | id | vc_code_full |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 22107 | 0 | 08 | 31 | 216 | 22107 |
| 22350 | 0 | 03 | 25 | 224 | 22350 |
| 21658 | A | 07 | 28 | 154 | 21658A |
| 23152 | A | 01 | 20 | 276 | 23152A |
| 22515 | A | 13 | 38 | 248 | 22515A |

*Category Mapping Examples:* 01 \= Driving Under Influence, 03 \= Unsafe Speed, 07 \= Unsafe Lane Change, 08 \= Improper Turning, 13 \= Hazardous Parking.

The script extracts numeric sections from free-text fields in CCRS (e.g., "VC 22107", "22350 VC", "VC 22450(a)", "21658CVC", "VC 22350 UNSAFE SPEED", "VC 21651(a)(1)") to perform clean matching. Numeric extraction is robust against common transcription patterns.

### **3.3 Data Quality Diagnostic Log (data\_quality\_log.csv)**

Due to inconsistencies that occasionally occur in native CCRS exports, a diagnostic data\_quality\_log.csv is written on every run. It details collisions where row counts computed from the **IWP table** do not align with the crash header's stated NumberKilled and NumberInjured values.

* An empty log (only the header row) denotes complete data integrity.  
* **IWP Count Higher:** Typically indicates the presence of duplicate victim rows within the source CCRS IWP file.  
* **IWP Count Lower:** Indicates that expected injured/killed victim entries are entirely missing from the source IWP file.

#### **Column Structure:**

1. collision\_id: The CCRS-assigned CollisionId.  
2. report\_number: Local agency report tracking number.  
3. crash\_date: Date formatted as YYYYMMDD.  
4. ccrs\_number\_killed / ccrs\_number\_injured: Direct values stated in the CCRS crash header record.  
5. iwp\_killed\_count / iwp\_injured\_count: Computed rows matching Fatal / Non-Fatal codes.  
6. iwp\_total\_casualty\_rows: Combined physical rows containing actionable casualty codes.  
7. discrepancy\_type: Human-readable discrepancy direction (e.g., killed: IWP=9 vs CCRS=1 (IWP HIGHER \- possible duplicates)).  
8. notes: Summary explanation of calculation methodology.

#### **Sample Rows:**

| collision_id | report_number | crash_date | ccrs_killed | ccrs_injured | iwp_killed | iwp_injured | discrepancy_type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 4669308 | 9525-2025-00041 | 20250103 | 1 | 2 | 9 | 2 | killed: IWP=9 vs CCRS=1 (IWP HIGHER - possible duplicates) |
| 4712045 | 1900-2025-00187 | 20250211 | 0 | 3 | 0 | 1 | injured: IWP=1 vs CCRS=3 (IWP LOWER - possible missing IWP rows) |
| 4698120 | 5701-2025-00923 | 20250118 | 2 | 1 | 4 | 1 | killed: IWP=4 vs CCRS=2 (IWP HIGHER - possible duplicates) |

*Note: The converter maintains strict analytical neutrality and **does not modify** the source values. NumberKilled and NumberInjured in the crash output are written exactly as exported from CCRS, even when discrepancies are detected in the IWP table.*

### **3.4 Accident Table Field Mappings**

Below is the structured schema mapping from **CCRS to SWITRS**:

| SWITRS Field | CCRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| case\_id | CollisionId | Direct mapping. |
| accident\_year | Crash Date Time | Year extracted from datetime string. |
| collision\_date | Crash Date Time | Formatted as YYYYMMDD. |
| collision\_time | Collision Time / Crash Date Time | HHMM (24h). If time is 0 and CrashTimeDescription contains 2500 (unknown), writes 2500\. |
| proc\_date | PreparedDate | Formatted as YYYYMMDD (falls back to ModifiedDate). |
| juris | NCIC Code | Direct mapping. |
| cnty\_city\_loc | City Code | Zero-padded to 4 digits (when numeric). |
| day\_of\_week | Day Of Week | Text parsed to 1-7 integer format (Monday=1, Sunday=7). |
| primary\_rd | PrimaryRoad | Handles common column variations and aliases. |
| secondary\_rd | SecondaryRoad | Direct mapping. |
| distance | SecondaryDistance | Converted from miles to feet if SecondaryUnitOfMeasure \= M. |
| direction | SecondaryDirection | Direct mapping. |
| intersection | Derived | "Y" if SecondaryDistance is blank or 0; "N" otherwise. |
| weather\_1 | Weather 1 | First character code extracted (e.g., "Clear" → "A"). |
| weather\_2 | Weather 2 | First character code extracted; defaults to "-" if blank. |
| road\_cond\_1 / \_2 | Road Condition 1/2 | String-matched to SWITRS codes (A-H); defaults to "-" if blank. |
| lighting | LightingCode | First character code extracted. |
| road\_surface | RoadwaySurfaceCode | First character code extracted. |
| control\_device | TrafficControlDeviceCode | First character code extracted. |
| state\_hwy\_ind | IsHighwayRelated | True → "Y", False → "N". |
| tow\_away | IsTowAway | True → "Y", False → "N". |
| collision\_severity | IWP ExtentOfInjuryCode | Worst injury across all related IWP rows (1=Fatal, 2=Severe, 3=Visible, 4=Pain). |
| number\_killed | NumberKilled | Stated value; negative values clamped to 0; blanks default to 0\. |
| number\_injured | NumberInjured | Stated value; negative values clamped to 0; blanks default to 0\. |
| party\_count | Party Table Rows | Dynamically calculated by counting Party rows per CollisionId. |
| primary\_coll\_factor | Primary Collision Factor Code | First character code extracted. |
| pcf\_code\_of\_viol | Primary Collision Factor Violation | "C" (Vehicle Code) when a VC section is detected; else "-". |
| pcf\_viol\_category | Derived via lookup | Derived from vc\_codes\_table.csv using extracted CVC code. |
| pcf\_violation | Primary Collision Factor Violation | Extracted clean numeric CVC section (e.g., 22350). |
| pcf\_viol\_subsection | Primary Collision Factor Violation | Extracted literal suffix letter (e.g., "A" from "23152A"). |
| hit\_and\_run | HitRun | Mapping of "F" (Fatal), "M" (Misdemeanor) to standard codes; else "N". |
| type\_of\_collision | CollisionTypeCode | First character code extracted. |
| mviw | MotorVehicleInvolvedWithCode | First character code extracted. |
| ped\_action | PedestrianActionCode | First character code extracted. |
| special\_cond | Special Condition (text) | "School Bus Collision" → 1, "No Pupils on School Bus" → 3; else 0\. |
| not\_private\_property | Special Condition (text) | "Blank" if "Private Property" exists in text; else "Y". |
| alcohol\_involved | Party SobrietyDrugPhysicalCode1 | "Y" if any party has code B, C, or D; else "N". |
| pedestrian\_accident | Party PartyType | "Y" if any party type is "PEDESTRIAN". |
| bicycle\_accident | Party PartyType | "Y" if any party type is "BICYCLIST". |
| motorcycle\_accident | Party stwd\_vehicle\_type | "Y" if any party has vehicle type C (Motorcycle) or O (Moped). |
| truck\_accident | Party stwd\_vehicle\_type | "Y" if any party has type F (Truck) or G (Truck with Trailer). |
| stwd\_vehtype\_at\_fault | Faulty Party Vehicle Types | CHP towing/towed code logic applied to at-fault party. |
| chp\_vehtype\_at\_fault | Faulty Party Vehicle1TypeId | Zero-padded 2-digit CHP code. |
| chp\_beat\_class | Derived | "1" (CHP Primary) if report matches JURIS-YEAR-XXXXX format; else "0". |
| count\_severe\_inj | IWP ExtentOfInjuryCode | Count of SuspectSerious \+ SevereInactive IWP rows. |
| count\_visible\_inj | IWP ExtentOfInjuryCode | Count of SuspectMinor \+ OtherVisibleInactive IWP rows. |
| count\_complaint\_pain | IWP ExtentOfInjuryCode | Count of PossibleInjury \+ ComplaintOfPainInactive IWP rows. |
| count\_ped\_killed | IWP InjuredPersonType | Count of fatal Pedestrian IWP rows. |
| count\_ped\_injured | IWP InjuredPersonType | Count of injured Pedestrian IWP rows. |
| count\_bicyclist\_killed | IWP InjuredPersonType | Count of fatal Bicyclist IWP rows. |
| count\_bicyclist\_injured | IWP InjuredPersonType | Count of injured Bicyclist IWP rows. |
| count\_mc\_killed | IWP \+ Party Vehicle Type | Count of fatal motorcyclist IWP rows (matching party vehicle type C or O). |
| count\_mc\_injured | IWP \+ Party Vehicle Type | Count of injured motorcyclist IWP rows (matching party vehicle type C or O). |
| postmile | MilepostDistance | Direct mapping. |
| side\_of\_hwy | MilepostDirection | Direct mapping. |
| primary\_ramp | N/A | Always "-" (not captured in CCRS exports). |
| secondary\_ramp | N/A | Always "-" (not captured in CCRS exports). |
| latitude / longitude | Latitude / Longitude | Direct mapping. |
| local\_report\_number | Report Number | Direct mapping. |

### **3.5 Party Table Field Mappings**

| SWITRS Field | CCRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| case\_id | CollisionId | Direct mapping. |
| party\_number | Party Number | Direct mapping. |
| party\_type | PartyType | Normalized text matched to codes 1–6 (Parked Vehicle \= 3). |
| at\_fault | IsAtFault | True → "Y"; False or blank → "N". |
| party\_sex | GenderCode | Leading letter extracted; blank → "-". |
| party\_age | StatedAge | Cleaned integer; blank/missing → 998 (not stated). |
| party\_sobriety | SobrietyDrugPhysicalCode1 | Normalizes to SWITRS codes (A, B, C, D, G, H); blank → "-". |
| party\_drug\_physical | SobrietyDrugPhysicalCode2 | Normalizes to SWITRS codes (E, F, I, H); blank → "-". |
| party\_safety\_equip\_1 | AirbagCode | Leading letter extracted; blank → "-". |
| party\_safety\_equip\_2 | SafetyEquipmentCode | Leading letter extracted; blank → "-". |
| sp\_info\_1 | Special Information | Set to "A" if Hazardous Materials token is detected. |
| sp\_info\_2 | Special Information | Checked for mobile device usage tokens (1/2/3/4/B/C/D); first match wins. |
| sp\_info\_3 | Special Information | Set to "E" if School Bus Related token is detected. |
| oaf\_1 / \_2 | Other Associate Factor | Maps text patterns to SWITRS A–O codes. Refined by Inattention columns. |
| oaf\_violation\_code | Primary Collision Factor Violation | Set to "C" (Vehicle Code) when a VC section is detected. |
| oaf\_viol\_cat | Derived via lookup | Derived from vc\_codes\_table.csv using extracted CVC code. |
| oaf\_viol\_section | Primary Collision Factor Violation | Cleaned numeric CVC section (e.g., 22350); else "-". |
| oaf\_viol\_suffix | Primary Collision Factor Violation | Cleaned alphanumeric suffix letter (e.g., A); else "-". |
| move\_pre\_acc | MovementPrecCollCode | Leading letter extracted. |
| stwd\_vehicle\_type | Vehicle1TypeId \+ V2TypeId | CHP towing/towed rules; falls back to text description checks. |
| chp\_veh\_type\_towing | Vehicle1TypeId | Zero-padded to 2 digits. |
| chp\_veh\_type\_towed | Vehicle2TypeId | Zero-padded to 2 digits. |
| inattention | Inattention | Matches text descriptions to SWITRS codes (A-K). |
| race | RaceCode | Leading letter extracted. |
| party\_number\_killed | Related IWP Rows | Total Fatal IWP rows attributed to this party. |
| party\_number\_injured | Related IWP Rows | Total Injured (non-fatal) IWP rows attributed to this party. |
| vehicle\_year | Vehicle1Year | Direct mapping. |
| vehicle\_make | Vehicle1Make | Direct mapping. |
| dir\_of\_travel | DirectionOfTravel | Extracted leading compass letter (N, S, E, W); else "-". |
| local\_report\_number | Crash Report Number | Joined from Crash table on matching CollisionId. |

### **3.6 Victim Table Field Mappings**

| SWITRS Field | CCRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| case\_id | CollisionId | Direct mapping. |
| party\_number | IWP PartyNumber | Matches the individual to their parent Party ID. |
| victim\_role | InjuredPersonType | Standard text mapped to codes 1–6 (Driver=1, Passenger=2, Pedestrian=3, etc). |
| victim\_sex | Gender / GenderCode | Leading letter extracted (M, F, X, etc.). |
| victim\_age | StatedAge | Cleaned integer; blank/missing → 998 (not stated). |
| victim\_degree\_of\_injury | ExtentOfInjuryCode | CCRS text descriptions mapped to SWITRS integers (Fatal=1, Severe=2, etc.). |
| victim\_seating\_position | SeatPosition | Standard positional values mapped to SWITRS codes (e.g., Driver=1, PassengerRearLeft=A/B/C). |
| victim\_safety\_equip\_1 | IWP AirbagCode | Leading letter extracted. |
| victim\_safety\_equip\_2 | IWP SafetyEquipmentCode | Leading letter extracted. |
| victim\_ejected | Ejected | Map text values to codes: NotEjected=0, FullyEjected=1, PartiallyEjected=2, Unknown=3. |
| local\_report\_number | Crash Report Number | Joined from Crash table on matching CollisionId. |

### **3.7 CCRS-Only Fields (unmapped\_ccrs\_fields.csv)**

These fields from modern CCRS files have no historical SWITRS equivalent. The script archives them inside unmapped\_ccrs\_fields.csv, preserving the raw data and keying it by CollisionId and SourceTable for future reference.

* **Crash Table:** ReportVersion, IsPreliminary, DispatchNotified, HasPhotographs, IsDeleted, JudicialDistrict, PreparedDate, PrimaryCollisionFactorIsCited, PrimaryCollisionPartyNumber, ReviewedDate, IsLocationReferToNarrative, IsAOIOneSameAsLocation, EvidenceNumber, CHP555Version, HasDigitalMediaFiles, ServerCreateTime, ServerModifiedTime.  
* **Party Table:** IsOnDutyEmergencyVehicle, IsHitAndRun, AirbagCode, StreetOrHighwayName, SpeedLimit, DriverLicenseClass, DriverLicenseStateCode, Vehicle1Color, Lane, ThruLane, TotalLane, IsDREConducted, VehicleBodyTypeTextDescription, VehicleMakeTextDescription, SpecialPurposeVehicleIndicatorCode, PartyTypeTextDescription, InattentionTextDescription, OtherAssociateFactorTextDescription, DamageCodeTextDescription, DamageLocationDescription, DriveByShootingRelated, DrivenBySchoolEmpioyee, IsIncidentReportedToADA, VehicleInvolvedWithTextDescription, SobrietyTextDescription, SafetyEquipmentTextDescription, ProcessingStatusTextDescription.  
* **IWP Table:** Race, IsWitnessOnly, IsPassengerOnly, AirbagCode.

## **4. SWITRS → CCRS Converter (switrs\_ccrs\_converter.py)**

This script processes legacy SWITRS flat files and generates contemporary CCRS-structured tables.

### **4.1 Command Usage**

python switrs\_ccrs\_converter.py \\  
    \--crash   crash.csv  \\  
    \--party   party.csv  \\  
    \--victim  victim.csv \\  
    \--out-dir ./ccrs\_output

### **4.2 Crash Table Field Mappings**

Below is the structured schema mapping from **SWITRS to CCRS**:

| CCRS Field | SWITRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| CollisionId | case\_id | Direct mapping. |
| Report Number | local\_report\_number | Direct mapping. |
| NCIC Code | juris | Direct mapping. |
| Crash Date Time | collision\_date \+ \_time | Recombined into a standard timestamp string. |
| City Code | cnty\_city\_loc | Zero-padded to 4 digits. |
| Day Of Week | day\_of\_week | 1–7 integer formatted back to standard text name. |
| Primary Collision Factor Code | primary\_coll\_factor | Direct letter code mapping. |
| Collision Type Code | type\_of\_collision | Direct letter code mapping. |
| Weather 1 / Weather 2 | weather\_1 / weather\_2 | Direct letter codes. |
| Road Condition 1/2 | road\_cond\_1 / \_2 | Letter codes mapped to descriptive text. |
| LightingCode | lighting | Letter code mapped to descriptive text. |
| RoadwaySurfaceCode | road\_surface | Letter code mapped to descriptive text. |
| TrafficControlDeviceCode | control\_device | Letter code mapped to descriptive text. |
| IsHighwayRelated | state\_hwy\_ind | "Y" → True, "N" → False. |
| IsTowAway | tow\_away | "Y" → True, "N" → False. |
| HitRun | hit\_and\_run | "F" / "M" / "N" mapped to CCRS equivalent strings. |
| NumberKilled / NumberInjured | number\_killed / \_injured | Direct mapping. |
| PedestrianActionCode | ped\_action | Direct letter code mapping. |
| MotorVehicleInvolvedWithCode | mviw | Direct letter code mapping. |
| Latitude / Longitude | latitude / longitude | Direct mapping. |
| SecondaryDirection | direction | Direct mapping. |
| SecondaryDistance | distance | Direct distance value (feet; UOM is hardcoded to "F"). |

### **4.3 Party Table Field Mappings**

| CCRS Field | SWITRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| CollisionId | case\_id | Direct mapping. |
| Party Number | party\_number | Direct mapping. |
| PartyType | party\_type | Code 1–6 converted to text (DRIVER, PEDESTRIAN, BICYCLIST, etc.). |
| IsAtFault | at\_fault | "Y" → True, "N" → False. |
| GenderCode | party\_sex | Direct letter mapped; "-" becomes blank. |
| StatedAge | party\_age | Direct integer mapping; 998 mapped to blank. |
| SobrietyDrugPhysicalCode1 | party\_sobriety | Direct code mapping. |
| SobrietyDrugPhysicalCode2 | party\_drug\_physical | Direct code mapping. |
| AirbagCode | party\_safety\_equip\_1 | Direct code mapping. |
| SafetyEquipmentCode | party\_safety\_equip\_2 | Direct code mapping. |
| Special Information | sp\_info\_1 \+ sp\_info\_2 | Tokens (A, 1-4, B/C/D) recombined into space-separated string. |
| DirectionOfTravel | dir\_of\_travel | Direct compass letter mapping. |
| MovementPrecCollCode | move\_pre\_acc | Direct code mapping. |
| Vehicle1TypeId | chp\_veh\_type\_towing | Direct code mapping. |
| Vehicle2TypeId | chp\_veh\_type\_towed | Direct code mapping. |
| Vehicle1Year | vehicle\_year | Direct mapping. |
| Vehicle1Make | vehicle\_make | Direct mapping. |
| RaceCode | race | Direct letter mapping. |

### **4.4 InjuredWitnessPassenger (IWP) Table Field Mappings**

| CCRS Field | SWITRS Source Field | Conversion Logic / Notes |
| :---- | :---- | :---- |
| CollisionId | case\_id | Direct mapping. |
| PartyNumber | party\_number | Direct mapping. |
| StatedAge | victim\_age | Direct integer mapping; 998 mapped to blank. |
| Gender | victim\_sex | Direct letter mapped. |
| ExtentOfInjuryCode | victim\_degree\_of\_injury | Numeric code converted to CCRS text (Fatal, SuspectSerious, etc.). |
| InjuredPersonType | victim\_role | Code 1–6 converted to text (DRIVER, PASSENGER, PEDESTRIAN, etc.). |
| SeatPosition | victim\_seating\_position | Direct mapping to CCRS textual seat assignments. |
| AirbagCode | victim\_safety\_equip\_1 | Direct code mapping. |
| SafetyEquipmentCode | victim\_safety\_equip\_2 | Direct code mapping. |
| Ejected | victim\_ejected | Code 0–3/"-" converted to descriptive strings. |
| IsWitnessOnly | N/A | Always False (SWITRS victims are never witnesses). |
| IsPassengerOnly | victim\_role | Set to True if role is 2 (Passenger); else False. |

### **4.5 Fields Not Recoverable from SWITRS**

Due to differences in the information captured by the two systems, some CCRS fields cannot be populated using SWITRS source files alone. These fields are left **blank/null** in the generated output:

* **Headers:** ReportVersion, IsPreliminary, DispatchNotified, HasPhotographs, HasDigitalMediaFiles, CHP555Version.  
* **Investigation Details:** JudicialDistrict, EvidenceNumber, IsLocationReferToNarrative, IsAOIOneSameAsLocation.  
* **Licensing & Speed:** SpeedLimit, DriverLicenseClass, DriverLicenseStateCode, IsDREConducted.  
* **Medical Transport:** SeatPositionOther, TransportedBy, TakenTo, ExtentOfInjury (textual description is blank; the numerical code ExtentOfInjuryCode is populated).

## **5. Limitations**

Users should be aware of the following programmatic limitations when using these converters:

* **CHP Beat Tracking (chp\_beat\_type / beat\_type):** This data is not present in raw CCRS files and requires a custom CHP beat lookup reference mapping. These fields will be blank in SWITRS output.  
* **Special Condition Codes (2, 5, 6):** SWITRS parameters 2 (State University), 5 (Vista Point or Rest Area), and 6 (Other Public Access) are derived from beat numbers. Since beat data is omitted from CCRS, these conditions cannot be reliably back-converted.  
* **Officer and Financial Data:** Officer IDs (officer\_id) and financial responsibility indicators (finan\_respons) are entirely absent from CCRS exports.  
* **Ramp Identifiers:** Both primary\_ramp and secondary\_ramp default to "-" (not stated), as these are manually input by legacy CHP clerks and do not exist in digital CCRS databases.  
* **Deprecated SWITRS Metrics:** Caltrans administrative values (caltrans\_county, caltrans\_district, state\_route, route\_suffix, postmile\_prefix, location\_type, ramp\_intersection, chp\_road\_type) are not available in CCRS exports and are omitted from output.  
* **Reverse Mapping sp\_info\_3:** During SWITRS → CCRS conversion, sp\_info\_3 (School Bus Related, code E) is omitted. Only sp\_info\_1 (Hazardous Materials) and sp\_info\_2 (Cell Phone codes 1/2/3/4/B/C/D) are encoded into the Special Information field.  
* **Derived Casualty Columns:** Metric columns such as count\_mc\_killed or count\_ped\_injured are calculated directly from IWP/Victim records. If the source data contains duplicate records (refer to the data quality log), these counts may exceed stated casualty figures.

## **6. Requirements and Setup**

* **Python Runtime:** Python 3.8 or later (standard library only).  
* **Encoding:** Input files must be formatted as **UTF-8** or **UTF-8-BOM** CSV files.  
* **Header Matching:** Column header parsing handles capitalization and spaces flexibly, incorporating several common aliases per field.  
* **Memory Constraints:** Both converters load entire datasets into system RAM to map cross-table relations efficiently. A batch of 500,000 crash records and associated sub-tables requires **2 to 4 GB** of available memory.

## **7. Support and Updates**

As California's crash data structures mature, field values and formats may change. If a converted field is unexpectedly blank:

1. Verify if your CSV files contain non-standard header column names. Check the FIELD MAPPING REFERENCE block at the top of the python scripts.  
2. Ensure you have provided vc\_codes\_table.csv to successfully populate violation fields.  
3. Check unmapped\_ccrs\_fields.csv to identify new or changed fields that might require logic additions.  
4. Review lookup dictionary arrays in the python scripts (such as PARTY\_TYPE\_MAP, ROAD\_CONDITION\_PREFIXES, OAF\_TEXT\_MAP, etc.) to verify if new code mappings need to be appended.

**Reference Documentation:**

* CHP Collision Investigation Manual (HPM 110.5)  
* SWITRS Data Dictionary (Current as of 4/26/2022)  
* SWITRS Raw Data Tables Excel Workbook
* California Vehicle Code 
