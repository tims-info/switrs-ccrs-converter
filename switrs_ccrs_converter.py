"""
SWITRS → CCRS Format Converter
================================
Converts legacy SWITRS-format CSV files into the California Crash Reporting
System (CCRS) raw data export format.

SWITRS tables:  crash, party, victim
CCRS tables:    Crash, Party, InjuredWitnessPassenger (IWP)

Usage:
    python switrs_ccrs_converter.py \
        --crash  switrs_crash.csv \
        --party     switrs_party.csv \
        --victim    switrs_victim.csv \
        --out-dir   ./ccrs_output

    Produces:
        ccrs_output/ccrs_crash.csv
        ccrs_output/ccrs_party.csv
        ccrs_output/ccrs_iwp.csv

Key SWITRS -> CCRS field notes:
  Crash:  case_id                 -> CollisionId
          local_report_number     -> Report Number
          juris                   -> NCIC Code
          collision_date+time     -> Crash Date Time (M/D/YYYY H:MM:SS AM/PM, no leading zeros)
          collision_time          -> Collision Time  (stripped leading zeros; 2500 passed through)
          day_of_week             -> Day of Week     (1-7 -> Monday-Sunday)
          reporting_district      -> ReportingDistrict only; ReportingDistrictCode left blank
          cnty_city_loc           -> CityCode, City Name, County Code, City Is Incorporated
                                     (resolved from embedded cnty_city_loc table)
          weather_1/_2            -> Weather 1/2 (description only, no code prefix)
          state_hwy_ind           -> IsHighwayRelated (Y->True / N->False)
          tow_away                -> IsTowAway
          hit_and_run             -> HitRun  (F/M pass through; N -> blank)
          type_of_collision       -> Collision Type Code + Collision Type Description
                                     (description has no code prefix)
          mviw                    -> MotorVehicleInvolvedWithCode + Desc (no code prefix)
          ped_action              -> PedestrianActionCode + PedestrianActionDesc (no code prefix)
          road_surface            -> RoadwaySurfaceCode (description only, no code prefix)
          road_cond_1/_2          -> Road Condition 1/2 (description only, no code prefix)
          lighting                -> LightingCode + LightingDescription (no code prefix)
          control_device          -> TrafficControlDeviceCode (description only, no code prefix)
          primary_coll_factor     -> PrimaryCollisionFactorCode + Description (no code prefix)
          postmile / side_of_hwy  -> MilepostDistance / MilepostDirection
          proc_date               -> PreparedDate (same M/D/YYYY H:MM:SS AM/PM format)
  Party:  party_type (1-6)        -> Party Type (code -> text)
          at_fault (Y/N)          -> IsAtFault (True/False)
          party_sex               -> GenderCode + GenderDescription (two columns)
          party_age               -> StatedAge (998 -> blank)
          party_sobriety          -> SobrietyDrugPhysicalCode1 + SobrietyDrugPhysicalDescription1
          party_drug_physical     -> SobrietyDrugPhysicalCode2 + SobrietyDrugPhysicalDescription2
          party_safety_equip_1    -> AirbagCode + AirBagCodeDescription
          party_safety_equip_2    -> SafetyEquipmentCode + SafetyEquipmentDescription
          move_pre_acc            -> MovementPrecCollCode + MovementPrecCollDesc
                                     (description has no code prefix; '-' -> both blank)
          oaf_1 / oaf_2           -> Other Associate Factor (joined with ' / ')
          race                    -> RaceCode + RaceDesc (two columns)
          inattention             -> Inattention
          sp_info_1/2/3           -> Special Information (recombined)
  Victim: victim_role (1-6)       -> InjuredPersonType (code -> text)
          victim_sex              -> Gender + Gender Desc (two columns)
          victim_age              -> StatedAge (998 -> blank)
          victim_degree_of_injury -> ExtentOfInjury (code -> text)
          victim_safety_equip_1   -> AirbagCode + AirBagCodeDescription
          victim_safety_equip_2   -> SafetyEquipmentCode + SafetyEquipmentDescription
          victim_ejected          -> Ejected (description only, no code prefix)
"""

import argparse
import csv
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# EMBEDDED CITY / COUNTY LOOKUP TABLE
# Source: SWITRS_Raw_Data_Tables.xlsx -- cnty_city_loc sheet
# ---------------------------------------------------------------------------

_CNTY_CITY_LOC_RAW = [
    (100, 'Alameda County'), (101, 'Alameda'), (102, 'Albany'),
    (103, 'Berkeley'), (104, 'Emeryville'), (105, 'Fremont'),
    (106, 'Hayward'), (107, 'Livermore'), (108, 'Newark'),
    (109, 'Oakland'), (110, 'Piedmont'), (111, 'Pleasanton'),
    (112, 'San Leandro'), (113, 'Union City'), (115, 'CSU Hayward'),
    (122, 'UC Livermore Lab'), (141, 'Oakland International Airport'),
    (197, 'UC Berkeley'), (198, 'Dublin'), (200, 'Alpine'),
    (300, 'Amador County'), (301, 'Amador City'), (302, 'Ione'),
    (303, 'Jackson'), (304, 'Plymouth'), (305, 'Sutter Creek'),
    (400, 'Butte County'), (401, 'Biggs'), (402, 'Chico'),
    (403, 'Gridley'), (404, 'Oroville'), (405, 'Paradise'),
    (407, 'Northern Butte Dist'), (497, 'CSU Chico'),
    (500, 'Calaveras'), (501, 'Angels Camp'), (503, 'Calaveras Park Dist'),
    (600, 'Colusa'), (601, 'Colusa'), (602, 'Williams'),
    (700, 'Contra Costa County'), (701, 'Antioch'), (702, 'Brentwood'),
    (703, 'Clayton'), (704, 'Concord'), (705, 'El Cerrito'),
    (706, 'Hercules'), (707, 'Pinole'), (708, 'Pittsburg'),
    (709, 'Pleasant Hill'), (710, 'Richmond'), (711, 'San Pablo'),
    (712, 'Walnut Creek'), (713, 'Kensington'), (714, 'Martinez'),
    (715, 'Lafayette'), (716, 'Moraga'), (734, 'Oakley'),
    (790, 'Danville'), (791, 'San Ramon'), (792, 'Orinda'),
    (800, 'Del Norte'), (801, 'Crescent City'),
    (900, 'El Dorado'), (901, 'Placerville'), (902, 'South Lake Tahoe'),
    (1000, 'Fresno County'), (1001, 'Clovis'), (1002, 'Coalinga'),
    (1003, 'Firebaugh'), (1004, 'Fowler'), (1005, 'Fresno'),
    (1006, 'Huron'), (1007, 'Kerman'), (1008, 'Kingsburg'),
    (1009, 'Mendota'), (1010, 'Orange Cove'), (1011, 'Parlier'),
    (1012, 'Reedley'), (1013, 'Sanger'), (1014, 'San Joaquin'),
    (1015, 'Selma'), (1030, 'San Joaquin Vly Dist'), (1097, 'CSU Fresno'),
    (1100, 'Glenn'), (1101, 'Orland'), (1102, 'Willows'),
    (1200, 'Humboldt'), (1201, 'Arcata'), (1202, 'Blue Lake'),
    (1203, 'Eureka'), (1204, 'Ferndale'), (1205, 'Fortuna'),
    (1206, 'Trinidad'), (1207, 'Rio Dell'), (1208, 'Humboldt State Univ'),
    (1211, 'No Cst Redwood Dist'),
    (1300, 'Imperial'), (1301, 'Brawley'), (1302, 'Calexico'),
    (1303, 'Calipatria'), (1304, 'El Centro'), (1305, 'Holtville'),
    (1306, 'Imperial'), (1307, 'Westmorland'),
    (1400, 'Inyo'), (1401, 'Bishop'),
    (1500, 'Kern County'), (1501, 'Arvin'), (1502, 'Bakersfield'),
    (1503, 'Delano'), (1504, 'Maricopa'), (1505, 'Mcfarland'),
    (1506, 'Ridgecrest'), (1507, 'Shafter'), (1508, 'Taft'),
    (1509, 'Tehachapi'), (1510, 'Wasco'), (1511, 'California City'),
    (1512, 'CSU Bakersfield'), (1513, 'China Lake'),
    (1515, 'Bear Valley Springs'),
    (1600, 'Kings County'), (1601, 'Corcoran'), (1602, 'Hanford'),
    (1603, 'Lemoore'), (1690, 'Avenal'),
    (1700, 'Lake'), (1701, 'Lakeport'), (1702, 'Clearlake'),
    (1800, 'Lassen'), (1801, 'Susanville'),
    (1900, 'Los Angeles County'), (1901, 'Alhambra'), (1902, 'Arcadia'),
    (1903, 'Artesia'), (1904, 'Avalon'), (1905, 'Azusa'),
    (1906, 'Baldwin Park'), (1907, 'Bell'), (1908, 'Bellflower'),
    (1909, 'Bell Gardens'), (1910, 'Beverly Hills'), (1911, 'Bradbury'),
    (1912, 'Burbank'), (1913, 'Claremont'), (1914, 'Commerce'),
    (1915, 'Compton'), (1916, 'Covina'), (1917, 'Cudahy'),
    (1918, 'Culver City'), (1919, 'Cerritos'), (1920, 'Downey'),
    (1921, 'Duarte'), (1922, 'El Monte'), (1923, 'El Segundo'),
    (1924, 'Gardena'), (1925, 'Glendale'), (1926, 'Glendora'),
    (1927, 'Hawaiian Gardens'), (1928, 'Hawthorne'),
    (1929, 'Hermosa Beach'), (1930, 'Hidden Hills'),
    (1931, 'Huntington Park'), (1932, 'Industry'), (1933, 'Inglewood'),
    (1934, 'Irwindale'), (1935, 'Lakewood'), (1936, 'La Mirada'),
    (1937, 'La Puente'), (1938, 'La Verne'), (1939, 'Lawndale'),
    (1940, 'Lomita'), (1941, 'Long Beach'), (1942, 'Los Angeles'),
    (1943, 'Lynwood'), (1944, 'Manhattan Beach'), (1945, 'Maywood'),
    (1946, 'Monrovia'), (1947, 'Montebello'), (1948, 'Monterey Park'),
    (1949, 'Norwalk'), (1950, 'Palmdale'), (1951, 'Palos Verdes Est'),
    (1952, 'Paramount'), (1953, 'Pasadena'), (1954, 'Pico Rivera'),
    (1955, 'Pomona'), (1956, 'Redondo Beach'), (1957, 'Rolling Hills'),
    (1958, 'Rolling Hills Est'), (1959, 'Rosemead'), (1960, 'San Dimas'),
    (1961, 'San Fernando'), (1962, 'San Gabriel'), (1963, 'San Marino'),
    (1964, 'Santa Fe Springs'), (1965, 'Santa Monica'),
    (1966, 'Sierra Madre'), (1967, 'Signal Hill'),
    (1968, 'South El Monte'), (1969, 'South Gate'),
    (1970, 'South Pasadena'), (1971, 'Temple City'), (1972, 'Torrance'),
    (1973, 'Vernon'), (1974, 'Walnut'), (1975, 'West Covina'),
    (1976, 'Whittier'), (1977, 'Carson'), (1978, 'Cal Poly Pomona'),
    (1979, 'West Hollywood'), (1980, 'Rancho Palos Verdes'),
    (1981, 'CSU Dominguez Hills'), (1982, 'CSU Long Beach'),
    (1983, 'CSU Los Angeles'), (1984, 'CSU Northridge'),
    (1985, 'Santa Clarita'), (1988, 'Port of Los Angeles'),
    (1989, 'Calabasas'), (1990, 'Diamond Bar'),
    (1991, 'La Canada-Flintridge'), (1992, 'Lancaster'),
    (1993, 'Westlake Village'), (1994, 'Agoura Hills'), (1995, 'Malibu'),
    (1997, 'UC Los Angeles'), (1999, 'La Habra Heights'),
    (2000, 'Madera'), (2001, 'Chowchilla'), (2002, 'Madera'),
    (2100, 'Marin'), (2101, 'Belvedere'), (2102, 'Corte Madera'),
    (2103, 'Fairfax'), (2104, 'Larkspur'), (2105, 'Mill Valley'),
    (2106, 'Novato'), (2107, 'Ross'), (2108, 'San Anselmo'),
    (2109, 'San Rafael'), (2110, 'Sausalito'), (2111, 'Tiburon'),
    (2114, 'Marin Park Dist'),
    (2200, 'Mariposa'),
    (2300, 'Mendocino County'), (2301, 'Fort Bragg'), (2302, 'Point Arena'),
    (2303, 'Ukiah'), (2304, 'Willits'),
    (2400, 'Merced'), (2401, 'Atwater'), (2402, 'Dos Palos'),
    (2403, 'Gustine'), (2404, 'Livingston'), (2405, 'Los Banos'),
    (2406, 'Merced'), (2410, 'Four Rivers Pk Dist'), (2412, 'UC Merced'),
    (2500, 'Modoc'), (2501, 'Alturas'),
    (2600, 'Mono'), (2601, 'Mammoth Lakes'),
    (2700, 'Monterey'), (2701, 'Carmel'), (2702, 'Del Rey Oaks'),
    (2703, 'Gonzales'), (2704, 'Greenfield'), (2705, 'King City'),
    (2706, 'Monterey'), (2707, 'Pacific Grove'), (2708, 'Salinas'),
    (2709, 'Sand City'), (2710, 'Seaside'), (2711, 'Soledad'),
    (2712, 'Marina'), (2717, 'Monterey Park Dist'), (2719, 'CSU Monterey Bay'),
    (2800, 'Napa County'), (2801, 'Calistoga'), (2802, 'Napa'),
    (2803, 'Saint Helena'), (2804, 'Yountville'), (2805, 'American Canyon'),
    (2900, 'Nevada County'), (2901, 'Grass Valley'), (2902, 'Nevada City'),
    (2908, 'Truckee'),
    (3000, 'Orange County'), (3001, 'Anaheim'), (3002, 'Brea'),
    (3003, 'Buena Park'), (3004, 'Costa Mesa'), (3005, 'Cypress'),
    (3006, 'La Palma'), (3007, 'Fountain Valley'), (3008, 'Fullerton'),
    (3009, 'Garden Grove'), (3010, 'Huntington Beach'),
    (3011, 'Laguna Beach'), (3012, 'La Habra'), (3013, 'Los Alamitos'),
    (3014, 'Newport Beach'), (3015, 'Orange'), (3016, 'Placentia'),
    (3017, 'San Clemente'), (3018, 'San Juan Capistrano'),
    (3019, 'Santa Ana'), (3020, 'Seal Beach'), (3021, 'Stanton'),
    (3022, 'Tustin'), (3023, 'Villa Park'), (3024, 'Westminster'),
    (3025, 'Yorba Linda'), (3026, 'Irvine'), (3027, 'CSU Fullerton'),
    (3028, 'Mission Viejo'), (3029, 'Dana Point'),
    (3032, 'Orange Coast Pk Dist'), (3040, 'Laguna Niguel'),
    (3045, 'Laguna Hills'), (3048, 'Rcho Snta Margarita'),
    (3049, 'Aliso Viejo'), (3050, 'Lake Forest'), (3051, 'Laguna Woods'),
    (3096, 'Irvine Valley Clg'), (3097, 'UC Irvine'),
    (3100, 'Placer County'), (3101, 'Auburn'), (3102, 'Colfax'),
    (3103, 'Lincoln'), (3104, 'Rocklin'), (3105, 'Roseville'),
    (3106, 'Loomis'), (3107, 'Sierra Park Dist'), (3111, 'Sierra College'),
    (3200, 'Plumas County'), (3201, 'Portola'),
    (3300, 'Riverside County'), (3301, 'Banning'), (3302, 'Beaumont'),
    (3303, 'Blythe'), (3305, 'Coachella'), (3306, 'Desert Hot Springs'),
    (3307, 'Lake Elsinore'), (3308, 'Hemet'), (3309, 'Indio'),
    (3310, 'Norco'), (3311, 'Palm Springs'), (3312, 'Perris'),
    (3313, 'Riverside'), (3314, 'San Jacinto'), (3315, 'Corona'),
    (3316, 'Indian Wells'), (3317, 'Rancho Mirage'), (3318, 'Palm Desert'),
    (3324, 'Los Lagos Park Dist'), (3325, 'Cathedral City'),
    (3335, 'Temecula'), (3336, 'Calimesa'), (3337, 'Canyon Lake'),
    (3341, 'Menifee'), (3342, 'Murrieta'), (3343, 'Wildomar'),
    (3344, 'Eastvale'), (3345, 'Jurupa Valley'), (3392, 'La Quinta'),
    (3394, 'Moreno Valley'), (3397, 'UC Riverside'),
    (3400, 'Sacramento County'), (3401, 'Folsom'), (3402, 'Galt'),
    (3403, 'Isleton'), (3404, 'Sacramento'), (3408, 'CSU Sacramento'),
    (3412, 'American Riv Pk Dist'), (3422, 'Gold Rush Park Dist'),
    (3433, 'Twin Cities Pk Dist'), (3450, 'Elk Grove'),
    (3490, 'Rancho Cordova'), (3496, 'Citrus Heights'),
    (3497, 'UC Davis Medical Center'),
    (3500, 'San Benito'), (3501, 'Hollister'), (3502, 'San Juan Bautista'),
    (3504, 'Hollister Hills Park'),
    (3600, 'San Bernardino County'), (3601, 'Barstow'), (3602, 'Chino'),
    (3603, 'Colton'), (3604, 'Fontana'), (3605, 'Montclair'),
    (3606, 'Needles'), (3607, 'Ontario'), (3608, 'Redlands'),
    (3609, 'Rialto'), (3610, 'San Bernardino'), (3611, 'Upland'),
    (3612, 'Victorville'), (3613, 'Adelanto'), (3614, 'CSU San Bernardino'),
    (3615, 'Loma Linda'), (3616, 'Rancho Cucamonga'),
    (3617, 'Twentynine Palms'), (3618, 'Highland'), (3619, 'Hesperia'),
    (3621, 'Apple Valley'), (3630, 'Chino Hills'), (3631, 'Yucca Valley'),
    (3640, 'Yucaipa'), (3680, 'Big Bear Lake'), (3690, 'Grand Terrace'),
    (3700, 'San Diego County'), (3701, 'Carlsbad'), (3702, 'Chula Vista'),
    (3703, 'Coronado'), (3704, 'Del Mar'), (3705, 'El Cajon'),
    (3706, 'Escondido'), (3707, 'Imperial Beach'), (3708, 'La Mesa'),
    (3709, 'National City'), (3710, 'Oceanside'), (3711, 'San Diego'),
    (3712, 'San Marcos'), (3713, 'Vista'), (3714, 'San Diego State Univ'),
    (3715, 'San Diego Harbor'), (3720, 'Lemon Grove'),
    (3722, 'Colorado Desert Park'), (3724, 'Ocotillo Wls Pk Dist'),
    (3725, 'San Diego Pk Dist'), (3780, 'Poway'), (3781, 'Santee'),
    (3782, 'Encinitas'), (3783, 'Solana Beach'), (3797, 'UC San Diego'),
    (3801, 'San Francisco'), (3803, 'San Francisco State'),
    (3897, 'UC San Francisco'),
    (3900, 'San Joaquin County'), (3901, 'Escalon'), (3902, 'Lodi'),
    (3903, 'Manteca'), (3904, 'Ripon'), (3905, 'Stockton'),
    (3906, 'Tracy'), (3908, 'SJ Delta Comm Coll Dist'), (3920, 'Lathrop'),
    (4000, 'San Luis Obispo'), (4001, 'Arroyo Grande'),
    (4002, 'Grover Beach'), (4003, 'Morro Bay'), (4004, 'Paso Robles'),
    (4005, 'Pismo Beach'), (4006, 'San Luis Obispo'),
    (4007, 'Cal Poly Slo'), (4008, 'Atascadero'),
    (4012, 'San Simeon Park Dist'), (4013, 'S L Obispo Cst Dist'),
    (4014, 'Pismo Dunes Pk Dist'),
    (4100, 'San Mateo County'), (4101, 'Atherton'), (4102, 'Belmont'),
    (4103, 'Brisbane'), (4104, 'Burlingame'), (4105, 'Colma'),
    (4106, 'Daly City'), (4107, 'Half Moon Bay'), (4108, 'Hillsborough'),
    (4109, 'Menlo Park'), (4110, 'Millbrae'), (4111, 'Pacifica'),
    (4112, 'Portola Valley'), (4113, 'Redwood City'), (4114, 'San Bruno'),
    (4115, 'San Carlos'), (4116, 'San Mateo'),
    (4117, 'South San Francisco'), (4118, 'Woodside'),
    (4119, 'Broadmoor'), (4120, 'Foster City'),
    (4125, 'San Francisco International Airport'),
    (4126, 'Bay Area Park Dist'), (4127, 'East Palo Alto'),
    (4200, 'Santa Barbara County'), (4201, 'Guadalupe'), (4202, 'Lompoc'),
    (4203, 'Santa Barbara'), (4204, 'Santa Maria'),
    (4205, 'Carpinteria'), (4206, 'Solvang'), (4212, 'Buellton'),
    (4214, 'Goleta'), (4297, 'UC Santa Barbara'),
    (4300, 'Santa Clara County'), (4302, 'Campbell'), (4303, 'Cupertino'),
    (4304, 'Gilroy'), (4305, 'Los Altos'), (4306, 'Los Altos Hills'),
    (4307, 'Los Gatos'), (4308, 'Milpitas'), (4309, 'Monte Sereno'),
    (4310, 'Morgan Hill'), (4311, 'Mountain View'), (4312, 'Palo Alto'),
    (4313, 'San Jose'), (4314, 'Santa Clara'), (4315, 'Saratoga'),
    (4316, 'Sunnyvale'), (4317, 'San Jose State Univ'),
    (4320, 'Sj Evrgreen Comm Clg'),
    (4400, 'Santa Cruz'), (4401, 'Capitola'), (4402, 'Santa Cruz'),
    (4403, 'Watsonville'), (4404, 'Scotts Valley'),
    (4408, 'Santa Cruz Pk Dist'), (4497, 'UC Santa Cruz'),
    (4500, 'Shasta County'), (4501, 'Anderson'), (4502, 'Redding'),
    (4580, 'Shasta Lake'),
    (4600, 'Sierra County'), (4601, 'Loyalton'),
    (4700, 'Siskiyou County'), (4701, 'Dorris'), (4702, 'Dunsmuir'),
    (4703, 'Etna'), (4704, 'Fort Jones'), (4705, 'Montague'),
    (4706, 'Mount Shasta'), (4707, 'Tulelake'), (4708, 'Weed'),
    (4709, 'Yreka'), (4710, 'Lake Shastina'),
    (4800, 'Solano'), (4801, 'Benicia'), (4802, 'Dixon'),
    (4803, 'Fairfield'), (4804, 'Rio Vista'), (4805, 'Suisun City'),
    (4806, 'Vacaville'), (4807, 'Vallejo'),
    (4900, 'Sonoma County'), (4901, 'Cloverdale'), (4902, 'Cotati'),
    (4903, 'Healdsburg'), (4904, 'Rohnert Park'), (4905, 'Santa Rosa'),
    (4906, 'Sebastopol'), (4907, 'Sonoma'), (4908, 'Petaluma'),
    (4909, 'Sonoma State Univ'), (4911, 'Silverado Park Dist'),
    (4912, 'Russ Riv Mndcno Dist'), (4914, 'Santa Rosa Campus Pd'),
    (4980, 'Windsor'),
    (5000, 'Stanislaus'), (5001, 'Ceres'), (5002, 'Modesto'),
    (5003, 'Newman'), (5004, 'Oakdale'), (5005, 'Patterson'),
    (5006, 'Riverbank'), (5007, 'Turlock'), (5008, 'Waterford'),
    (5009, 'Hughson'), (5010, 'CSC Stanislaus'),
    (5100, 'Sutter County'), (5101, 'Live Oak'), (5102, 'Yuba City'),
    (5200, 'Tehama'), (5201, 'Corning'), (5202, 'Red Bluff'),
    (5203, 'Tehama'),
    (5300, 'Trinity'),
    (5400, 'Tulare'), (5401, 'Dinuba'), (5402, 'Exeter'),
    (5403, 'Farmersville'), (5404, 'Lindsay'), (5405, 'Porterville'),
    (5406, 'Tulare'), (5407, 'Visalia'), (5408, 'Woodlake'),
    (5500, 'Tuolumne'), (5501, 'Sonora'),
    (5600, 'Ventura County'), (5601, 'Camarillo'), (5602, 'Fillmore'),
    (5603, 'Ojai'), (5604, 'Oxnard'), (5605, 'Port Hueneme'),
    (5606, 'Santa Paula'), (5607, 'Thousand Oaks'), (5608, 'Ventura'),
    (5609, 'Simi Valley'), (5613, 'Angeles Park Dist'),
    (5615, 'Channel Cst Pk Dist'), (5617, 'Hungry Vly Pk Dist'),
    (5622, 'CSU Channel Islands'), (5690, 'Moorpark'),
    (5700, 'Yolo'), (5701, 'Davis'), (5702, 'Winters'),
    (5703, 'Woodland'), (5704, 'West Sacramento'), (5797, 'UC Davis'),
    (5800, 'Yuba'), (5801, 'Marysville'), (5802, 'Wheatland'),
]

CNTY_CITY_LOOKUP = {code: desc for code, desc in _CNTY_CITY_LOC_RAW}

# ---------------------------------------------------------------------------
# CHP VEHICLE TYPE LOOKUP TABLE
# Source: SWITRS_Raw_Data_Tables.xlsx -- CHP_vehicle_type sheet
# Keys are zero-padded 2-digit strings matching chp_veh_type_towing/towed values.
# ---------------------------------------------------------------------------

CHP_VEHICLE_TYPE_LOOKUP = {
    "-":  "VEHICLE TYPE LEFT BLANK",
    "00": "NOT CHP",
    "01": "PASSENGER CAR, STATION WAGON, JEEP",
    "02": "MOTORCYCLE",
    "03": "MOTOR-DRIVEN CYCLE (<15HP)",
    "04": "BICYCLE",
    "05": "MOTORIZED BICYCLE",
    "06": "ALL-TERRAIN VEHICLE",
    "07": "SPORT UTILITY VEHICLE",
    "08": "MINIVAN",
    "09": "PARATRANSIT BUS",
    "10": "TOUR BUS",
    "11": "OTHER COMMERCIAL BUS",
    "12": "NON-COMMERCIAL BUS",
    "13": "SCHOOLBUS PUBLIC I",
    "14": "SCHOOLBUS PUBLIC II",
    "15": "SCHOOLBUS PRIVATE I",
    "16": "SCHOOLBUS PRIVATE II",
    "17": "SCHOOLBUS CONTRACTUAL I",
    "18": "SCHOOLBUS CONTRACTUAL II",
    "19": "GENERAL PUBLIC PARATRANSIT VEHICLE",
    "20": "PUBLIC TRANSIT AUTHORITY",
    "21": "TWO-AXLE TANK TRUCK",
    "22": "PICKUP OR PANEL TRUCK",
    "23": "PICKUP TRUCK WITH CAMPER",
    "24": "THREE-AXLE TANK TRUCK",
    "25": "TRUCK TRACTOR",
    "26": "TWO-AXLE TRUCK",
    "27": "THREE-AXLE TRUCK",
    "28": "SEMI-TANK TRAILER",
    "29": "PULL-TANK TRAILER",
    "30": "TWO TANK TRAILERS",
    "31": "SEMI",
    "32": "PULL",
    "33": "TWO TRAILERS(INCLUDES SEMI AND TRAILER)",
    "34": "BOAT",
    "35": "UTILITY",
    "36": "TRAILER COACH",
    "37": "OVERSIZE VEHICLE/LOAD",
    "38": "POLE, PIPE OR LOGGING DOLLY",
    "39": "THREE TRAILERS(INCLUDES SEMI AND TWO TRAILERS)",
    "40": "SEMI 48 OR LESS WITH KING PIN TO TRAILER AXLE OF OVER 38",
    "41": "AMBULANCE",
    "42": "DUNE BUGGY",
    "43": "FIRE TRUCK (NOT RESCUE)",
    "44": "FORKLIFT",
    "45": "HIGHWAY CONSTRUCT EQUIP",
    "46": "IMPLEMENT OF HUSBANDRY",
    "47": "MOTOR HOME",
    "48": "CHP/POLICE/SHERIFF CAR",
    "49": "CHP/POLICE/SHERIFF MOTORCYCLE",
    "50": "MOBILE EQUIPMENT",
    "51": "FARM LABOR VEHICLE (CERT)",
    "52": "FEDERALLY LEGAL DOUBLE COMBO OVER 75 LONG",
    "53": "5TH WHEEL TRAVEL TRAILER",
    "54": "CONTAINER CHASSIS",
    "55": "TWO-AXLE TOW TRUCK",
    "56": "THREE-AXLE TOW TRUCK",
    "57": "FARM LABOR VEHICLE (NON-CERT)",
    "58": "FARM LABOR TRANSPORTER",
    "60": "PEDESTRIAN",
    "63": "YOUTH BUS",
    "64": "SCHOOL PUPIL ACTIVITY BUS I",
    "65": "SCHOOL PUPIL ACTIVITY BUS II",
    "66": "SCHOOLBUS W/OUT PUPILS",
    "71": "PASSENGER CAR (HAZMAT)",
    "72": "PICKUPS/PANELS (HAZMAT)",
    "73": "PICKUPS/CAMPERS (HAZMAT)",
    "75": "TRUCK TRACTOR (HAZMAT)",
    "76": "TWO-AXLE TRUCK (HAZMAT)",
    "77": "THREE+AXLE TRUCK (HAZMAT)",
    "78": "TWO-AXLE TNK TRK (HAZMAT)",
    "79": "3-AXLE TANK TRK (HAZMAT)",
    "81": "PASSENGER CAR (HAZWST)",
    "82": "PICKUPS/PANELS (HAZWST)",
    "83": "PICKUPS/CAMPERS (HAZWST)",
    "85": "TRUCK TRACTOR (HAZWST)",
    "86": "TWO-AXLE TRUCK (HAZWST)",
    "87": "THREE+AXLE TRUCK (HAZWST)",
    "88": "TWO-AXLE TNK TRK (HAZWST)",
    "89": "3-AXLE TANK TRK (HAZWST)",
    "94": "MOTORIZED TRANSPORT DEV",
    "95": "MISC NON-MOTORIZED VEH",
    "96": "MISC MOTORIZED VEHICLE",
    "97": "LOW-SPEED VEHICLE",
    "98": "EMERGENCY VEHICLE ON EMERGENCY RUN",
    "99": "NOT STATED OR UNKNOWN",
}


def chp_veh_type_desc(code):
    """Return CHP vehicle type description for a zero-padded 2-digit code string."""
    v = (code or "").strip()
    if not v or v in ("-", ""):
        return ""
    # Normalise to zero-padded 2-digit
    if v.isdigit():
        v = v.zfill(2)
    return CHP_VEHICLE_TYPE_LOOKUP.get(v, "")




# ---------------------------------------------------------------------------
# CITY / COUNTY RESOLUTION
# ---------------------------------------------------------------------------

def resolve_city_fields(cnty_city_loc_raw):
    """
    Resolve CCRS city/county fields from a SWITRS cnty_city_loc value.
    - Last two digits == 00 -> Unincorporated; City Is Incorporated = False
    - Last two digits != 00 -> City name from lookup; City Is Incorporated = True
    - County Code = first two digits as plain integer (no leading zero)
    - City Code = full integer value as string (no leading zeros)
    """
    raw = (cnty_city_loc_raw or "").strip()
    empty = {"City Code": "", "City Name": "", "County Code": "",
             "City Is Active": "", "City Is Incorporated": ""}
    if not raw:
        return empty
    try:
        code_int = int(raw)
    except ValueError:
        return {**empty, "City Code": raw}

    code_str  = str(code_int).zfill(4)
    city_sfx  = code_str[2:]
    county_int = int(code_str[:2])

    is_unincorporated = (city_sfx == "00")
    city_name         = "Unincorporated" if is_unincorporated else CNTY_CITY_LOOKUP.get(code_int, "")
    is_incorporated   = "False" if is_unincorporated else "True"

    return {
        "City Code":            str(code_int),
        "City Name":            city_name,
        "County Code":          str(county_int),
        "City Is Active":       "",
        "City Is Incorporated": is_incorporated,
    }


# ---------------------------------------------------------------------------
# DATE / TIME HELPERS
# ---------------------------------------------------------------------------

def _remove_leading_zeros_datetime(s):
    """
    Strip leading zeros from month, day, and hour in a datetime string.
    Input:  "01/05/2025 09:30:00 AM"
    Output: "1/5/2025 9:30:00 AM"
    Works cross-platform (no %-m Linux-only format codes used).
    """
    if not s:
        return s
    # Split into date part and time part on the space before AM/PM
    # Format produced by strftime: "MM/DD/YYYY HH:MM:SS AM"
    parts = s.split(" ")          # ["MM/DD/YYYY", "HH:MM:SS", "AM"]
    if len(parts) >= 1:
        # Strip leading zero from month (first char)
        date_part = parts[0]
        if date_part and date_part[0] == "0":
            date_part = date_part[1:]
        # Strip leading zero from day (after first slash)
        date_part = date_part.replace("/0", "/", 1)
        parts[0] = date_part
    if len(parts) >= 2:
        # Strip leading zero from hour
        time_part = parts[1]
        if time_part and time_part[0] == "0":
            time_part = time_part[1:]
        parts[1] = time_part
    return " ".join(parts)


def _build_ccrs_datetime(yyyymmdd, hhmm=""):
    """
    Build CCRS-style datetime: "M/D/YYYY H:MM:SS AM/PM" (no leading zeros).
    "2500" (unknown time) uses midnight fallback.
    """
    v = (yyyymmdd or "").strip()
    if not (len(v) == 8 and v.isdigit()):
        return v
    try:
        dt = datetime.strptime(v, "%Y%m%d")
    except ValueError:
        return v

    t = (hhmm or "").strip()
    if t and t != "2500" and t.isdigit():
        t = t.zfill(4)
        try:
            dt = dt.replace(hour=int(t[:2]), minute=int(t[2:]))
        except ValueError:
            pass

    raw = dt.strftime("%m/%d/%Y %I:%M:%S %p")
    return _remove_leading_zeros_datetime(raw)


def _build_ccrs_date_only(yyyymmdd):
    """PreparedDate: M/D/YYYY 12:00:00 AM (no leading zeros)."""
    v = (yyyymmdd or "").strip()
    if not (len(v) == 8 and v.isdigit()):
        return v
    try:
        dt = datetime.strptime(v, "%Y%m%d")
    except ValueError:
        return v
    raw = dt.strftime("%m/%d/%Y 12:00:00 AM")
    return _remove_leading_zeros_datetime(raw)


def _ccrs_collision_time(hhmm):
    """SWITRS HHMM -> CCRS CollisionTime (no leading zeros; 2500 passes through)."""
    v = (hhmm or "").strip()
    if v == "2500":
        return "2500"
    if v.isdigit():
        return str(int(v)) if v else ""
    return v


# ---------------------------------------------------------------------------
# GENERIC HELPERS
# ---------------------------------------------------------------------------

def normalize(value):
    return (value or "").strip().upper()


def bool_from_yn(value):
    v = normalize(value)
    if v == "Y":
        return "True"
    if v == "N":
        return "False"
    return ""


def load_csv(path):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v for k, v in row.items() if k is not None})
    return rows


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows -> {path}")


# ---------------------------------------------------------------------------
# REVERSE LOOKUP TABLES
# All description values have any leading "X-" or "X - " code prefix stripped.
# ---------------------------------------------------------------------------

DAY_OF_WEEK_REVERSE = {
    "1": "Monday",   "2": "Tuesday",  "3": "Wednesday",
    "4": "Thursday", "5": "Friday",   "6": "Saturday",  "7": "Sunday",
}

PARTY_TYPE_REVERSE = {
    "1": "DRIVER",        "2": "PEDESTRIAN",    "3": "PARKED VEHICLE",
    "4": "BICYCLIST",     "5": "OTHER",          "6": "OPERATOR",
}

VICTIM_ROLE_REVERSE = {
    "1": "DRIVER",        "2": "PASSENGER",     "3": "PEDESTRIAN",
    "4": "BICYCLIST",     "5": "OTHER",          "6": "OPERATOR",
}

INJURY_DEGREE_REVERSE = {
    "1": "FATAL INJURY",               "2": "SUSPECTED SERIOUS INJURY",
    "3": "SUSPECTED MINOR INJURY",     "4": "POSSIBLE INJURY",
    "5": "SUSPECTED SERIOUS INJURY",   "6": "SUSPECTED MINOR INJURY",
    "7": "POSSIBLE INJURY",            "0": "",  "": "",
}

# Ejected: description only, no leading code prefix
EJECTED_REVERSE = {
    "0": "Not Ejected",        "1": "Fully Ejected",
    "2": "Partially Ejected",  "3": "Unknown",
    "-": "",  "": "",
}

# Weather: description only
WEATHER_REVERSE = {
    "A": "CLEAR",   "B": "CLOUDY",  "C": "RAINING",
    "D": "SNOWING", "E": "FOG",     "F": "OTHER",   "G": "WIND",
}

# Collision type: code letter kept; description has no prefix
COLLISION_TYPE_DESC_REVERSE = {
    "A": "HEAD-ON",            "B": "SIDE SWIPE",
    "C": "REAR END",           "D": "BROADSIDE",
    "E": "HIT OBJECT",         "F": "OVERTURNED",
    "G": "VEHICLE/PEDESTRIAN", "H": "OTHER",
}

# MVIW: code letter kept; description has no prefix
MVIW_DESC_REVERSE = {
    "A": "NON-COLLISION",               "B": "PEDESTRIAN",
    "C": "OTHER MOTOR VEHICLE",         "D": "MOTOR VEHICLE ON OTHER ROADWAY",
    "E": "PARKED MOTOR VEHICLE",        "F": "TRAIN",
    "G": "BICYCLE",                     "H": "ANIMAL",
    "I": "FIXED OBJECT",                "J": "OTHER OBJECT",
    "-": "NOT STATED",
}

# Ped action: code letter kept; description has no prefix
PED_ACTION_DESC_REVERSE = {
    "A": "NO PEDESTRIAN INVOLVED",
    "B": "CROSSING IN CROSSWALK AT INTERSECTION",
    "C": "CROSSING IN CROSSWALK NOT AT INTERSECTION",
    "D": "CROSSING NOT IN CROSSWALK",
    "E": "IN ROAD, INCLUDING SHOULDER",
    "F": "NOT IN ROAD",
    "G": "APPROACHING/LEAVING SCHOOL BUS",
}

# Road surface: description only, no prefix
ROAD_SURFACE_REVERSE = {
    "A": "DRY",                    "B": "WET",
    "C": "SNOWY-ICY",              "D": "SLIPPERY(MUDDY,OILY,ETC)",
}

# Road condition: description only, no prefix
ROAD_CONDITION_REVERSE = {
    "A": "HOLES, DEEP RUTS",       "B": "LOOSE MATERIAL ON ROADWAY",
    "C": "OBSTRUCTION ON ROADWAY", "D": "CONSTRUCTION OR REPAIR ZONE",
    "E": "REDUCED ROADWAY WIDTH",  "F": "FLOODED",
    "G": "OTHER",                  "H": "NO UNUSUAL CONDITION",
    "-": "",  "": "",
}

# Lighting: code letter kept; description has no prefix
LIGHTING_DESC_REVERSE = {
    "A": "DAYLIGHT",
    "B": "DUSK-DAWN",
    "C": "DARK-STREET LIGHTS",
    "D": "DARK-NO STREET LIGHTS",
    "E": "DARK-STREET LIGHTS NOT FUNCTIONING",
}

# TrafficControlDevice: description only, no prefix
CONTROL_DEVICE_REVERSE = {
    "A": "CONTROLS FUNCTIONING",    "B": "CONTROLS NOT FUNCTIONING",
    "C": "CONTROLS OBSCURED",       "D": "NO CONTROLS PRESENT/FACTOR",
}

# PCF: code letter kept; description has no prefix
PCF_DESC_REVERSE = {
    "A": "(VEHICLE) CODE VIOLATION", "B": "OTHER IMPROPER DRIVING",
    "C": "OTHER THAN DRIVER",        "D": "UNKNOWN",
    "E": "FELL ASLEEP",              "-": "NOT STATED",
}

GENDER_CODE_MAP = {"F": "F", "M": "M", "U": "U", "X": "X"}
GENDER_DESC_MAP = {"F": "FEMALE", "M": "MALE", "U": "UNKNOWN", "X": "NON-BINARY"}

RACE_CODE_MAP = {"A": "A", "B": "B", "H": "H", "O": "O", "W": "W"}
RACE_DESC_MAP = {
    "A": "ASIAN", "B": "BLACK", "H": "HISPANIC", "O": "OTHER", "W": "WHITE",
}

AIRBAG_CODE_MAP = {"B": "B", "L": "L", "M": "M", "N": "N", "P": "P"}
AIRBAG_DESC_MAP = {
    "B": "UNKNOWN",             "L": "AIR BAG DEPLOYED",
    "M": "AIR BAG NOT DEPLOYED","N": "OTHER",  "P": "NOT REQUIRED",
}

SAFETY_EQUIP_DESC_MAP = {
    "A": "NONE IN VEHICLE",                 "B": "UNKNOWN",
    "C": "LAP BELT USED",                   "D": "LAP BELT NOT USED",
    "E": "SHOULDER HARNESS USED",           "F": "SHOULDER HARNESS NOT USED",
    "G": "LAP/SHOULDER HARNESS USED",       "H": "LAP/SHOULDER HARNESS NOT USED",
    "J": "PASSIVE RESTRAINT USED",          "K": "PASSIVE RESTRAINT NOT USED",
    "L": "AIR BAG DEPLOYED",                "M": "AIR BAG NOT DEPLOYED",
    "N": "OTHER",                           "P": "NOT REQUIRED",
    "Q": "CHILD RESTRAINT IN VEHICLE USED", "R": "CHILD RESTRAINT IN VEHICLE NOT USED",
    "S": "CHILD RESTRAINT IN VEHICLE, USE UNKNOWN",
    "T": "CHILD RESTRAINT IN VEHICLE, IMPROPER USE",
    "U": "NO CHILD RESTRAINT IN VEHICLE",
    "V": "DRIVER, MOTORCYCLE HELMET NOT USED",
    "W": "DRIVER, MOTORCYCLE HELMET USED",
    "X": "PASSENGER, MOTORCYCLE HELMET NOT USED",
    "Y": "PASSENGER, MOTORCYCLE HELMET USED",
}

# Movement preceding collision: description has no prefix; '-' -> both blank
MOVEMENT_DESC_REVERSE = {
    "A": "STOPPED",                  "B": "PROCEEDING STRAIGHT",
    "C": "RAN OFF ROAD",             "D": "MAKING RIGHT TURN",
    "E": "MAKING LEFT TURN",         "F": "MAKING U-TURN",
    "G": "BACKING",                  "H": "SLOWING/STOPPING",
    "I": "PASSING OTHER VEHICLE",    "J": "CHANGING LANES",
    "K": "PARKING MANEUVER",         "L": "ENTERING TRAFFIC",
    "M": "OTHER UNSAFE TURNING",     "N": "CROSSED INTO OPPOSING LANE",
    "O": "PARKED",                   "P": "MERGING",
    "Q": "TRAVELING WRONG WAY",      "R": "OTHER",
    "-": "",
}

SOBRIETY_DESC_MAP = {
    "A": "HAD NOT BEEN DRINKING",
    "B": "HAD BEEN DRINKING, UNDER INFLUENCE",
    "C": "HAD BEEN DRINKING, NOT UNDER INFLUENCE",
    "D": "HAD BEEN DRINKING, IMPAIRMENT UNKNOWN",
    "E": "UNDER DRUG INFLUENCE",
    "F": "IMPAIRMENT - PHYSICAL",
    "G": "IMPAIRMENT UNKNOWN",
    "H": "NOT APPLICABLE",
    "I": "IMPAIRMENT UNKNOWN - DRUG PHYSICAL",
}

INATTENTION_REVERSE = {
    "A": "CELL PHONE HANDHELD",   "B": "CELL PHONE HANDSFREE",
    "C": "ELECTRONIC_EQUIPMENT",  "D": "RADIO/CD",
    "E": "SMOKING",               "F": "EATING",
    "G": "CHILDREN",              "H": "ANIMALS",
    "I": "PERSONAL HYGIENE",      "J": "READING",  "K": "OTHER",
}

OAF_CODE_REVERSE = {
    "A": "VC SECTION VIOLATED",     "E": "VISION OBSCUREMENT",
    "F": "INATTENTION",             "G": "STOP & GO TRAFFIC",
    "H": "ENTERING OR LEAVING RAMP","I": "PREVIOUS COLLISION",
    "J": "UNFAMILIAR WITH ROAD",    "K": "DEFECTIVE VEHICLE EQUIPMENT",
    "L": "UNINVOLVED VEHICLE",      "M": "OTHER",
    "N": "NONE APPARENT",           "O": "RUNAWAY VEHICLE",
    "P": "INATTENTION", "Q": "INATTENTION", "R": "INATTENTION",
    "S": "INATTENTION", "T": "INATTENTION", "U": "INATTENTION",
    "V": "INATTENTION", "W": "INATTENTION", "X": "INATTENTION",
    "Y": "INATTENTION",
    "-": "",  "": "",
}

SPECIAL_COND_REVERSE = {
    "1": "SCHOOL BUS COLLISION",
    "3": "NO PUPILS ON SCHOOL BUS",
    "0": "",  "": "",
}


# ---------------------------------------------------------------------------
# SWITRS CRASH -> CCRS CRASH
# ---------------------------------------------------------------------------

def convert_switrs_to_crash(crash_rows):
    out = []
    for row in crash_rows:
        cid = row.get("case_id", "").strip()

        ctype     = normalize(row.get("type_of_collision", ""))
        ctype_code = ctype if len(ctype) == 1 and ctype.isalpha() else ""
        ctype_desc = COLLISION_TYPE_DESC_REVERSE.get(ctype, "")

        mviw      = normalize(row.get("mviw", ""))
        mviw_code = mviw if len(mviw) == 1 else ""
        mviw_desc = MVIW_DESC_REVERSE.get(mviw, "")

        ped       = normalize(row.get("ped_action", ""))
        ped_code  = ped if len(ped) == 1 and ped.isalpha() else ""
        ped_desc  = PED_ACTION_DESC_REVERSE.get(ped, "")

        light      = normalize(row.get("lighting", ""))
        light_code = light if light in "ABCDE" else ""
        light_desc = LIGHTING_DESC_REVERSE.get(light, "")

        pcf      = normalize(row.get("primary_coll_factor", ""))
        pcf_code = pcf if len(pcf) == 1 else ""
        pcf_desc = PCF_DESC_REVERSE.get(pcf, "")

        w1        = WEATHER_REVERSE.get(normalize(row.get("weather_1", "")), "")
        w2        = WEATHER_REVERSE.get(normalize(row.get("weather_2", "")), "")
        road_surf = ROAD_SURFACE_REVERSE.get(normalize(row.get("road_surface", "")), "")
        rc1       = ROAD_CONDITION_REVERSE.get(normalize(row.get("road_cond_1", "")), "")
        rc2       = ROAD_CONDITION_REVERSE.get(normalize(row.get("road_cond_2", "")), "")
        ctrl      = CONTROL_DEVICE_REVERSE.get(normalize(row.get("control_device", "")), "")

        hr      = normalize(row.get("hit_and_run", ""))
        hit_run = hr if hr in ("F", "M") else ""

        sc_text     = SPECIAL_COND_REVERSE.get(row.get("special_cond", "").strip(), "")
        not_private = normalize(row.get("not_private_property", ""))
        if not_private not in ("Y",):
            parts = ["PRIVATE PROPERTY"]
            if sc_text:
                parts.append(sc_text)
            special_cond_text = " / ".join(parts)
        else:
            special_cond_text = sc_text

        col_date            = row.get("collision_date", "").strip()
        col_time            = row.get("collision_time", "").strip()
        crash_datetime      = _build_ccrs_datetime(col_date, col_time)
        collision_time_ccrs = _ccrs_collision_time(col_time)
        prepared_date       = _build_ccrs_date_only(row.get("proc_date", "").strip())
        city_fields         = resolve_city_fields(row.get("cnty_city_loc", "").strip())

        # Build Primary Collision Factor Violation from pcf_violation + pcf_viol_subsection
        # Format: "VC 22350(A)" when subsection present, "VC 22350" when not.
        _pcf_viol    = (row.get("pcf_violation", "") or "").strip()
        _pcf_sub     = (row.get("pcf_viol_subsection", "") or "").strip().upper()
        if _pcf_viol:
            _pcf_sub_fmt = f"({_pcf_sub})" if _pcf_sub else ""
            pcf_violation_str = f"VC {_pcf_viol}{_pcf_sub_fmt}"
        else:
            pcf_violation_str = ""

        crash = {
            "CollisionId":                          cid,
            "Report Number":                        (row.get("local_report_number", "") or "").strip().upper(),
            "Report Version":                       "",
            "Is Preliminary":                       "",
            "NCIC Code":                            (row.get("juris", "") or "").strip().upper(),
            "Crash Date Time":                      crash_datetime,
            "Collision Time":                       collision_time_ccrs,
            "Day of Week":                          DAY_OF_WEEK_REVERSE.get(
                                                        row.get("day_of_week", "").strip(), ""),
            "Beat":                                 (row.get("beat_number", "") or "").strip().upper(),
            "City Id":                              "",
            "City Code":                            city_fields["City Code"],
            "City Name":                            city_fields["City Name"],
            "County Code":                          city_fields["County Code"],
            "City Is Active":                       city_fields["City Is Active"],
            "City Is Incorporated":                 city_fields["City Is Incorporated"],
            "Collision Type Code":                  ctype_code,
            "Collision Type Description":           ctype_desc,
            "DispatchNotified":                     "",
            "HasPhotographs":                       "",
            "HitRun":                               hit_run,
            "IsDeleted":                            "",
            "IsHighwayRelated":                     bool_from_yn(row.get("state_hwy_ind", "")),
            "IsTowAway":                            bool_from_yn(row.get("tow_away", "")),
            "JudicialDistrict":                     "",
            "MotorVehicleInvolvedWithCode":          mviw_code,
            "MotorVehicleInvolvedWithDesc":          mviw_desc,
            "MotorVehicleInvolvedWithOtherDesc":     "",
            "NumberInjured":                        row.get("number_injured", ""),
            "NumberKilled":                         row.get("number_killed", ""),
            "Weather 1":                            w1,
            "Weather 2":                            w2,
            "Road Condition 1":                     rc1,
            "Road Condition 2":                     rc2,
            "Special Condition":                    special_cond_text,
            "LightingCode":                         light_code,
            "LightingDescription":                  light_desc,
            "Latitude":                             row.get("latitude", ""),
            "Longitude":                            row.get("longitude", ""),
            "MilePostDirection":                    (row.get("side_of_hwy", "") or "").strip().upper(),
            "MilePostDistance":                     row.get("postmile", ""),
            "MilePostMarker":                       "",
            "MilePostUnitOfMeasure":                "",
            "PedestrianActionCode":                 ped_code,
            "PedestrianActionDesc":                 ped_desc,
            "PreparedDate":                         prepared_date,
            "PrimaryCollisionFactorCode":           pcf_code,
            "PrimaryCollisionFactorDescription":    pcf_desc,
            "Primary Collision Factor Violation":   pcf_violation_str,
            "PrimaryCollisionFactorIsCited":        "",
            "PrimaryCollisionPartyNumber":          "",
            "Primary Rd":                           (row.get("primary_rd", "") or "").strip().upper(),
            "ReportingDistrict":                    (row.get("reporting_district", "") or "").strip().upper(),
            "ReportingDistrictCode":                "",   # left blank per spec
            "Secondary Rd":                         (row.get("secondary_rd", "") or "").strip().upper(),
            "ReviewedDate":                         "",
            "RoadwaySurfaceCode":                   road_surf,
            "SecondaryDirection":                   (row.get("direction", "") or "").strip().upper(),
            "SecondaryDistance":                    row.get("distance", ""),
            "SecondaryUnitOfMeasure":               "F",  # SWITRS distances are in feet
            "SecondaryRoad":                        (row.get("secondary_rd", "") or "").strip().upper(),
            "TrafficControlDeviceCode":             ctrl,
            "CreatedDate":                          "",
            "ModifiedDate":                         "",
            "IsCountyRoad":                         "",
            "IsFreeWay":                            bool_from_yn(row.get("state_hwy_ind", "")),
            "CHP555Version":                        "",
            "IsAdditonalObjectStruck":              "",
            "NotificationDate":                     "",
            "NotificationTimeDescription":          "",
            "HasDigitalMediaFiles":                 "",
            "EvidenceNumber":                       "",
            "IsLocationReferToNarrative":           "",
            "IsAOIOneSameAsLocation":               "",
        }
        out.append(crash)
    return out


# ---------------------------------------------------------------------------
# PARTY -> CCRS PARTY
# ---------------------------------------------------------------------------

def convert_party_to_ccrs(party_rows, hit_run_map=None):
    out = []
    for row in party_rows:
        cid  = row.get("case_id", "").strip()
        pnum = row.get("party_number", "").strip()

        ptype_text  = PARTY_TYPE_REVERSE.get(row.get("party_type", "").strip(), "")
        at_fault    = row.get("at_fault", "").strip()
        is_at_fault = "True" if at_fault == "Y" else ("False" if at_fault == "N" else "")

        age = row.get("party_age", "").strip()
        if age == "998":
            age = ""

        gender_raw  = row.get("party_sex", "").strip().upper()
        gender_code = GENDER_CODE_MAP.get(gender_raw, gender_raw)
        gender_desc = GENDER_DESC_MAP.get(gender_raw, "")

        race_raw  = row.get("race", "").strip().upper()
        race_code = RACE_CODE_MAP.get(race_raw, race_raw)
        race_desc = RACE_DESC_MAP.get(race_raw, "")

        airbag_raw  = row.get("party_safety_equip_1", "").strip().upper()
        airbag_code = AIRBAG_CODE_MAP.get(airbag_raw, airbag_raw)
        airbag_desc = AIRBAG_DESC_MAP.get(airbag_raw, "")

        safety_raw  = row.get("party_safety_equip_2", "").strip().upper()
        safety_code = safety_raw
        safety_desc = SAFETY_EQUIP_DESC_MAP.get(safety_raw, "")

        # Movement: '-' -> both code and desc blank
        move_raw = row.get("move_pre_acc", "").strip().upper()
        if move_raw == "-":
            move_code = ""
            move_desc = ""
        else:
            move_code = move_raw
            move_desc = MOVEMENT_DESC_REVERSE.get(move_raw, "")

        # Sobriety: four columns (code1, desc1, code2, desc2)
        sob1      = row.get("party_sobriety", "").strip().upper()
        sob2      = row.get("party_drug_physical", "").strip().upper()
        sob1_desc = SOBRIETY_DESC_MAP.get(sob1, "")
        sob2_desc = SOBRIETY_DESC_MAP.get(sob2, "")

        oaf1_text = OAF_CODE_REVERSE.get(row.get("oaf_1", "").strip().upper(), "")
        oaf2_text = OAF_CODE_REVERSE.get(row.get("oaf_2", "").strip().upper(), "")
        if oaf1_text and oaf2_text and oaf1_text != oaf2_text:
            oaf_combined = oaf1_text + " / " + oaf2_text
        else:
            oaf_combined = oaf1_text or oaf2_text

        inatt_text = INATTENTION_REVERSE.get(row.get("inattention", "").strip().upper(), "")

        # Rebuild CCRS Special Information from SWITRS sp_info_1/2/3 codes.
        # SWITRS uses "-" as a null/not-stated sentinel -- filter these out.
        # Each code maps to a full CCRS description string; combined with " / ".
        _SP_INFO_MAP = {
            "A": "HAZARDOUS MATERIALS",
            "B": "CELL PHONE IN USE (4/1/01)",
            "C": "CELL PHONE NOT IN USE (4/1/01)",
            "D": "NO CELL PHONE/UNKNOWN (4/1/01)",
            "1": "CELL PHONE HANDHELD IN USE",
            "2": "CELL PHONE HANDSFREE IN USE",
            "3": "CELL PHONE NOT IN USE",
            "4": "CELL PHONE USE UNKNOWN",
            "E": "SCHOOL BUS RELATED (1/1/02)",
        }
        # SWITRS sp_info_1 is "A" or blank/dash; sp_info_2 is "1"-"4","B"-"D" or blank/dash;
        # sp_info_3 is "E" or blank/dash. The forward converter had a substring bug that
        # set sp_info_3="E" whenever the letter E appeared anywhere in the source text,
        # so many records incorrectly carry sp_info_3="E". Only accept exact single-char
        # codes that are valid keys in _SP_INFO_MAP; reject anything else (including
        # values that are clearly artefacts of the forward converter bug, i.e. anything
        # longer than one character or not a recognised code).
        # sp_info_1: "A" (Hazardous Materials) or blank/dash -- safe to use directly.
        # sp_info_2: "1"-"4","B","C","D" (cell phone codes) or blank/dash -- safe.
        # sp_info_3: intended to be "E" (School Bus Related) or blank, BUT the forward
        #   converter used `"E" in sp_raw` (substring match) rather than a token check,
        #   and EVERY CCRS Special Information description text contains the letter "E"
        #   (e.g. "CELL PHONE NOT IN USE", "HAZARDOUS MATERIALS"). This means sp_info_3
        #   is set to "E" on virtually every party row that had any Special Information
        #   at all -- so it cannot be trusted. We suppress sp_info_3 entirely to avoid
        #   generating spurious "SCHOOL BUS RELATED" values on non-school-bus records.
        _NULL_VALUES = {"", "-", " "}
        sp_codes = [
            row.get("sp_info_1", "").strip(),   # A or blank/dash
            row.get("sp_info_2", "").strip(),   # 1-4, B-D, or blank/dash
            # sp_info_3 intentionally omitted -- see note above
        ]
        sp_parts = [
            _SP_INFO_MAP[c] for c in sp_codes
            if c not in _NULL_VALUES and c in _SP_INFO_MAP
        ]
        special_info = " / ".join(sp_parts)

        # IsOnDutyEmergencyVehicle: CHP type 98 = "EMERGENCY VEHICLE ON EMERGENCY RUN"
        def _is_emerg(code):
            v = (code or "").strip()
            return v.zfill(2) == "98" if v.isdigit() else False
        is_on_duty_emerg = (
            "True" if _is_emerg(row.get("chp_veh_type_towing", ""))
                   or _is_emerg(row.get("chp_veh_type_towed", ""))
            else ""
        )

        p = {
            "Party Id":                         "",
            "CollisionId":                      cid,
            "Party Number":                     pnum,
            "Party Type":                       ptype_text,
            "IsAtFault":                        is_at_fault,
            "IsOnDutyEmergencyVehicle":         is_on_duty_emerg,
            "IsHitAndRun":                      "True" if (hit_run_map or {}).get(cid, "") in ("F", "M") else "False",
            "AirbagCode":                       airbag_code,
            "AirBagCodeDescription":            airbag_desc,
            "SafetyEquipmentCode":              safety_code,
            "SafetyEquipmentDescription":       safety_desc,
            "Special Information":              special_info,
            "Other Associate Factor":           oaf_combined,
            "Inattention":                      inatt_text,
            "DirectionOfTravel":                row.get("dir_of_travel", "").strip(),
            "StreetOrHighwayName":              "",
            "SpeedLimit":                       "",
            "MovementPrecCollCode":             move_code,
            "MovementPrecCollDesc":             move_desc,
            "SobrietyDrugPhysicalCode1":        sob1,
            "SobrietyDrugPhysicalDescription1": sob1_desc,
            "SobrietyDrugPhysicalCode2":        sob2,
            "SobrietyDrugPhysicalDescription2": sob2_desc,
            "GenderCode":                       gender_code,
            "GenderDescription":                gender_desc,
            "StatedAge":                        age,
            "DriverLicenseClass":               "",
            "DriverLicenseStateCode":           "",
            "RaceCode":                         race_code,
            "RaceDesc":                         race_desc,
            "Vehicle1TypeId":                   row.get("chp_veh_type_towing", "").strip(),
            "Vehicle1TypeDesc":                 chp_veh_type_desc(row.get("chp_veh_type_towing", "")),
            "Vehicle1Year":                     row.get("vehicle_year", ""),
            "Vehicle1Make":                     row.get("vehicle_make", ""),
            "Vehicle1Model":                    "",
            "Vehicle1Color":                    "",
            "V1IsVehicleTowed":                 "",
            "Vehicle2TypeId":                   row.get("chp_veh_type_towed", "").strip(),
            "Vehicle2TypeDesc":                 chp_veh_type_desc(row.get("chp_veh_type_towed", "")),
            "Vehicle2Year":                     "",
            "Vehicle2Make":                     "",
            "Vehicle2Model":                    "",
            "Vehicle2Color":                    "",
            "V2IsVehicleTowed":                 "",
            "Lane":                             "",
            "ThruLane":                         "",
            "TotalLane":                        "",
            "IsDREConducted":                   "",
        }
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# VICTIM -> CCRS InjuredWitnessPassenger (IWP)
# ---------------------------------------------------------------------------

def convert_victim_to_iwp(victim_rows):
    out = []
    for row in victim_rows:
        cid  = row.get("case_id", "").strip()
        pnum = row.get("party_number", "").strip()

        role_text = VICTIM_ROLE_REVERSE.get(row.get("victim_role", "").strip(), "")

        age = row.get("victim_age", "").strip()
        if age == "998":
            age = ""

        gender_raw  = row.get("victim_sex", "").strip().upper()
        gender_code = GENDER_CODE_MAP.get(gender_raw, gender_raw)
        gender_desc = GENDER_DESC_MAP.get(gender_raw, "")

        extent = INJURY_DEGREE_REVERSE.get(row.get("victim_degree_of_injury", "").strip(), "")

        airbag_raw  = row.get("victim_safety_equip_1", "").strip().upper()
        airbag_code = AIRBAG_CODE_MAP.get(airbag_raw, airbag_raw)
        airbag_desc = AIRBAG_DESC_MAP.get(airbag_raw, "")

        safety_raw  = row.get("victim_safety_equip_2", "").strip().upper()
        safety_code = safety_raw
        safety_desc = SAFETY_EQUIP_DESC_MAP.get(safety_raw, "")

        # Ejected: description only, no code prefix
        ejected_text = EJECTED_REVERSE.get(row.get("victim_ejected", "").strip(), "")

        iwp = {
            "Collision Id":                 cid,
            "InjuredWitPassId":             "",
            "PartyNumber":                  pnum,
            "StatedAge":                    age,
            "Gender":                       gender_code,
            "Gender Desc":                  gender_desc,
            "Race":                         "",
            "Race Desc":                    "",
            "IsWitnessOnly":                "False",  # SWITRS has no witness-only records
            "IsPassengerOnly":              "True" if role_text == "PASSENGER" else "False",
            "ExtentOfInjury":               extent,
            "InjuredPersonType":            role_text,
            "SeatPosition":                 row.get("victim_seating_position", "").strip(),
            "AirbagCode":                   airbag_code,
            "AirBagCodeDescription":        airbag_desc,
            "SafetyEquipmentCode":          safety_code,
            "SafetyEquipmentDescription":   safety_desc,
            "Ejected":                      ejected_text,
        }
        out.append(iwp)
    return out


# ---------------------------------------------------------------------------
# OUTPUT SCHEMAS
# ---------------------------------------------------------------------------

CCRS_CRASH_FIELDS = [
    "CollisionId", "Report Number", "Report Version", "Is Preliminary",
    "NCIC Code", "Crash Date Time", "Collision Time", "Beat",
    "City Id", "City Code", "City Name", "County Code",
    "City Is Active", "City Is Incorporated",
    "Collision Type Code", "Collision Type Description",
    "Day of Week", "DispatchNotified", "HasPhotographs", "HitRun",
    "IsDeleted", "IsHighwayRelated", "IsTowAway", "JudicialDistrict",
    "MotorVehicleInvolvedWithCode", "MotorVehicleInvolvedWithDesc",
    "MotorVehicleInvolvedWithOtherDesc",
    "NumberInjured", "NumberKilled",
    "Weather 1", "Weather 2",
    "Road Condition 1", "Road Condition 2",
    "Special Condition",
    "LightingCode", "LightingDescription",
    "Latitude", "Longitude",
    "MilePostDirection", "MilePostDistance", "MilePostMarker",
    "MilePostUnitOfMeasure",
    "PedestrianActionCode", "PedestrianActionDesc",
    "PreparedDate",
    "PrimaryCollisionFactorCode", "PrimaryCollisionFactorDescription",
    "Primary Collision Factor Violation",
    "PrimaryCollisionFactorIsCited", "PrimaryCollisionPartyNumber",
    "Primary Rd", "ReportingDistrict", "ReportingDistrictCode",
    "Secondary Rd", "ReviewedDate",
    "RoadwaySurfaceCode",
    "SecondaryDirection", "SecondaryDistance", "SecondaryUnitOfMeasure",
    "SecondaryRoad",
    "TrafficControlDeviceCode",
    "CreatedDate", "ModifiedDate",
    "IsCountyRoad", "IsFreeWay",
    "CHP555Version", "IsAdditonalObjectStruck",
    "NotificationDate", "NotificationTimeDescription",
    "HasDigitalMediaFiles", "EvidenceNumber",
    "IsLocationReferToNarrative", "IsAOIOneSameAsLocation",
]

CCRS_PARTY_FIELDS = [
    "Party Id", "CollisionId", "Party Number", "Party Type",
    "IsAtFault", "IsOnDutyEmergencyVehicle", "IsHitAndRun",
    "AirbagCode", "AirBagCodeDescription",
    "SafetyEquipmentCode", "SafetyEquipmentDescription",
    "Special Information", "Other Associate Factor", "Inattention",
    "DirectionOfTravel", "StreetOrHighwayName", "SpeedLimit",
    "MovementPrecCollCode", "MovementPrecCollDesc",
    "SobrietyDrugPhysicalCode1", "SobrietyDrugPhysicalDescription1",
    "SobrietyDrugPhysicalCode2", "SobrietyDrugPhysicalDescription2",
    "GenderCode", "GenderDescription",
    "StatedAge",
    "DriverLicenseClass", "DriverLicenseStateCode",
    "RaceCode", "RaceDesc",
    "Vehicle1TypeId", "Vehicle1TypeDesc",
    "Vehicle1Year", "Vehicle1Make", "Vehicle1Model", "Vehicle1Color",
    "V1IsVehicleTowed",
    "Vehicle2TypeId", "Vehicle2TypeDesc",
    "Vehicle2Year", "Vehicle2Make", "Vehicle2Model", "Vehicle2Color",
    "V2IsVehicleTowed",
    "Lane", "ThruLane", "TotalLane",
    "IsDREConducted",
]

CCRS_IWP_FIELDS = [
    "Collision Id", "InjuredWitPassId", "PartyNumber",
    "StatedAge",
    "Gender", "Gender Desc",
    "Race", "Race Desc",
    "IsWitnessOnly", "IsPassengerOnly",
    "ExtentOfInjury", "InjuredPersonType",
    "SeatPosition",
    "AirbagCode", "AirBagCodeDescription",
    "SafetyEquipmentCode", "SafetyEquipmentDescription",
    "Ejected",
]


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert SWITRS CSV exports to CCRS format."
    )
    parser.add_argument("--crash", required=True, help="Path to SWITRS crash CSV")
    parser.add_argument("--party",    required=True, help="Path to SWITRS party CSV")
    parser.add_argument("--victim",   required=True, help="Path to SWITRS victim CSV")
    parser.add_argument("--out-dir",  default="./ccrs_output",
                        help="Output directory (default: ./ccrs_output)")
    args = parser.parse_args()

    print("Loading SWITRS data files...")
    crash_rows = load_csv(args.crash)
    party_rows    = load_csv(args.party)
    victim_rows   = load_csv(args.victim)
    print(f"  Crash rows : {len(crash_rows)}")
    print(f"  Party rows    : {len(party_rows)}")
    print(f"  Victim rows   : {len(victim_rows)}")
    print(f"  City/county lookup: {len(CNTY_CITY_LOOKUP)} entries (embedded)")

    print("Converting tables...")
    # Build case_id -> HitRun lookup so party rows can derive IsHitAndRun
    hit_run_map = {
        row.get("case_id", "").strip(): row.get("hit_and_run", "").strip().upper()
        for row in crash_rows
        if row.get("case_id", "").strip()
    }
    crash_out = convert_switrs_to_crash(crash_rows)
    party_out = convert_party_to_ccrs(party_rows, hit_run_map)
    iwp_out   = convert_victim_to_iwp(victim_rows)

    # ── Sort party and IWP by CollisionId then PartyNumber ───────────────
    def _sort_key(row, id_field, num_field):
        cid = row.get(id_field, "") or ""
        pnum = row.get(num_field, "") or ""
        try:
            return (int(cid), int(pnum))
        except ValueError:
            return (cid, pnum)

    party_out.sort(key=lambda r: _sort_key(r, "CollisionId", "Party Number"))
    iwp_out.sort(key=lambda r: _sort_key(r, "Collision Id", "PartyNumber"))

    # ── Populate PrimaryCollisionPartyNumber in crash from at-fault party ─
    # Build map: collision_id -> party_number of the at-fault party
    at_fault_map = {}
    for p in party_out:
        if p.get("IsAtFault") == "True":
            at_fault_map[p["CollisionId"]] = p["Party Number"]
    for c in crash_out:
        c["PrimaryCollisionPartyNumber"] = at_fault_map.get(c["CollisionId"], "")

    out = args.out_dir
    write_csv(f"{out}/ccrs_crash.csv", CCRS_CRASH_FIELDS, crash_out)
    write_csv(f"{out}/ccrs_party.csv", CCRS_PARTY_FIELDS, party_out)
    write_csv(f"{out}/ccrs_iwp.csv",   CCRS_IWP_FIELDS,   iwp_out)

    print("\nDone.")
    print(f"  ccrs_crash.csv -> {len(crash_out)} rows")
    print(f"  ccrs_party.csv -> {len(party_out)} rows")
    print(f"  ccrs_iwp.csv   -> {len(iwp_out)} rows")


if __name__ == "__main__":
    main()
