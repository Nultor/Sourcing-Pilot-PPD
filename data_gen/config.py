"""Static configuration of the synthetic packaging-sourcing world.

Everything here is fictional: brands, ranges, suppliers and contract manufacturers
are invented and do not refer to real companies or products.
"""

SEED = 42

# Last closed quarter = "today" for the snapshot. History runs up to it,
# the forecast covers the next 3 years (12 quarters).
LAST_CLOSED_QUARTER = (2026, 3)
HISTORY_QUARTERS = 8
FORECAST_QUARTERS = 12
SNAPSHOT_DATE = "2026-10-01"
# Second snapshot, one quarter later (see snapshots.py).
NEXT_QUARTER = (2026, 4)
NEXT_SNAPSHOT_DATE = "2027-01-01"

# Saturation thresholds used for the planted ground truth.
WARN_THRESHOLD = 0.85
CRITICAL_THRESHOLD = 1.0

N_EXISTING_PRODUCTS = 70
N_NPD_PRODUCTS = 6
N_HEROES = 20

PLANTS = {"P100": "Main plant (ES)", "P200": "Secondary plant (FR)"}

BRANDS = ["Maison Orelia", "Solvane Pro", "Atelier Nuvo", "Vireo Hair"]

RANGES = [
    "Hydra Veil", "Curl Theory", "Silk Ritual", "Scalp Balance", "Color Shield",
    "Volume Craft", "Bond Restore", "Nutri Gloss", "Pure Detox", "Lumi Repair",
]

# Product type -> possible formats (ml) and the component families of its BOM.
PRODUCT_TYPES = {
    "shampoo": {"formats": [250, 300, 500, 1000], "bom": ["plastic_bottle", "cap", "label"]},
    "conditioner": {"formats": [200, 250, 500, 1000], "bom": ["plastic_bottle", "cap", "label"]},
    "mask": {"formats": [200, 250, 500], "bom": ["jar", "jar_lid", "label", "carton"]},
    "serum": {"formats": [30, 50, 90], "bom": ["glass_bottle", "pump", "label", "carton"]},
    "oil": {"formats": [50, 100], "bom": ["glass_bottle", "pump", "carton"]},
    "spray": {"formats": [150, 200], "bom": ["plastic_bottle", "spray_pump", "label"]},
    "cream": {"formats": [75, 150], "bom": ["tube", "carton"]},
    "refill": {"formats": [500, 1000], "bom": ["refill_pouch", "cap"]},
}

# Component families.
#   sized:          the component size (ml) equals the PF format
#   brand_specific: decorated with brand artwork -> one AC per PF, never shared
#   shared_prob:    probability to reuse an existing compatible AC (multi-brand standardisation)
#   price:          unit price range in EUR
#   capacity:       whether supplier line capacity is tracked in the buyer capacity file
FAMILIES = {
    "plastic_bottle": {"materials": ["PET", "rPET", "HDPE", "PP"], "technology": "blow moulding",
                       "sized": True, "brand_specific": False, "shared_prob": 0.5,
                       "price": (0.08, 0.35), "capacity": True},
    "glass_bottle": {"materials": ["glass", "extra-flint glass"], "technology": "glass moulding",
                     "sized": True, "brand_specific": False, "shared_prob": 0.4,
                     "price": (0.25, 0.90), "capacity": True},
    "jar": {"materials": ["PP", "glass"], "technology": "injection moulding",
            "sized": True, "brand_specific": False, "shared_prob": 0.5,
            "price": (0.15, 0.60), "capacity": True},
    "jar_lid": {"materials": ["PP", "PP + aluminium"], "technology": "injection moulding",
                "sized": True, "brand_specific": False, "shared_prob": 0.6,
                "price": (0.05, 0.20), "capacity": True},
    "cap": {"materials": ["PP", "HDPE"], "technology": "injection moulding",
            "sized": False, "brand_specific": False, "shared_prob": 0.8,
            "price": (0.02, 0.08), "capacity": True},
    "pump": {"materials": ["PP", "multi-material"], "technology": "pump assembly",
             "sized": False, "brand_specific": False, "shared_prob": 0.7,
             "price": (0.15, 0.45), "capacity": True},
    "spray_pump": {"materials": ["PP", "multi-material"], "technology": "pump assembly",
                   "sized": False, "brand_specific": False, "shared_prob": 0.7,
                   "price": (0.12, 0.35), "capacity": True},
    "tube": {"materials": ["PE", "rPE", "PE/EVOH laminate"], "technology": "tube extrusion",
             "sized": True, "brand_specific": True, "shared_prob": 0.0,
             "price": (0.08, 0.25), "capacity": True},
    "refill_pouch": {"materials": ["PET/PE laminate", "mono-PE"], "technology": "pouch converting",
                     "sized": True, "brand_specific": True, "shared_prob": 0.0,
                     "price": (0.06, 0.20), "capacity": True},
    "label": {"materials": ["PE film", "PP film", "paper"], "technology": "label printing",
              "sized": False, "brand_specific": True, "shared_prob": 0.0,
              "price": (0.01, 0.05), "capacity": False},
    "carton": {"materials": ["board", "recycled board"], "technology": "carton printing",
               "sized": False, "brand_specific": True, "shared_prob": 0.0,
               "price": (0.05, 0.25), "capacity": False},
}

NECKS = {"cap": ["24/410", "28/410"], "pump": ["20/400", "24/410"], "spray_pump": ["24/410"]}

# How each source system names a component family. This is one of the main
# sources of inconsistency between tables ("bottle" vs "plastic bottle" vs "flacon").
FAMILY_NAMES = {
    #                 canonical (master)   finance        site                  buyer file
    "plastic_bottle": ("Bottle",          "BTL",         "plastic bottle",     "Flacon"),
    "glass_bottle":   ("Glass bottle",    "BTL GLASS",   "bottle glass",       "Flacon verre"),
    "jar":            ("Jar",             "JAR",         "pot",                "Pot"),
    "jar_lid":        ("Jar lid",         "LID",         "lid",                "Couvercle"),
    "cap":            ("Cap",             "CAP",         "closure",            "Bouchon"),
    "pump":           ("Pump",            "PUMP",        "dispenser pump",     "Pompe"),
    "spray_pump":     ("Spray pump",      "SPRAY",       "spray",              "Spray"),
    "tube":           ("Tube",            "TUBE",        "laminate tube",      "Tube"),
    "refill_pouch":   ("Refill pouch",    "POUCH",       "doypack",            "Doypack"),
    "label":          ("Label",           "LBL",         "sticker label",      "Etiquette"),
    "carton":         ("Folding carton",  "CARTON",      "box",                "Etui"),
}

# Packaging suppliers: (legal name, short name, country, families).
SUPPLIERS = [
    ("Nordpack Industries SAS", "Nordpack", "FR", ["plastic_bottle", "jar", "jar_lid"]),
    ("Iberplast Envases S.L.", "Iberplast", "ES", ["plastic_bottle", "cap"]),
    ("Oberwald Kunststoff GmbH", "Oberwald", "DE", ["plastic_bottle", "jar", "jar_lid", "cap"]),
    ("Valtera Glass S.p.A.", "Valtera", "IT", ["glass_bottle", "jar"]),
    ("Vitralis Verre SAS", "Vitralis", "FR", ["glass_bottle"]),
    ("Helvo Dispensing GmbH", "Helvo", "DE", ["pump", "spray_pump"]),
    ("Pumptec Systems Inc", "Pumptec", "US", ["pump", "spray_pump"]),
    ("Castell Closures S.L.", "Castell", "ES", ["cap", "jar_lid"]),
    ("Arden Labels Ltd", "Arden", "GB", ["label"]),
    ("Etiquettes Moderne SARL", "Etiquettes Moderne", "FR", ["label"]),
    ("Cartonnerie Duval SA", "Duval", "FR", ["carton"]),
    ("Sanroque Carton S.A.", "Sanroque", "ES", ["carton"]),
    ("Lusoflex Tubes Lda", "Lusoflex", "PT", ["tube"]),
    ("Polyform Packaging Group Ltd", "Polyform", "GB", ["tube", "refill_pouch"]),
    ("Medina Flexibles S.L.", "Medina", "ES", ["refill_pouch"]),
]

# Contract manufacturers: extra (stretch) capacity that is available but not used today.
CONTRACT_MANUFACTURERS = [
    ("Fillpro Contract Manufacturing SA", "Fillpro", "FR"),
    ("Cosmolab Iberica S.L.", "Cosmolab", "ES"),
    ("Duofill GmbH", "Duofill", "DE"),
    ("Atlas Beauty Manufacturing Ltd", "Atlas", "GB"),
]

CURRENCY_BY_COUNTRY = {"US": "USD", "GB": "GBP"}  # everything else EUR
FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17}

# Planted capacity cases (count per case). See saturation.py for definitions.
PLANTED_CASES = {
    "both_saturated": 3,
    "baseline_only": 4,
    "future_breach": 3,
    "single_quarter_spike": 2,   # decoy: one-quarter forecast spike, not structural
    "monthly_capacity_entry": 2,  # decoy: buyer entered a monthly capacity in a quarterly column
    "cm_not_qualified": 2,        # trap: CM capacity listed but CM not qualified for the AC
}
