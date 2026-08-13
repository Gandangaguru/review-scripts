"""Brands to scrape from HelloPeter.

slug = the part after hellopeter.com/ on the brand's review page.
Run `python verify_slugs.py` after editing to confirm every slug is valid.
industry = specific label; the consolidated bucket is derived in platform_upsert.py.
"""

HELLOPETER_BUSINESSES = [
    # --- Banking ---
    {"brand_name": "Absa", "slug": "absa", "industry": "Banking"},
    {"brand_name": "Capitec", "slug": "capitec-bank", "industry": "Banking"},
    {"brand_name": "FNB", "slug": "first-national-bank", "industry": "Banking"},
    {"brand_name": "Standard Bank", "slug": "standard-bank", "industry": "Banking"},
    {"brand_name": "Nedbank", "slug": "nedbank", "industry": "Banking"},
    {"brand_name": "African Bank", "slug": "african-bank", "industry": "Banking"},
    {"brand_name": "Discovery Bank", "slug": "discovery-bank", "industry": "Banking"},
    {"brand_name": "TymeBank", "slug": "tymebank", "industry": "Banking"},

    # --- Telecoms / ISP ---
    {"brand_name": "Vodacom", "slug": "vodacom", "industry": "ISP"},
    {"brand_name": "MTN", "slug": "mtn", "industry": "ISP"},
    {"brand_name": "Cell C", "slug": "cell-c", "industry": "ISP"},
    {"brand_name": "Telkom", "slug": "telkom", "industry": "ISP"},
    {"brand_name": "Rain", "slug": "rain-internet-service-provider", "industry": "ISP"},

    # --- Insurance ---
    {"brand_name": "Discovery Insure", "slug": "discovery-insure", "industry": "Insurance"},
    {"brand_name": "OUTsurance", "slug": "outsurance", "industry": "Insurance"},
    {"brand_name": "Santam", "slug": "santam", "industry": "Insurance"},
    {"brand_name": "MiWay", "slug": "miway", "industry": "Insurance"},

    # --- Retail ---
    {"brand_name": "Takealot", "slug": "take2takealot", "industry": "Retail"},
    {"brand_name": "Checkers Sixty60", "slug": "checkers-sixty60", "industry": "Retail"},
    {"brand_name": "Pick n Pay", "slug": "pick-n-pay", "industry": "Retail"},
    {"brand_name": "Woolworths", "slug": "woolworths", "industry": "Retail"},
    {"brand_name": "Mr Price", "slug": "mr-price", "industry": "Retail"},
    {"brand_name": "Edgars", "slug": "edgars", "industry": "Retail"},

    # --- Restaurants / delivery ---
    {"brand_name": "Mr D Food", "slug": "mr-delivery", "industry": "Restaurants"},
    {"brand_name": "KFC South Africa", "slug": "kfc", "industry": "Restaurants"},
    {"brand_name": "Nando's", "slug": "nandos", "industry": "Restaurants"},
    {"brand_name": "Debonairs Pizza", "slug": "debonairs-pizza", "industry": "Restaurants"},
]
