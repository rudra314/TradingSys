"""
sector_definitions.py — Authoritative NSE sector mapping.

Covers all stocks in NIFTY100, NIFTY_MIDCAP150, and NIFTY_SMALLCAP250
using standard NSE sector classifications aligned with the indices in
config.SECTOR_INDICES.  Stocks without a matching index are mapped to
OTHER and pass Gate 4 unconditionally.

Sector  → NSE index used for RS55
Banking → ^NSEBANK   (banks, NBFCs, insurance, exchanges, AMC)
IT      → ^CNXIT     (software, IT services, fintech, telecom-infra)
Auto    → ^CNXAUTO   (OEMs, ancillaries, tyres, batteries)
Pharma  → ^CNXPHARMA (pharma, hospitals, diagnostics, devices)
FMCG    → ^CNXFMCG   (food, beverages, personal care, spirits)
Metals  → ^CNXMETAL  (steel, aluminium, copper, coal, mining)
Energy  → ^CNXENERGY (oil, gas, power utilities, renewables)
Infra   → ^CNXINFRA  (capital goods, construction, defence mfg)
Realty  → ^CNXREALTY (real estate developers)
Other   → (none)     (cement, chemicals, telecom, retail, media …)
"""

BANKING = "Banking"
IT      = "IT"
AUTO    = "Auto"
PHARMA  = "Pharma"
FMCG    = "FMCG"
METALS  = "Metals"
ENERGY  = "Energy"
INFRA   = "Infra"
REALTY  = "Realty"
OTHER   = "Other"

SECTOR_MAP: dict[str, str] = {
    # Banking — banks, NBFCs, housing finance, insurance, exchanges/AMC
    "AAVAS": 'Banking',      "ABCAPITAL": 'Banking',      "ANGELONE": 'Banking',      "APTUS": 'Banking',
    "ARMANFIN": 'Banking',      "AUBANK": 'Banking',      "AXISBANK": 'Banking',      "BAJAJFINSV": 'Banking',
    "BAJAJHFL": 'Banking',      "BAJFINANCE": 'Banking',      "BANDHANBNK": 'Banking',      "BANKBARODA": 'Banking',
    "BSE": 'Banking',      "CAMS": 'Banking',      "CANARABANK": 'Banking',      "CANBK": 'Banking',
    "CANFINHOME": 'Banking',      "CARERATING": 'Banking',      "CDSL": 'Banking',      "CENTRALBK": 'Banking',
    "CHOLAFIN": 'Banking',      "CRISIL": 'Banking',      "CSBBANK": 'Banking',      "DCBBANK": 'Banking',
    "EDELWEISS": 'Banking',      "EMKAY": 'Banking',      "FEDERALBNK": 'Banking',      "GICHRE": 'Banking',
    "HDFC": 'Banking',      "HDFCBANK": 'Banking',      "HDFCLIFE": 'Banking',      "ICICIBANK": 'Banking',
    "ICICIPRULI": 'Banking',      "ICRA": 'Banking',      "IDFC": 'Banking',      "IDFCFIRSTB": 'Banking',
    "INDUSINDBK": 'Banking',      "IRFC": 'Banking',      "ISEC": 'Banking',      "JIOFIN": 'Banking',
    "JMFINANCIL": 'Banking',      "KARURVYSYA": 'Banking',      "KOTAKBANK": 'Banking',      "LAKSHVILAS": 'Banking',
    "LICHSGFIN": 'Banking',      "MANAPPURAM": 'Banking',      "MCX": 'Banking',      "MFSL": 'Banking',
    "MOTILALOFS": 'Banking',      "NIACL": 'Banking',      "NUVAMA": 'Banking',      "PAISALO": 'Banking',
    "PNB": 'Banking',      "PNBHOUSING": 'Banking',      "RBLBANK": 'Banking',      "RECLTD": 'Banking',
    "SBICARD": 'Banking',      "SBILIFE": 'Banking',      "SBIN": 'Banking',      "STARHEALTH": 'Banking',
    "SUNDARMFIN": 'Banking',      "UCOBANK": 'Banking',      "UJJIVANSFB": 'Banking',      "UNIONBANK": 'Banking',
    "UTIAMC": 'Banking',      "UTKARSHBNK": 'Banking',      "YESBANK": 'Banking',

    # IT — software, IT services, fintech, telecom infra, digital
    "AFFLE": 'IT',      "AXISCADES": 'IT',      "CIGNITITEC": 'IT',      "COFORGE": 'IT',
    "CYIENT": 'IT',      "CYIENTDLM": 'IT',      "DATAPATTNS": 'IT',      "DIXON": 'IT',
    "HAPPSTMNDS": 'IT',      "HCLTECH": 'IT',      "HEXAWARE": 'IT',      "HFCL": 'IT',
    "INFY": 'IT',      "INTELLECT": 'IT',      "IXIGO": 'IT',      "KFINTECH": 'IT',
    "KPITTECH": 'IT',      "LTIM": 'IT',      "LTTS": 'IT',      "MASTEK": 'IT',
    "MATRIMONY": 'IT',      "MPHASIS": 'IT',      "MPSLTD": 'IT',      "MTNL": 'IT',
    "NAUKRI": 'IT',      "NAZARA": 'IT',      "NIITLTD": 'IT',      "NIITTECH": 'IT',
    "OFSS": 'IT',      "ONMOBILE": 'IT',      "PAYTM": 'IT',      "PERSISTENT": 'IT',
    "POLICYBZR": 'IT',      "RAILTEL": 'IT',      "RATEGAIN": 'IT',      "ROUTE": 'IT',
    "SONATSOFTW": 'IT',      "STLTECH": 'IT',      "TANLA": 'IT',      "TATACOMM": 'IT',
    "TATAELXSI": 'IT',      "TCS": 'IT',      "TECHM": 'IT',      "TEJASNET": 'IT',
    "WIPRO": 'IT',      "XCHANGING": 'IT',      "ZENSARTECH": 'IT',

    # Auto — OEMs, auto ancillaries, tyres, batteries, forgings
    "AMARAJABAT": 'Auto',      "APOLLOTYRE": 'Auto',      "ASAHIINDIA": 'Auto',      "ASHOKLEY": 'Auto',
    "BAJAJ-AUTO": 'Auto',      "BHARATFORG": 'Auto',      "BOSCHLTD": 'Auto',      "CEATLTD": 'Auto',
    "CRAFTSMAN": 'Auto',      "EICHERMOT": 'Auto',      "ENDURANCE": 'Auto',      "ESCORTS": 'Auto',
    "EXIDEIND": 'Auto',      "FIEMIND": 'Auto',      "GABRIEL": 'Auto',      "HARITASEAT": 'Auto',
    "HEROMOTOCO": 'Auto',      "INDNIPPON": 'Auto',      "JKTYRE": 'Auto',      "M&M": 'Auto',
    "MAHINDCIE": 'Auto',      "MARUTI": 'Auto',      "MINDA": 'Auto',      "MINDAIND": 'Auto',
    "MOTHERSON": 'Auto',      "OLECTRA": 'Auto',      "PRICOLLTD": 'Auto',      "RAJRATAN": 'Auto',
    "SCHAEFFLER": 'Auto',      "SHRIPISTON": 'Auto',      "SMLISUZU": 'Auto',      "SONACOMS": 'Auto',
    "SSWL": 'Auto',      "SUBROS": 'Auto',      "SUNDRMFAST": 'Auto',      "SUPRAJIT": 'Auto',
    "TALBROS": 'Auto',      "TATAMOTORS": 'Auto',      "TIMKEN": 'Auto',      "TVSMOTOR": 'Auto',
    "TVSMOTORS": 'Auto',      "TVSSRICHAK": 'Auto',      "UNOMINDA": 'Auto',      "USHAMART": 'Auto',
    "ZFCVINDIA": 'Auto',

    # Pharma — pharma, hospitals, diagnostics, medical devices, CROs
    "AARTIDRUGS": 'Pharma',      "ABBOTINDIA": 'Pharma',      "AJANTPHARM": 'Pharma',      "ALKEM": 'Pharma',
    "APOLLOHOSP": 'Pharma',      "AUROPHARMA": 'Pharma',      "BIOCON": 'Pharma',      "CIPLA": 'Pharma',
    "DCAL": 'Pharma',      "DIVISLAB": 'Pharma',      "DRREDDY": 'Pharma',      "DRREDDYLAB": 'Pharma',
    "FORTIS": 'Pharma',      "GLAXO": 'Pharma',      "GLENMARK": 'Pharma',      "GRANULES": 'Pharma',
    "IPCALAB": 'Pharma',      "JBCHEPHARM": 'Pharma',      "JUBLPHARMA": 'Pharma',      "LALPATHLAB": 'Pharma',
    "LAURUSLABS": 'Pharma',      "LUPIN": 'Pharma',      "MARKSANS": 'Pharma',      "MAXHEALTH": 'Pharma',
    "MEDANTA": 'Pharma',      "METROPOLIS": 'Pharma',      "NATCOPHARM": 'Pharma',      "PFIZER": 'Pharma',
    "POLYMED": 'Pharma',      "RAINBOW": 'Pharma',      "SANOFI": 'Pharma',      "SEQUENT": 'Pharma',
    "SHILPAMED": 'Pharma',      "SIGACHI": 'Pharma',      "SOLARA": 'Pharma',      "SUNPHARMA": 'Pharma',
    "SUPRIYA": 'Pharma',      "SYNGENE": 'Pharma',      "TARSONS": 'Pharma',      "THYROCARE": 'Pharma',
    "TORNTPHARM": 'Pharma',      "WINDLAS": 'Pharma',      "WOCKPHARMA": 'Pharma',      "YATHARTH": 'Pharma',
    "ZIMLAB": 'Pharma',      "ZYDUSLIFE": 'Pharma',

    # FMCG — food, beverages, personal care, tobacco, spirits, dairy
    "AMRUTANJAN": 'FMCG',      "AVANTIFEED": 'FMCG',      "BALRAMCHIN": 'FMCG',      "BRITANNIA": 'FMCG',
    "CCL": 'FMCG',      "COLPAL": 'FMCG',      "DABUR": 'FMCG',      "DFMFOODS": 'FMCG',
    "EMAMILTD": 'FMCG',      "GODREJCP": 'FMCG',      "HERITGFOOD": 'FMCG',      "HINDUNILVR": 'FMCG',
    "ITC": 'FMCG',      "JUBLFOOD": 'FMCG',      "JYOTHYLAB": 'FMCG',      "KRBL": 'FMCG',
    "MARICO": 'FMCG',      "MCDOWELL-N": 'FMCG',      "NESTLEIND": 'FMCG',      "RADICO": 'FMCG',
    "TATACONSUM": 'FMCG',      "UBL": 'FMCG',      "UNITDSPR": 'FMCG',      "VARUNBEV": 'FMCG',
    "VBL": 'FMCG',      "VENKEYS": 'FMCG',

    # Metals — steel, aluminium, zinc, copper, coal, iron ore, graphite
    "APLAPOLLO": 'Metals',      "COALINDIA": 'Metals',      "GPIL": 'Metals',      "GRAPHITE": 'Metals',
    "HEG": 'Metals',      "HINDALCO": 'Metals',      "HINDZINC": 'Metals',      "IMFA": 'Metals',
    "JAIBALAJI": 'Metals',      "JINDALSTEL": 'Metals',      "JSWSTEEL": 'Metals',      "KIOCL": 'Metals',
    "LLOYDSME": 'Metals',      "MIDHANI": 'Metals',      "MOIL": 'Metals',      "MUKANDLTD": 'Metals',
    "NATIONALUM": 'Metals',      "NMDC": 'Metals',      "RATNAMANI": 'Metals',      "SAIL": 'Metals',
    "TATASTEEL": 'Metals',      "TINPLATE": 'Metals',      "VEDL": 'Metals',      "WELSPUNIND": 'Metals',

    # Energy — oil, gas, power utilities, renewables, lubricants
    "ADANIGAS": 'Energy',      "ADANIGREEN": 'Energy',      "ADANIPOWER": 'Energy',      "ATGL": 'Energy',
    "BPCL": 'Energy',      "CASTROLIND": 'Energy',      "CESC": 'Energy',      "GAIL": 'Energy',
    "GSPL": 'Energy',      "GULFOILLUB": 'Energy',      "HINDPETRO": 'Energy',      "HPCL": 'Energy',
    "IGL": 'Energy',      "INOXWIND": 'Energy',      "IOC": 'Energy',      "JPPOWER": 'Energy',
    "JSWENERGY": 'Energy',      "MAHANAGAR": 'Energy',      "MGL": 'Energy',      "MRPL": 'Energy',
    "NAVA": 'Energy',      "NHPC": 'Energy',      "NLCINDIA": 'Energy',      "NTPC": 'Energy',
    "OIL": 'Energy',      "ONGC": 'Energy',      "PETRONET": 'Energy',      "POWERGRID": 'Energy',
    "RELIANCE": 'Energy',      "RPOWER": 'Energy',      "RTNPOWER": 'Energy',      "SUZLON": 'Energy',
    "SWSOLAR": 'Energy',      "TATAPOWER": 'Energy',      "TORNTPOWER": 'Energy',      "UJAAS": 'Energy',
    "WEBELSOLAR": 'Energy',

    # Infra — capital goods, construction, defence mfg, heavy engineering
    "ABB": 'Infra',      "ACE": 'Infra',      "ADANIENT": 'Infra',      "ADANIPORTS": 'Infra',
    "AIAENG": 'Infra',      "BEL": 'Infra',      "BEML": 'Infra',      "BHEL": 'Infra',
    "CGPOWER": 'Infra',      "CUMMINSIND": 'Infra',      "ELECON": 'Infra',      "ELGIEQUIP": 'Infra',
    "GMRINFRA": 'Infra',      "HAL": 'Infra',      "HGINFRA": 'Infra',      "HONAUT": 'Infra',
    "IRB": 'Infra',      "ISGEC": 'Infra',      "ITD": 'Infra',      "ITDCEM": 'Infra',
    "JKIL": 'Infra',      "KALPATPOWR": 'Infra',      "KEC": 'Infra',      "KPIL": 'Infra',
    "LIKHITHA": 'Infra',      "LMWLTD": 'Infra',      "LT": 'Infra',      "MANINFRA": 'Infra',
    "MONTECARLO": 'Infra',      "NCC": 'Infra',      "PATELENG": 'Infra',      "PNCINFRA": 'Infra',
    "POWERINDIA": 'Infra',      "POWERMECH": 'Infra',      "RAILVIKAS": 'Infra',      "RITES": 'Infra',
    "RVNL": 'Infra',      "SADBHAV": 'Infra',      "SIEMENS": 'Infra',      "SKIPPER": 'Infra',
    "THERMAX": 'Infra',      "TITAGARH": 'Infra',      "VOLTAMP": 'Infra',      "WABAG": 'Infra',

    # Realty — real estate developers
    "ASHIANA": 'Realty',      "BRIGADE": 'Realty',      "DLF": 'Realty',      "GODREJPROP": 'Realty',
    "HUBTOWN": 'Realty',      "KOLTEPATIL": 'Realty',      "MAHLIFE": 'Realty',      "MARATHON": 'Realty',
    "MAXESTATES": 'Realty',      "OBEROIRLTY": 'Realty',      "OMAXE": 'Realty',      "PHOENIXLTD": 'Realty',
    "PRESTIGE": 'Realty',      "PURVA": 'Realty',      "SOBHA": 'Realty',      "SURAJEST": 'Realty',
    "TRIL": 'Realty',

    # Other — no dedicated NSE index; Gate 4 passes unconditionally
    "AARTI": 'Other',      "AARTIIND": 'Other',      "ABFRL": 'Other',      "AKZOINDIA": 'Other',
    "ALKYLAMINE": 'Other',      "ALLCARGO": 'Other',      "AMBER": 'Other',      "AMBUJACEM": 'Other',
    "ANUPAM": 'Other',      "APOLLOPIPE": 'Other',      "ASIANPAINT": 'Other',      "ASTRAL": 'Other',
    "ATUL": 'Other',      "BALAJITELE": 'Other',      "BALMLAWRIE": 'Other',      "BATAINDIA": 'Other',
    "BAYERCROP": 'Other',      "BERGEPAINT": 'Other',      "BERGERINT": 'Other',      "BHAGERIA": 'Other',
    "BHARTIARTL": 'Other',      "BLUESTAR": 'Other',      "BLUESTARCO": 'Other',      "BUTTERFLY": 'Other',
    "CAMLINFINE": 'Other',      "CARBORUNIV": 'Other',      "CENTURYTEX": 'Other',      "CHAMBLFERT": 'Other',
    "CLEAN": 'Other',      "CONCOR": 'Other',      "CONTROLPR": 'Other',      "COROMANDEL": 'Other',
    "COSMOFILMS": 'Other',      "CROMPTON": 'Other',      "DALBHARAT": 'Other',      "DBCORP": 'Other',
    "DCMSHRIRAM": 'Other',      "DEEPAKFERT": 'Other',      "DEEPAKNTR": 'Other',      "DEEPIND": 'Other',
    "DHANUKA": 'Other',      "DMART": 'Other',      "DOLLAR": 'Other',      "EASEMYTRIP": 'Other',
    "EIDPARRY": 'Other',      "ELECTHERM": 'Other',      "EPL": 'Other',      "FAZE3Q": 'Other',
    "FINEORG": 'Other',      "FINOLEXIND": 'Other',      "FINPIPE": 'Other',      "FLUOROCHEM": 'Other',
    "GALAXYSURF": 'Other',      "GANDHITUBE": 'Other',      "GATI": 'Other',      "GHCL": 'Other',
    "GNFC": 'Other',      "GOLDIAM": 'Other',      "GRASIM": 'Other',      "GRINDWELL": 'Other',
    "GSFC": 'Other',      "HAVELLS": 'Other',      "HINDCOMPOS": 'Other',      "HITECHCORP": 'Other',
    "HMVL": 'Other',      "IDEA": 'Other',      "IFGLEXPOR": 'Other',      "INDHOTEL": 'Other',
    "INDIGO": 'Other',      "INDIGOPNTS": 'Other',      "INOXLEISUR": 'Other',      "INSECTICID": 'Other',
    "IONEXCHANG": 'Other',      "IRCTC": 'Other',      "JKCEMENT": 'Other',      "JKLAKSHMI": 'Other',
    "JKPAPER": 'Other',      "JUBLINGREA": 'Other',      "KAJARIACER": 'Other',      "KANSAINER": 'Other',
    "KARMA": 'Other',      "KDDL": 'Other',      "KEI": 'Other',      "KHADIM": 'Other',
    "KILPEST": 'Other',      "KITEX": 'Other',      "KPRMILL": 'Other',      "KSCL": 'Other',
    "LEMONTREE": 'Other',      "LIBERTSHOE": 'Other',      "LINC": 'Other',      "LINDEINDIA": 'Other',
    "LUXIND": 'Other',      "LXCHEM": 'Other',      "MAHAPEXLTD": 'Other',      "MALLCOM": 'Other',
    "MANYAVAR": 'Other',      "MARALOVER": 'Other',      "MAYURUNIQ": 'Other',      "MHRIL": 'Other',
    "MKPL": 'Other',      "MOLDTKPAC": 'Other',      "MSTCLTD": 'Other',      "NACLIND": 'Other',
    "NAVINFLUOR": 'Other',      "NBVENTURES": 'Other',      "NOCIL": 'Other',      "NYKAA": 'Other',
    "ORIENTELEC": 'Other',      "PAGEIND": 'Other',      "PATINTLOG": 'Other',      "PCJEWELLER": 'Other',
    "PEL": 'Other',      "PENIND": 'Other',      "PIDILITIND": 'Other',      "PIIND": 'Other',
    "PILANIINVS": 'Other',      "PIRAMALENT": 'Other',      "POCL": 'Other',      "POLYCAB": 'Other',
    "PRINCEPIPES": 'Other',      "PVRINOX": 'Other',      "QUESS": 'Other',      "RAMCOCEM": 'Other',
    "RAYMOND": 'Other',      "ROSSARI": 'Other',      "RPSGVENT": 'Other',      "RUSHIL": 'Other',
    "SAFARI": 'Other',      "SAREGAMA": 'Other',      "SBCL": 'Other',      "SHAKTIPUMP": 'Other',
    "SHOPERSTOP": 'Other',      "SHREECEM": 'Other',      "SNOWMAN": 'Other',      "SOLARINDS": 'Other',
    "SOMANYCERA": 'Other',      "SPICEJET": 'Other',      "SRF": 'Other',      "STCINDIA": 'Other',
    "STYRENIX": 'Other',      "SUMICHEM": 'Other',      "SUMIT": 'Other',      "SUPREMEIND": 'Other',
    "SURYAROSNI": 'Other',      "SYMPHONY": 'Other',      "TATACHEM": 'Other',      "TATAINVEST": 'Other',
    "TATVA": 'Other',      "TCIEXP": 'Other',      "TCNSBRANDS": 'Other',      "TEAMLEASE": 'Other',
    "TECHNOE": 'Other',      "THEMISSLTD": 'Other',      "TITAN": 'Other',      "TPVISION": 'Other',
    "TRANSINDIA": 'Other',      "TRENT": 'Other',      "TRIDENT": 'Other',      "TTKPRESTIG": 'Other',
    "TVTODAY": 'Other',      "UDAICEMENT": 'Other',      "UFLEX": 'Other',      "ULTRACEMCO": 'Other',
    "UPL": 'Other',      "V-GUARD": 'Other',      "V2RETAIL": 'Other',      "VAIBHAVGBL": 'Other',
    "VEDANT": 'Other',      "VESUVIUS": 'Other',      "VGUARD": 'Other',      "VIPIND": 'Other',
    "VOLTAS": 'Other',      "VSSL": 'Other',      "WALCHANNAG": 'Other',      "WATERBASE": 'Other',
    "WHIRLPOOL": 'Other',      "WONDERLA": 'Other',      "ZEEL": 'Other',      "ZODIACLOTH": 'Other',
    "ZOMATO": 'Other',

}
