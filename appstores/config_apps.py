from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

SA_APPS = [
    {
        "brand_name": "Standard Bank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "com.sbg.mobile.phone",
        "apple_app_id": "528239110",
        "apple_app_name": "standard-bank-stanbic-bank",
    },
    {
        "brand_name": "Absa",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "com.barclays.absa.banking",
        "apple_app_id": "1085620596",
        "apple_app_name": "absa-banking",
    },
    {
        "brand_name": "Capitec",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "capitec.acuity.mobile.prod",
        "apple_app_id": "1217842108",
        "apple_app_name": "capitec-bank",
    },
    {
        "brand_name": "FNB",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "za.co.fnb.connect.itt",
        "apple_app_id": "450094779",
        "apple_app_name": "fnb-banking-app",
    },
    {
        "brand_name": "Nedbank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "za.co.nedbank",
        "apple_app_id": "1260981758",
        "apple_app_name": "nedbank-money",
    },
    {
        "brand_name": "African Bank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "za.co.android.africanbank",
        "apple_app_id": "1357204405",
        "apple_app_name": "african-bank",
    },
    {
        "brand_name": "Discovery Bank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "bank.discovery.banking.production.release",
        "apple_app_id": "1451167079",
        "apple_app_name": "discovery-bank",
    },
    {
        "brand_name": "Investec",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "com.investec.app",
        "apple_app_id": "603019723",
        "apple_app_name": "investec-private-client",
    },
    {
        "brand_name": "RMB Private Bank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "za.co.fnb.connect.rmbpb",
        "apple_app_id": None,
        "apple_app_name": "rmb-private-bank",
    },
    {
        "brand_name": "GoTyme Bank",
        "sector": "banking",
        "country": "ZA",
        "google_play_id": "za.co.gotyme",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "MTN",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "com.mtnapp",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "MTN MoMo SA",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "com.momosa",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Vodacom VodaPay",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "za.co.vodacom.vodapay",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Cell C",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "com.app.cellc",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Telkom",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "za.co.telkom.mytelkomapp",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Rain",
        "sector": "telecom",
        "country": "ZA",
        "google_play_id": "za.co.raingo.www.pwa",
        "apple_app_id": None,
        "apple_app_name": None,
    },

    # --- QSR apps ---
    {
        "brand_name": "KFC South Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "com.kfc.sa",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Nando's South Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "co.za.nandos.nandosapp",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Burger King South Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "za.co.wigroup.burgerking",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Steers",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "za.co.steers.android",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Debonairs Pizza",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "mobi.debonairspizza.iosapp",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Spur Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "com.spur.africa",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "RocoMamas South Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "com.rocomamas.app",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Wimpy South Africa",
        "sector": "qsr",
        "country": "ZA",
        "google_play_id": "za.co.wigroup.wimpy",
        "apple_app_id": None,
        "apple_app_name": None,
    },

    # --- Delivery / retail ---
    {
        "brand_name": "Mr D Food",
        "sector": "delivery",
        "country": "ZA",
        "google_play_id": "com.mrd.food",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Checkers Sixty60",
        "sector": "retail",
        "country": "ZA",
        "google_play_id": "za.co.shoprite.sixty60",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Pick n Pay Smart Shopper",
        "sector": "retail",
        "country": "ZA",
        "google_play_id": "za.co.pnp.smartshopper",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "SPAR Mobile",
        "sector": "retail",
        "country": "ZA",
        "google_play_id": "za.co.sparmobile",
        "apple_app_id": None,
        "apple_app_name": None,
    },
    {
        "brand_name": "Woolworths",
        "sector": "retail",
        "country": "ZA",
        "google_play_id": "com.awfs.coordination",
        "apple_app_id": None,
        "apple_app_name": None,
    },
]

REVIEWS_PER_APP = 50
COUNTRY_CODE = "za"
LANG_CODE = "en"

# Rolling window (same reasoning as core/platform_upsert.py): a fixed cutoff
# would mean every weekly run re-fetches all history forever. Dedup on
# review_id in pipeline/supabase_upsert.py makes the overlap free.
REVIEW_LOOKBACK_DAYS = 10
MIN_REVIEW_DATE = (datetime.now(timezone.utc) - timedelta(days=REVIEW_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
