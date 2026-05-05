"""
GA4 BigQuery Export Sample Data Generator
==========================================
Generates 90 days of realistic GA4 e-commerce event data in newline-delimited
JSON format, suitable for direct BigQuery upload.

Anomalies injected:
  A. PII leakage in page_location / page_referrer (event_params)
  B. Cross-domain tracking failure (payment gateway referral)
  C. Missing session_start events (bad GTM deploy window)
  D. Missing attribution → (not set) (CMP/consent blocking)
  E. Session timeout (no session_start event)

Outputs:
  events_YYYYMMDD.jsonl       — NDJSON, one event per line, one file per day
  ga4_schema.json             — BigQuery JSON schema for bq load
  anomaly_manifest.csv        — Anomaly registry with date ranges and descriptions
"""

import json
import csv
import os
import uuid
import random
import hashlib
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timedelta, timezone
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# =============================================================================
# CONFIG — adjust these to change scale, dates, and anomaly windows
# =============================================================================

START_DATE = datetime(2025, 10, 1)
END_DATE   = datetime(2025, 12, 31)

# Baseline traffic
MIN_SESSIONS_PER_DAY = 600
MAX_SESSIONS_PER_DAY = 1400

# User pool — realistic returning user ratio (~30%)
USER_POOL_SIZE = 8000
RETURNING_USER_RATIO = 0.30

# Site config
HOSTNAME = "www.nordhaus-living.com"
STREAM_ID = "3847291056"
CURRENCY  = "EUR"
USD_RATE  = 1.08  # EUR → USD conversion

# Funnel conversion rates (per session)
PURCHASE_RATE      = 0.032
ADD_TO_CART_RATE   = 0.18
VIEW_ITEM_RATE     = 0.55
BEGIN_CHECKOUT_RATE = 0.09

# Anomaly windows (inclusive)
ANOMALY_A_PII_START   = datetime(2025, 10, 22)
ANOMALY_A_PII_END     = datetime(2025, 10, 27)   # 5-day window

ANOMALY_B_XDOMAIN_START = datetime(2025, 11, 5)
ANOMALY_B_XDOMAIN_END   = datetime(2025, 11, 30)  # 25-day window

ANOMALY_C_NO_SESSION_START_START = datetime(2025, 11, 14)
ANOMALY_C_NO_SESSION_START_END   = datetime(2025, 11, 21)  # 7-day window

ANOMALY_D_NO_ATTR_START = datetime(2025, 12, 3)
ANOMALY_D_NO_ATTR_END   = datetime(2025, 12, 18)  # 15-day window

ANOMALY_E_TIMEOUT_START = datetime(2025, 12, 19)
ANOMALY_E_TIMEOUT_END   = datetime(2025, 12, 29)

# Fraction of sessions affected by each anomaly (when window is active)
ANOMALY_A_AFFECTED_RATIO   = 0.08   # 8% of sessions leak PII
ANOMALY_B_AFFECTED_RATIO   = 0.12   # 12% of sessions lose cross-domain link
ANOMALY_C_SUPPRESSION_RATE = 1.0    # 100% of session_starts dropped in window
ANOMALY_D_AFFECTED_RATIO   = 0.25   # 25% of sessions lose attribution
ANOMALY_E_AFFECTED_RATIO = 0.06  # 6% of sessions in window

OUTPUT_DIR = "./outputs"

# =============================================================================
# Experiment config
# =============================================================================
# Single experiment: Black Friday 2025
EXPERIMENTS = {
    "BF2025": {
        "tool_id": "EXP",
        "experience_id": "BF2025",
        "n_variants": 2,
        "start": datetime(2025, 11, 1),
        "end": datetime(2025, 11, 28),
        "pages": ["/products/"],  # prefix match for PDPs
        "sample_rate": 1.0,        # apply to all eligible users
    }
}

# Runtime experiment impression counters: {exp_key: {date_str: {variant_string: count}}}
EXPERIMENT_STATS = {}

# =============================================================================
# REFERENCE DATA
# =============================================================================

PRODUCTS = [
    {"item_id": "SOFA-001", "item_name": "Oslo Corner Sofa", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Sofas", "price": 1299.00},
    {"item_id": "SOFA-002", "item_name": "Bergen 3-Seater", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Sofas", "price": 849.00},
    {"item_id": "CHAIR-001", "item_name": "Fjord Accent Chair", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Chairs", "price": 399.00},
    {"item_id": "CHAIR-002", "item_name": "Tromso Dining Chair", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Chairs", "price": 189.00},
    {"item_id": "TABLE-001", "item_name": "Stavanger Oak Desk", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Tables", "price": 699.00},
    {"item_id": "TABLE-002", "item_name": "Lofoten Coffee Table", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Tables", "price": 329.00},
    {"item_id": "BED-001",   "item_name": "Voss King Bed Frame", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Beds", "price": 1099.00},
    {"item_id": "BED-002",   "item_name": "Alesund Storage Bed", "item_brand": "Nordhaus", "item_category": "Furniture", "item_category2": "Beds", "price": 799.00},
    {"item_id": "LIGHT-001", "item_name": "Kirkenes Pendant Lamp", "item_brand": "LysNord", "item_category": "Lighting", "item_category2": "Pendants", "price": 149.00},
    {"item_id": "LIGHT-002", "item_name": "Narvik Floor Lamp", "item_brand": "LysNord", "item_category": "Lighting", "item_category2": "Floor Lamps", "price": 229.00},
    {"item_id": "RUG-001",   "item_name": "Tana Wool Rug 200x300", "item_brand": "FjordTextile", "item_category": "Textiles", "item_category2": "Rugs", "price": 449.00},
    {"item_id": "RUG-002",   "item_name": "Senja Jute Runner", "item_brand": "FjordTextile", "item_category": "Textiles", "item_category2": "Rugs", "price": 129.00},
]

PAGES = [
    "/",
    "/collections/sofas",
    "/collections/chairs",
    "/collections/tables",
    "/collections/beds",
    "/collections/lighting",
    "/collections/rugs",
    "/collections/new-arrivals",
    "/collections/sale",
    "/products/oslo-corner-sofa",
    "/products/bergen-3-seater",
    "/products/fjord-accent-chair",
    "/products/tromso-dining-chair",
    "/products/stavanger-oak-desk",
    "/products/lofoten-coffee-table",
    "/products/voss-king-bed-frame",
    "/products/kirkenes-pendant-lamp",
    "/products/tana-wool-rug",
    "/about",
    "/contact",
    "/faq",
    "/delivery-returns",
    "/cart",
    "/checkout",
    "/checkout/address",
    "/checkout/payment",
    "/order-confirmation",
    "/account/login",
    "/account/register",
    "/account/orders",
]

PAGE_TITLES = {
    "/": "Nordhaus Living – Scandinavian Furniture",
    "/collections/sofas": "Sofas | Nordhaus Living",
    "/collections/chairs": "Chairs | Nordhaus Living",
    "/collections/tables": "Tables | Nordhaus Living",
    "/collections/beds": "Beds | Nordhaus Living",
    "/collections/lighting": "Lighting | Nordhaus Living",
    "/collections/rugs": "Rugs & Textiles | Nordhaus Living",
    "/collections/new-arrivals": "New Arrivals | Nordhaus Living",
    "/collections/sale": "Sale | Nordhaus Living",
    "/products/oslo-corner-sofa": "Oslo Corner Sofa | Nordhaus Living",
    "/products/bergen-3-seater": "Bergen 3-Seater | Nordhaus Living",
    "/products/fjord-accent-chair": "Fjord Accent Chair | Nordhaus Living",
    "/products/tromso-dining-chair": "Tromso Dining Chair | Nordhaus Living",
    "/products/stavanger-oak-desk": "Stavanger Oak Desk | Nordhaus Living",
    "/products/lofoten-coffee-table": "Lofoten Coffee Table | Nordhaus Living",
    "/products/voss-king-bed-frame": "Voss King Bed Frame | Nordhaus Living",
    "/products/kirkenes-pendant-lamp": "Kirkenes Pendant Lamp | Nordhaus Living",
    "/products/tana-wool-rug": "Tana Wool Rug 200x300 | Nordhaus Living",
    "/about": "About Us | Nordhaus Living",
    "/contact": "Contact | Nordhaus Living",
    "/faq": "FAQ | Nordhaus Living",
    "/delivery-returns": "Delivery & Returns | Nordhaus Living",
    "/cart": "Your Cart | Nordhaus Living",
    "/checkout": "Checkout | Nordhaus Living",
    "/checkout/address": "Shipping Address | Nordhaus Living",
    "/checkout/payment": "Payment | Nordhaus Living",
    "/order-confirmation": "Order Confirmed | Nordhaus Living",
    "/account/login": "Login | Nordhaus Living",
    "/account/register": "Create Account | Nordhaus Living",
    "/account/orders": "My Orders | Nordhaus Living",
}

TRAFFIC_SOURCES = [
    {"source": "google",       "medium": "organic",  "campaign": None,              "gclid": False, "weight": 0.35},
    {"source": "google",       "medium": "cpc",      "campaign": "brand-search-de", "gclid": True,  "weight": 0.18},
    {"source": "google",       "medium": "cpc",      "campaign": "furniture-de",    "gclid": True,  "weight": 0.10},
    {"source": "(direct)",     "medium": "(none)",   "campaign": "(direct)",        "gclid": False, "weight": 0.15},
    {"source": "instagram.com","medium": "social",   "campaign": "autumn-collection","gclid": False, "weight": 0.08},
    {"source": "newsletter",   "medium": "email",    "campaign": "oct-promo",       "gclid": False, "weight": 0.06},
    {"source": "bing",         "medium": "cpc",      "campaign": "furniture-bing",  "gclid": False, "weight": 0.04},
    {"source": "pinterest.com","medium": "social",   "campaign": "home-inspiration","gclid": False, "weight": 0.04},
]

DEVICES = [
    {"category": "desktop", "os": "Windows", "os_version": "10", "browser": "Chrome",  "browser_version": "120.0.0.0", "weight": 0.38},
    {"category": "desktop", "os": "macOS",   "os_version": "14.1","browser": "Safari",  "browser_version": "17.1",      "weight": 0.18},
    {"category": "mobile",  "os": "Android", "os_version": "13",  "browser": "Chrome",  "browser_version": "120.0.6099","weight": 0.22},
    {"category": "mobile",  "os": "iOS",     "os_version": "17.1","browser": "Safari",  "browser_version": "17.1",      "weight": 0.17},
    {"category": "desktop", "os": "Windows", "os_version": "11",  "browser": "Edge",    "browser_version": "120.0.0.0", "weight": 0.03},
    {"category": "tablet",  "os": "iOS",     "os_version": "17.0","browser": "Safari",  "browser_version": "17.0",      "weight": 0.02},
]

MOBILE_BRANDS = {
    "Android": [("Samsung", "Galaxy S23"), ("Samsung", "Galaxy A54"), ("Google", "Pixel 7"), ("OnePlus", "11")],
    "iOS":     [("Apple", "iPhone 15"), ("Apple", "iPhone 14"), ("Apple", "iPhone 13 Pro")],
}

GEO_DISTRIBUTION = [
    {"country": "Germany",        "continent": "Europe", "sub_continent": "Western Europe", "region": "Bavaria",            "city": "Munich",       "weight": 0.32},
    {"country": "Germany",        "continent": "Europe", "sub_continent": "Western Europe", "region": "Berlin",             "city": "Berlin",       "weight": 0.22},
    {"country": "Germany",        "continent": "Europe", "sub_continent": "Western Europe", "region": "Hamburg",            "city": "Hamburg",      "weight": 0.12},
    {"country": "Austria",        "continent": "Europe", "sub_continent": "Western Europe", "region": "Vienna",             "city": "Vienna",       "weight": 0.09},
    {"country": "Switzerland",    "continent": "Europe", "sub_continent": "Western Europe", "region": "Zurich",             "city": "Zurich",       "weight": 0.07},
    {"country": "Netherlands",    "continent": "Europe", "sub_continent": "Western Europe", "region": "North Holland",      "city": "Amsterdam",    "weight": 0.06},
    {"country": "United Kingdom", "continent": "Europe", "sub_continent": "Northern Europe","region": "England",            "city": "London",       "weight": 0.05},
    {"country": "France",         "continent": "Europe", "sub_continent": "Western Europe", "region": "Île-de-France",      "city": "Paris",        "weight": 0.04},
    {"country": "Sweden",         "continent": "Europe", "sub_continent": "Northern Europe","region": "Stockholm County",   "city": "Stockholm",    "weight": 0.03},
]

PII_EMAIL_PARAMS = ["email", "user_email", "customer_email", "e"]
PII_PHONE_PARAMS = ["phone", "tel", "mobile"]
PII_NAME_PARAMS  = ["name", "first_name", "user_name"]

PAYMENT_GATEWAY_DOMAIN = "pay.stripe.com"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def weighted_choice(options):
    weights = [o["weight"] for o in options]
    return random.choices(options, weights=weights, k=1)[0]

def to_micros(dt):
    """Convert datetime to microseconds since epoch (UTC)."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000)

def generate_user_pseudo_id():
    return uuid.uuid4().hex

def generate_session_id():
    return random.randint(1_000_000_000, 9_999_999_999)

def in_window(date, start, end):
    return start <= date <= end

def gclid_value():
    return "Cj0K" + uuid.uuid4().hex[:40]

def make_event_param(key, string_value=None, int_value=None, double_value=None, float_value=None):
    value = {}
    if string_value is not None:
        value["string_value"] = string_value
    if int_value is not None:
        value["int_value"] = int_value
    if double_value is not None:
        value["double_value"] = double_value
    if float_value is not None:
        value["float_value"] = float_value
    return {"key": key, "value": value}

def sessions_for_day(date):
    """Weekday/weekend seasonality + slight upward trend toward December."""
    day_of_week = date.weekday()  # 0=Mon, 6=Sun
    weekday_factor = 1.0 if day_of_week < 5 else 0.72
    days_elapsed = (date - START_DATE).days
    trend_factor = 1.0 + (days_elapsed / 90) * 0.15
    base = random.randint(MIN_SESSIONS_PER_DAY, MAX_SESSIONS_PER_DAY)
    return max(1, int(base * weekday_factor * trend_factor))

def pick_traffic_source():
    return weighted_choice(TRAFFIC_SOURCES)

def pick_device():
    return weighted_choice(DEVICES)

def pick_geo():
    return weighted_choice(GEO_DISTRIBUTION)

def build_page_url(path, params=None):
    base = f"https://{HOSTNAME}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"
    return base

def pii_polluted_url(page_path):
    """Generate a URL with PII leaked into query parameters."""
    pii_type = random.choice(["email", "phone", "name"])
    if pii_type == "email":
        param = random.choice(PII_EMAIL_PARAMS)
        value = fake.email()
    elif pii_type == "phone":
        param = random.choice(PII_PHONE_PARAMS)
        value = fake.numerify("+49###########")
    else:
        param = random.choice(PII_NAME_PARAMS)
        value = fake.last_name().replace(" ", "_")
    return build_page_url(page_path, {param: value})

def make_user_property(key, string_value=None, int_value=None, set_timestamp_micros=None):
    value = {}
    if string_value is not None:
        value["string_value"] = string_value
    if int_value is not None:
        value["int_value"] = int_value
    if set_timestamp_micros:
        value["set_timestamp_micros"] = set_timestamp_micros
    return {"key": key, "value": value}


# =============================================================================
# Experiment helpers
# =============================================================================
def assign_variant_for_user(user_pseudo_id, experience_id, n_variants):
    """Deterministically assign a variant index (0..n_variants-1) per user + experience."""
    h = hashlib.md5((user_pseudo_id + experience_id).encode()).hexdigest()
    return int(h[:8], 16) % n_variants


def generate_exp_variant_string(tool_id, experience_id, variant_index):
    """Return exp_variant_string in format XXX-YYYYYYYYY-ZZZZZZZZ.

    We format the variant id as two-digit zero-padded number (01,02,...).
    """
    variant_id = str(variant_index + 1).zfill(2)
    return f"{tool_id}-{experience_id}-{variant_id}"



# =============================================================================
# USER POOL
# =============================================================================

def build_user_pool(size):
    """Pre-generate a pool of users with stable first-touch attribution."""
    pool = []
    for _ in range(size):
        src = pick_traffic_source()
        first_touch_dt = START_DATE - timedelta(days=random.randint(0, 365))
        pool.append({
            "user_pseudo_id": generate_user_pseudo_id(),
            "user_id": fake.uuid4() if random.random() < 0.40 else None,
            "first_touch_timestamp": to_micros(first_touch_dt),
            "first_touch_source": src["source"],
            "first_touch_medium": src["medium"],
            "first_touch_campaign": src["campaign"] or "(direct)",
            "session_count": 0,
            "ltv_revenue": 0.0,
            "preferred_device": pick_device(),
            "geo": pick_geo(),
        })
    return pool

# =============================================================================
# EVENT BUILDERS
# =============================================================================

def base_event(user, session_id, session_number, event_name, event_dt,
               page_path, page_referrer, traffic_src, device, geo,
               prev_timestamp=None, batch_event_index=0, batch_ordering_id=1,
               batch_page_id=1):
    """Construct the base event dict matching BQ GA4 export schema."""
    ts_micros = to_micros(event_dt)
    page_url  = build_page_url(page_path)
    page_title = PAGE_TITLES.get(page_path, "Nordhaus Living")

    event_params = [
        make_event_param("page_location",      string_value=page_url),
        make_event_param("page_title",         string_value=page_title),
        make_event_param("page_referrer",      string_value=page_referrer),
        make_event_param("ga_session_id",      int_value=session_id),
        make_event_param("ga_session_number",  int_value=session_number),
        make_event_param("session_engaged",    string_value="1"),
    ]

    # Consent — mostly "Yes", a small % "No"
    ads_storage       = "Yes" if random.random() > 0.08 else "No"
    analytics_storage = "Yes" if random.random() > 0.06 else "No"

    # Collected traffic source (event-level UTM snapshot)
    collected_ts = {}
    if traffic_src["source"] and traffic_src["source"] != "(direct)":
        collected_ts["manual_source"] = traffic_src["source"]
        collected_ts["manual_medium"] = traffic_src["medium"]
        if traffic_src["campaign"]:
            collected_ts["manual_campaign_name"] = traffic_src["campaign"]
    if traffic_src.get("gclid"):
        collected_ts["gclid"] = gclid_value()

    # session_traffic_source_last_click
    stslc = None
    if traffic_src["source"] and traffic_src["source"] != "(direct)":
        stslc = {
            "manual_campaign": {
                "source":        traffic_src["source"],
                "medium":        traffic_src["medium"],
                "campaign_name": traffic_src["campaign"],
                "campaign_id":   hashlib.md5((traffic_src["campaign"] or "").encode()).hexdigest()[:8] if traffic_src["campaign"] else None,
                "term":          None,
                "content":       None,
                "source_platform": None,
                "creative_format": None,
            }
        }

    # Device
    dev = {
        "category":                device["category"],
        "operating_system":        device["os"],
        "operating_system_version":device["os_version"],
        "web_info": {
            "browser":         device["browser"],
            "browser_version": device["browser_version"],
            "hostname":        HOSTNAME,
        },
        "language":               random.choice(["de-DE", "en-GB", "en-US", "de-AT"]),
        "time_zone_offset_seconds": 3600,
        "is_limited_ad_tracking": False,
    }
    if device["category"] in ("mobile", "tablet") and device["os"] in MOBILE_BRANDS:
        brand, model = random.choice(MOBILE_BRANDS[device["os"]])
        dev["mobile_brand_name"] = brand
        dev["mobile_model_name"] = model
        dev["mobile_marketing_name"] = model

    return {
        # ── Event ──────────────────────────────────────────────
        "event_date":                    event_dt.strftime("%Y%m%d"),
        "event_timestamp":               ts_micros,
        "event_previous_timestamp":      prev_timestamp,
        "event_name":                    event_name,
        "event_value_in_usd":            None,
        "event_bundle_sequence_id":      random.randint(100000, 999999),
        "event_server_timestamp_offset": random.randint(500000, 3000000),
        "batch_event_index":             batch_event_index,
        "batch_ordering_id":             batch_ordering_id,
        "batch_page_id":                 batch_page_id,
        "event_params":                  event_params,
        # ── User ───────────────────────────────────────────────
        "user_pseudo_id":                user["user_pseudo_id"],
        "user_id":                       user["user_id"],
        "user_first_touch_timestamp":    user["first_touch_timestamp"],
        "is_active_user":                True,
        "privacy_info": {
            "ads_storage":          ads_storage,
            "analytics_storage":    analytics_storage,
            "uses_transient_token": "No",
        },
        "user_properties": [
            make_user_property("logged_in",
                               string_value="true" if user["user_id"] else "false",
                               set_timestamp_micros=user["first_touch_timestamp"]),
        ],
        "user_ltv": {
            "revenue":  user["ltv_revenue"],
            "currency": CURRENCY,
        },
        # ── Traffic source (user-level, first-touch, immutable) ─
        "traffic_source": {
            "source":  user["first_touch_source"],
            "medium":  user["first_touch_medium"],
            "name":    user["first_touch_campaign"],
        },
        # ── Collected traffic source (event-level UTM snapshot) ─
        "collected_traffic_source": collected_ts if collected_ts else None,
        # ── Session last-click attribution ─────────────────────
        "session_traffic_source_last_click": stslc,
        # ── Device ─────────────────────────────────────────────
        "device": dev,
        # ── Geo ────────────────────────────────────────────────
        "geo": {
            "continent":     geo["continent"],
            "sub_continent": geo["sub_continent"],
            "country":       geo["country"],
            "region":        geo["region"],
            "city":          geo["city"],
            "metro":         None,
        },
        # ── Stream ─────────────────────────────────────────────
        "stream_id": STREAM_ID,
        "platform":  "WEB",
        # ── Ecommerce (populated later for purchase events) ────
        "ecommerce": None,
        "items":     [],
    }


def add_event_param(event, key, string_value=None, int_value=None, double_value=None):
    event["event_params"].append(
        make_event_param(key, string_value=string_value,
                         int_value=int_value, double_value=double_value)
    )


def make_session_start_event(user, session_id, session_number, event_dt,
                              page_path, page_referrer, traffic_src, device, geo):
    ev = base_event(user, session_id, session_number, "session_start",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=None, batch_event_index=0)
    add_event_param(ev, "entrances", int_value=1)
    return ev


def make_page_view_event(user, session_id, session_number, event_dt,
                          page_path, page_referrer, traffic_src, device, geo,
                          prev_ts, is_entrance=False, batch_event_index=0, batch_page_id=1):
    ev = base_event(user, session_id, session_number, "page_view",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts,
                    batch_event_index=batch_event_index,
                    batch_page_id=batch_page_id)
    if is_entrance:
        add_event_param(ev, "entrances", int_value=1)
    add_event_param(ev, "engagement_time_msec", int_value=random.randint(2000, 120000))
    return ev


def make_scroll_event(user, session_id, session_number, event_dt,
                       page_path, page_referrer, traffic_src, device, geo, prev_ts):
    ev = base_event(user, session_id, session_number, "scroll",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts)
    add_event_param(ev, "percent_scrolled", int_value=90)
    add_event_param(ev, "engagement_time_msec", int_value=random.randint(5000, 180000))
    return ev


def make_view_item_event(user, session_id, session_number, event_dt,
                          page_path, page_referrer, traffic_src, device, geo,
                          prev_ts, product):
    ev = base_event(user, session_id, session_number, "view_item",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts)
    add_event_param(ev, "currency",  string_value=CURRENCY)
    add_event_param(ev, "value",     double_value=product["price"])
    ev["items"] = [{
        "item_id":       product["item_id"],
        "item_name":     product["item_name"],
        "item_brand":    product["item_brand"],
        "item_category": product["item_category"],
        "item_category2":product["item_category2"],
        "price":         product["price"],
        "price_in_usd":  round(product["price"] * USD_RATE, 2),
        "quantity":      1,
        "item_revenue":  None,
        "item_revenue_in_usd": None,
        "item_refund":   None,
        "item_refund_in_usd": None,
    }]
    return ev


def make_experience_impression_event(user, session_id, session_number, event_dt,
                                     page_path, page_referrer, traffic_src, device, geo,
                                     prev_ts, exp_variant_string,
                                     batch_event_index=0, batch_page_id=1):
    ev = base_event(user, session_id, session_number, "experience_impression",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts,
                    batch_event_index=batch_event_index,
                    batch_page_id=batch_page_id)
    add_event_param(ev, "exp_variant_string", string_value=exp_variant_string)
    return ev


def make_add_to_cart_event(user, session_id, session_number, event_dt,
                            page_path, page_referrer, traffic_src, device, geo,
                            prev_ts, product, quantity=1):
    ev = base_event(user, session_id, session_number, "add_to_cart",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts)
    add_event_param(ev, "currency", string_value=CURRENCY)
    add_event_param(ev, "value",    double_value=round(product["price"] * quantity, 2))
    ev["items"] = [{
        "item_id":        product["item_id"],
        "item_name":      product["item_name"],
        "item_brand":     product["item_brand"],
        "item_category":  product["item_category"],
        "item_category2": product["item_category2"],
        "price":          product["price"],
        "price_in_usd":   round(product["price"] * USD_RATE, 2),
        "quantity":       quantity,
        "item_revenue":   None,
        "item_revenue_in_usd": None,
        "item_refund":    None,
        "item_refund_in_usd": None,
    }]
    return ev


def make_begin_checkout_event(user, session_id, session_number, event_dt,
                               page_path, page_referrer, traffic_src, device, geo,
                               prev_ts, cart_items):
    ev = base_event(user, session_id, session_number, "begin_checkout",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts)
    total = sum(p["price"] * q for p, q in cart_items)
    add_event_param(ev, "currency", string_value=CURRENCY)
    add_event_param(ev, "value",    double_value=round(total, 2))
    ev["items"] = [{
        "item_id":        p["item_id"],
        "item_name":      p["item_name"],
        "item_brand":     p["item_brand"],
        "item_category":  p["item_category"],
        "item_category2": p["item_category2"],
        "price":          p["price"],
        "price_in_usd":   round(p["price"] * USD_RATE, 2),
        "quantity":       q,
        "item_revenue":   None,
        "item_revenue_in_usd": None,
        "item_refund":    None,
        "item_refund_in_usd": None,
    } for p, q in cart_items]
    return ev


def make_purchase_event(user, session_id, session_number, event_dt,
                         page_path, page_referrer, traffic_src, device, geo,
                         prev_ts, cart_items):
    transaction_id = "T-" + uuid.uuid4().hex[:10].upper()
    revenue  = sum(p["price"] * q for p, q in cart_items)
    shipping = round(random.uniform(0, 15), 2) if revenue < 500 else 0.0
    tax      = round(revenue * 0.19, 2)  # German VAT
    total    = round(revenue + shipping, 2)

    ev = base_event(user, session_id, session_number, "purchase",
                    event_dt, page_path, page_referrer, traffic_src, device, geo,
                    prev_timestamp=prev_ts)
    ev["event_value_in_usd"] = round(total * USD_RATE, 2)

    add_event_param(ev, "transaction_id", string_value=transaction_id)
    add_event_param(ev, "currency",       string_value=CURRENCY)
    add_event_param(ev, "value",          double_value=round(total, 2))
    add_event_param(ev, "shipping",       double_value=shipping)
    add_event_param(ev, "tax",            double_value=tax)

    ev["ecommerce"] = {
        "transaction_id":           transaction_id,
        "purchase_revenue":         round(revenue, 2),
        "purchase_revenue_in_usd":  round(revenue * USD_RATE, 2),
        "shipping_value":           shipping,
        "shipping_value_in_usd":    round(shipping * USD_RATE, 2),
        "tax_value":                tax,
        "tax_value_in_usd":         round(tax * USD_RATE, 2),
        "refund_value":             None,
        "refund_value_in_usd":      None,
        "total_item_quantity":      sum(q for _, q in cart_items),
        "unique_items":             len(cart_items),
    }
    ev["items"] = [{
        "item_id":              p["item_id"],
        "item_name":            p["item_name"],
        "item_brand":           p["item_brand"],
        "item_category":        p["item_category"],
        "item_category2":       p["item_category2"],
        "price":                p["price"],
        "price_in_usd":         round(p["price"] * USD_RATE, 2),
        "quantity":             q,
        "item_revenue":         round(p["price"] * q, 2),
        "item_revenue_in_usd":  round(p["price"] * q * USD_RATE, 2),
        "item_refund":          None,
        "item_refund_in_usd":   None,
    } for p, q in cart_items]

    user["ltv_revenue"] = round(user["ltv_revenue"] + total, 2)
    return ev, transaction_id


# =============================================================================
# SESSION GENERATOR
# =============================================================================

def generate_session(user, date, anomalies_active):
    """Generate all events for a single session."""
    events = []
    global EXPERIMENT_STATS
    session_id     = generate_session_id()
    user["session_count"] += 1
    session_number = user["session_count"]

    traffic_src = pick_traffic_source()
    device      = user["preferred_device"]
    geo         = user["geo"]

    # Session start time — distributed across the day with peak hours
    hour_weights = [0.5,0.3,0.2,0.2,0.2,0.3,0.5,0.8,1.2,1.5,1.6,1.5,
                    1.4,1.5,1.5,1.6,1.7,1.8,1.9,1.7,1.5,1.2,0.9,0.7]
    hour = random.choices(range(24), weights=hour_weights, k=1)[0]
    minute  = random.randint(0, 59)
    second  = random.randint(0, 59)
    session_start_dt = date.replace(hour=hour, minute=minute, second=second)

    current_dt  = session_start_dt
    prev_ts     = None
    page_path   = random.choice(["/", "/collections/sofas", "/collections/chairs",
                                  "/collections/new-arrivals", "/collections/sale"])
    page_ref    = ""

    # ── Anomaly B: Cross-domain tracking failure ─────────────────────────────
    is_xdomain_victim = (
        anomalies_active.get("B") and
        random.random() < ANOMALY_B_AFFECTED_RATIO
    )
    if is_xdomain_victim:
        # Session arrives mid-funnel from the payment gateway
        page_path   = "/order-confirmation"
        page_ref    = f"https://{PAYMENT_GATEWAY_DOMAIN}/checkout"
        traffic_src = {"source": "(direct)", "medium": "(none)",
                       "campaign": "(direct)", "gclid": False}
        # No session_start, session opens straight on order-confirmation
        pv = make_page_view_event(user, session_id, session_number, current_dt,
                                   page_path, page_ref, traffic_src, device, geo,
                                   prev_ts=None, is_entrance=True, batch_page_id=1)
        # Mark: ignore_referrer is absent (the bug) — don't add it
        events.append(pv)
        return events  # short-circuit — these sessions have only 1 event

    # ── Anomaly E: Session timeout continuation ──────────────────────────────
    is_timeout_continuation = (
        anomalies_active.get("E") and
        user["session_count"] > 1 and
        random.random() < ANOMALY_E_AFFECTED_RATIO
    )

    # ── Anomaly C / normal session_start ─────────────────────────────────────
    if is_timeout_continuation:
        suppress_session_start = True
        traffic_src = {"source": None, "medium": None, "campaign": None, "gclid": False}
    else:
        suppress_session_start = (
            anomalies_active.get("C") and
            random.random() < ANOMALY_C_SUPPRESSION_RATE
        )
        if suppress_session_start:
            traffic_src = {"source": None, "medium": None, "campaign": None, "gclid": False}

    if not suppress_session_start:
        ss = make_session_start_event(user, session_id, session_number, current_dt,
                                    page_path, page_ref, traffic_src, device, geo)
        events.append(ss)

    prev_ts = to_micros(current_dt)
    current_dt += timedelta(seconds=random.randint(1, 3))

    # ── Anomaly D: Missing attribution ───────────────────────────────────────
    is_attr_victim = (
        anomalies_active.get("D") and
        random.random() < ANOMALY_D_AFFECTED_RATIO
    )
    if is_attr_victim:
        traffic_src = {"source": None, "medium": None, "campaign": None, "gclid": False}

    # ── First page_view (entrance) ───────────────────────────────────────────
    pv = make_page_view_event(user, session_id, session_number, current_dt,
                               page_path, page_ref, traffic_src, device, geo,
                               prev_ts=prev_ts, is_entrance=True, batch_page_id=1)

    # ── Anomaly A: PII in page_location ─────────────────────────────────────
    # Realistic leak: any page that could receive user data via URL (not just
    # account/checkout pages — the bug is in GTM dataLayer push, so it fires
    # on ANY page_view where the user object is available i.e. logged-in users)
    is_pii_victim = (
        anomalies_active.get("A") and
        random.random() < ANOMALY_A_AFFECTED_RATIO
    )
    if is_pii_victim:
        # Replace page_location param with PII-polluted URL
        for param in pv["event_params"]:
            if param["key"] == "page_location":
                param["value"]["string_value"] = pii_polluted_url(page_path)
        # PII also leaks into page_referrer of the next page — flag for next iter
        pii_referrer = pv["event_params"][0]["value"].get("string_value", "")
    else:
        pii_referrer = None

    events.append(pv)
    # ── Experiment: emit experience_impression on PDP entrance when applicable
    try:
        for exp_key, exp in EXPERIMENTS.items():
            # sample rate
            if random.random() > exp.get("sample_rate", 1.0):
                continue
            # check date window
            if not in_window(date, exp["start"], exp["end"]):
                continue
            # page prefix match (apply on entrance PDPs)
            if page_path and any(page_path.startswith(p) for p in exp.get("pages", [])):
                variant_index = assign_variant_for_user(user["user_pseudo_id"], exp["experience_id"], exp["n_variants"])
                exp_variant_string = generate_exp_variant_string(exp["tool_id"], exp["experience_id"], variant_index)
                # schedule impression shortly after the page_view timestamp
                imp_dt = current_dt + timedelta(milliseconds=50)
                imp = make_experience_impression_event(user, session_id, session_number, imp_dt,
                                                      page_path, page_ref, traffic_src, device, geo,
                                                      prev_ts, exp_variant_string,
                                                      batch_event_index=0, batch_page_id=1)
                events.append(imp)
                # advance prev_ts/current_dt so subsequent events are ordered
                prev_ts = to_micros(imp_dt)
                current_dt = imp_dt + timedelta(seconds=random.randint(1, 3))

                # record in EXPERIMENT_STATS
                date_key = date.strftime("%Y%m%d")
                EXPERIMENT_STATS.setdefault(exp_key, {})
                EXPERIMENT_STATS[exp_key].setdefault(date_key, {})
                EXPERIMENT_STATS[exp_key][date_key].setdefault(exp_variant_string, 0)
                EXPERIMENT_STATS[exp_key][date_key][exp_variant_string] += 1
    except Exception:
        # defensive: experiments must not break generation
        pass
    prev_ts = to_micros(current_dt)
    current_dt += timedelta(seconds=random.randint(5, 30))

    # ── Scroll on entrance page ──────────────────────────────────────────────
    if random.random() > 0.35:
        scroll = make_scroll_event(user, session_id, session_number, current_dt,
                                    page_path, page_ref, traffic_src, device, geo, prev_ts)
        events.append(scroll)
        prev_ts = to_micros(current_dt)
        current_dt += timedelta(seconds=random.randint(10, 60))

    # ── Browse 0–4 additional pages ──────────────────────────────────────────
    n_extra_pages = random.choices([0,1,2,3,4], weights=[0.15,0.30,0.30,0.15,0.10])[0]
    selected_product = None
    cart_items = []
    batch_page_id = 2

    for i in range(n_extra_pages):
        next_path = random.choice(PAGES)
        referrer  = pii_referrer if pii_referrer else build_page_url(page_path)
        pii_referrer = None  # only carry PII referrer for one hop

        pv2 = make_page_view_event(user, session_id, session_number, current_dt,
                                    next_path, referrer, traffic_src, device, geo,
                                    prev_ts=prev_ts, is_entrance=False,
                                    batch_event_index=i+1, batch_page_id=batch_page_id)
        events.append(pv2)
        # ── Experiment: emit experience_impression on PDP page views as well
        try:
            for exp_key, exp in EXPERIMENTS.items():
                if random.random() > exp.get("sample_rate", 1.0):
                    continue
                if not in_window(date, exp["start"], exp["end"]):
                    continue
                if next_path and any(next_path.startswith(p) for p in exp.get("pages", [])):
                    variant_index = assign_variant_for_user(user["user_pseudo_id"], exp["experience_id"], exp["n_variants"])
                    exp_variant_string = generate_exp_variant_string(exp["tool_id"], exp["experience_id"], variant_index)
                    imp_dt = current_dt + timedelta(milliseconds=50)
                    imp = make_experience_impression_event(user, session_id, session_number, imp_dt,
                                                          next_path, referrer, traffic_src, device, geo,
                                                          prev_ts, exp_variant_string,
                                                          batch_event_index=i+1, batch_page_id=batch_page_id)
                    events.append(imp)
                    # record in EXPERIMENT_STATS
                    date_key = date.strftime("%Y%m%d")
                    EXPERIMENT_STATS.setdefault(exp_key, {})
                    EXPERIMENT_STATS[exp_key].setdefault(date_key, {})
                    EXPERIMENT_STATS[exp_key][date_key].setdefault(exp_variant_string, 0)
                    EXPERIMENT_STATS[exp_key][date_key][exp_variant_string] += 1
        except Exception:
            pass
        prev_ts = to_micros(current_dt)
        current_dt += timedelta(seconds=random.randint(10, 90))
        batch_page_id += 1

        # View item on product pages
        if next_path.startswith("/products/") and random.random() < VIEW_ITEM_RATE:
            product = random.choice(PRODUCTS)
            selected_product = product
            vi = make_view_item_event(user, session_id, session_number, current_dt,
                                       next_path, build_page_url(page_path),
                                       traffic_src, device, geo, prev_ts, product)
            events.append(vi)
            prev_ts = to_micros(current_dt)
            current_dt += timedelta(seconds=random.randint(15, 120))

        page_path = next_path

    # ── Add to cart ──────────────────────────────────────────────────────────
    if selected_product and random.random() < ADD_TO_CART_RATE:
        quantity = random.choices([1, 2], weights=[0.85, 0.15])[0]
        cart_items = [(selected_product, quantity)]
        atc = make_add_to_cart_event(user, session_id, session_number, current_dt,
                                      "/cart", build_page_url(page_path),
                                      traffic_src, device, geo, prev_ts,
                                      selected_product, quantity)
        events.append(atc)
        prev_ts = to_micros(current_dt)
        current_dt += timedelta(seconds=random.randint(10, 60))

        # ── Begin checkout ───────────────────────────────────────────────────
        if cart_items and random.random() < (BEGIN_CHECKOUT_RATE / ADD_TO_CART_RATE):
            bc = make_begin_checkout_event(user, session_id, session_number, current_dt,
                                            "/checkout", build_page_url("/cart"),
                                            traffic_src, device, geo, prev_ts, cart_items)
            events.append(bc)
            prev_ts = to_micros(current_dt)
            current_dt += timedelta(seconds=random.randint(30, 180))

            # ── Purchase ─────────────────────────────────────────────────────
            if random.random() < (PURCHASE_RATE / BEGIN_CHECKOUT_RATE):
                purch, txn_id = make_purchase_event(
                    user, session_id, session_number, current_dt,
                    "/order-confirmation", build_page_url("/checkout/payment"),
                    traffic_src, device, geo, prev_ts, cart_items)
                events.append(purch)

    return events


# =============================================================================
# MAIN GENERATION LOOP
# =============================================================================

def generate_all_events():
    all_events = []
    anomaly_stats = {
        "A": {"count": 0, "sessions": 0},
        "B": {"count": 0, "sessions": 0},
        "C": {"count": 0, "sessions": 0},
        "D": {"count": 0, "sessions": 0},
        "E": {"count": 0, "sessions": 0},
    }

    # initialize experiment stats counters
    global EXPERIMENT_STATS
    EXPERIMENT_STATS = {k: {} for k in EXPERIMENTS.keys()}

    current_date = START_DATE
    total_days   = (END_DATE - START_DATE).days + 1
    day_num = 0

    user_pool = build_user_pool(USER_POOL_SIZE)

    while current_date <= END_DATE:
        day_num += 1
        if day_num % 10 == 0 or day_num == 1:
            print(f"  Processing day {day_num}/{total_days}: {current_date.strftime('%Y-%m-%d')}")

        anomalies_active = {
            "A": in_window(current_date, ANOMALY_A_PII_START, ANOMALY_A_PII_END),
            "B": in_window(current_date, ANOMALY_B_XDOMAIN_START, ANOMALY_B_XDOMAIN_END),
            "C": in_window(current_date, ANOMALY_C_NO_SESSION_START_START, ANOMALY_C_NO_SESSION_START_END),
            "D": in_window(current_date, ANOMALY_D_NO_ATTR_START, ANOMALY_D_NO_ATTR_END),
            "E": in_window(current_date, ANOMALY_E_TIMEOUT_START, ANOMALY_E_TIMEOUT_END),
        }

        n_sessions = sessions_for_day(current_date)

        for _ in range(n_sessions):
            is_returning = random.random() < RETURNING_USER_RATIO
            if is_returning:
                user = random.choice(user_pool[:USER_POOL_SIZE // 2])
            else:
                user = random.choice(user_pool)

            session_events = generate_session(user, current_date, anomalies_active)
            all_events.extend(session_events)

            # Track anomaly stats
            if anomalies_active["A"]:
                for ev in session_events:
                    for param in ev.get("event_params", []):
                        if param["key"] == "page_location":
                            url = param["value"].get("string_value", "")
                            if any(p in url for p in PII_EMAIL_PARAMS + PII_PHONE_PARAMS + PII_NAME_PARAMS):
                                anomaly_stats["A"]["sessions"] += 1
                                anomaly_stats["A"]["count"] += 1
                                break

            if anomalies_active["B"]:
                for ev in session_events:
                    for param in ev.get("event_params", []):
                        if param["key"] == "page_referrer":
                            if PAYMENT_GATEWAY_DOMAIN in param["value"].get("string_value", ""):
                                anomaly_stats["B"]["sessions"] += 1
                                anomaly_stats["B"]["count"] += len(session_events)
                                break

            if anomalies_active["C"]:
                has_session_start = any(e["event_name"] == "session_start" for e in session_events)
                has_page_view     = any(e["event_name"] == "page_view"     for e in session_events)
                if has_page_view and not has_session_start:
                    anomaly_stats["C"]["sessions"] += 1
                    anomaly_stats["C"]["count"] += len(session_events)

            if anomalies_active["D"]:
                for ev in session_events:
                    if ev.get("collected_traffic_source") is None and ev.get("session_traffic_source_last_click") is None:
                        anomaly_stats["D"]["sessions"] += 1
                        anomaly_stats["D"]["count"] += len(session_events)
                        break
            
            #print(f"session_count distribution: {sorted(set(u['session_count'] for u in user_pool))}")

            if anomalies_active["E"]:
                has_session_start = any(e["event_name"] == "session_start" for e in session_events)
                has_page_view     = any(e["event_name"] == "page_view"     for e in session_events)
                no_attribution    = all(
                    ev.get("collected_traffic_source") is None and
                    ev.get("session_traffic_source_last_click") is None
                    for ev in session_events
                )
                # E = no session_start + no attribution + user had a prior session
                # session_count was already incremented inside generate_session,
                # so > 1 means this is at least the user's second session
                if has_page_view and not has_session_start and no_attribution and user["session_count"] > 1:
                    anomaly_stats["E"]["sessions"] += 1
                    anomaly_stats["E"]["count"] += len(session_events)

        current_date += timedelta(days=1)

    return all_events, anomaly_stats

# =============================================================================
# SCHEMA DEFINITION
# =============================================================================

def build_bq_schema():
    """Return the BigQuery JSON schema matching our NDJSON output."""
    return [
        {"name": "event_date",                    "type": "STRING",  "mode": "NULLABLE"},
        {"name": "event_timestamp",               "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "event_previous_timestamp",      "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "event_name",                    "type": "STRING",  "mode": "NULLABLE"},
        {"name": "event_value_in_usd",            "type": "FLOAT",   "mode": "NULLABLE"},
        {"name": "event_bundle_sequence_id",      "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "event_server_timestamp_offset", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "batch_event_index",             "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "batch_ordering_id",             "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "batch_page_id",                 "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "event_params", "type": "RECORD", "mode": "REPEATED", "fields": [
            {"name": "key",   "type": "STRING", "mode": "NULLABLE"},
            {"name": "value", "type": "RECORD", "mode": "NULLABLE", "fields": [
                {"name": "string_value", "type": "STRING",  "mode": "NULLABLE"},
                {"name": "int_value",    "type": "INTEGER", "mode": "NULLABLE"},
                {"name": "double_value", "type": "FLOAT",   "mode": "NULLABLE"},
                {"name": "float_value",  "type": "FLOAT",   "mode": "NULLABLE"},
            ]},
        ]},
        {"name": "user_pseudo_id",            "type": "STRING",  "mode": "NULLABLE"},
        {"name": "user_id",                   "type": "STRING",  "mode": "NULLABLE"},
        {"name": "user_first_touch_timestamp","type": "INTEGER", "mode": "NULLABLE"},
        {"name": "is_active_user",            "type": "BOOLEAN", "mode": "NULLABLE"},
        {"name": "privacy_info", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "ads_storage",          "type": "STRING", "mode": "NULLABLE"},
            {"name": "analytics_storage",    "type": "STRING", "mode": "NULLABLE"},
            {"name": "uses_transient_token", "type": "STRING", "mode": "NULLABLE"},
        ]},
        {"name": "user_properties", "type": "RECORD", "mode": "REPEATED", "fields": [
            {"name": "key",   "type": "STRING", "mode": "NULLABLE"},
            {"name": "value", "type": "RECORD", "mode": "NULLABLE", "fields": [
                {"name": "string_value",          "type": "STRING",  "mode": "NULLABLE"},
                {"name": "int_value",             "type": "INTEGER", "mode": "NULLABLE"},
                {"name": "double_value",          "type": "FLOAT",   "mode": "NULLABLE"},
                {"name": "float_value",           "type": "FLOAT",   "mode": "NULLABLE"},
                {"name": "set_timestamp_micros",  "type": "INTEGER", "mode": "NULLABLE"},
            ]},
        ]},
        {"name": "user_ltv", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "revenue",  "type": "FLOAT",  "mode": "NULLABLE"},
            {"name": "currency", "type": "STRING", "mode": "NULLABLE"},
        ]},
        {"name": "traffic_source", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "name",   "type": "STRING", "mode": "NULLABLE"},
            {"name": "medium", "type": "STRING", "mode": "NULLABLE"},
            {"name": "source", "type": "STRING", "mode": "NULLABLE"},
        ]},
        {"name": "collected_traffic_source", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "manual_campaign_id",     "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_campaign_name",   "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_source",          "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_medium",          "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_term",            "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_content",         "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_creative_format", "type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_marketing_tactic","type": "STRING", "mode": "NULLABLE"},
            {"name": "manual_source_platform", "type": "STRING", "mode": "NULLABLE"},
            {"name": "gclid",                  "type": "STRING", "mode": "NULLABLE"},
            {"name": "dclid",                  "type": "STRING", "mode": "NULLABLE"},
            {"name": "srsltid",                "type": "STRING", "mode": "NULLABLE"},
        ]},
        {"name": "session_traffic_source_last_click", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "manual_campaign", "type": "RECORD", "mode": "NULLABLE", "fields": [
                {"name": "campaign_id",      "type": "STRING", "mode": "NULLABLE"},
                {"name": "campaign_name",    "type": "STRING", "mode": "NULLABLE"},
                {"name": "medium",           "type": "STRING", "mode": "NULLABLE"},
                {"name": "term",             "type": "STRING", "mode": "NULLABLE"},
                {"name": "content",          "type": "STRING", "mode": "NULLABLE"},
                {"name": "source_platform",  "type": "STRING", "mode": "NULLABLE"},
                {"name": "source",           "type": "STRING", "mode": "NULLABLE"},
                {"name": "creative_format",  "type": "STRING", "mode": "NULLABLE"},
            ]},
        ]},
        {"name": "device", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "category",                 "type": "STRING",  "mode": "NULLABLE"},
            {"name": "mobile_brand_name",        "type": "STRING",  "mode": "NULLABLE"},
            {"name": "mobile_model_name",        "type": "STRING",  "mode": "NULLABLE"},
            {"name": "mobile_marketing_name",    "type": "STRING",  "mode": "NULLABLE"},
            {"name": "operating_system",         "type": "STRING",  "mode": "NULLABLE"},
            {"name": "operating_system_version", "type": "STRING",  "mode": "NULLABLE"},
            {"name": "language",                 "type": "STRING",  "mode": "NULLABLE"},
            {"name": "time_zone_offset_seconds", "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "is_limited_ad_tracking",   "type": "BOOLEAN", "mode": "NULLABLE"},
            {"name": "web_info", "type": "RECORD", "mode": "NULLABLE", "fields": [
                {"name": "browser",         "type": "STRING", "mode": "NULLABLE"},
                {"name": "browser_version", "type": "STRING", "mode": "NULLABLE"},
                {"name": "hostname",        "type": "STRING", "mode": "NULLABLE"},
            ]},
        ]},
        {"name": "geo", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "continent",     "type": "STRING", "mode": "NULLABLE"},
            {"name": "sub_continent", "type": "STRING", "mode": "NULLABLE"},
            {"name": "country",       "type": "STRING", "mode": "NULLABLE"},
            {"name": "region",        "type": "STRING", "mode": "NULLABLE"},
            {"name": "metro",         "type": "STRING", "mode": "NULLABLE"},
            {"name": "city",          "type": "STRING", "mode": "NULLABLE"},
        ]},
        {"name": "ecommerce", "type": "RECORD", "mode": "NULLABLE", "fields": [
            {"name": "transaction_id",           "type": "STRING",  "mode": "NULLABLE"},
            {"name": "purchase_revenue",         "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "purchase_revenue_in_usd",  "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "shipping_value",           "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "shipping_value_in_usd",    "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "tax_value",                "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "tax_value_in_usd",         "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "refund_value",             "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "refund_value_in_usd",      "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "total_item_quantity",      "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "unique_items",             "type": "INTEGER", "mode": "NULLABLE"},
        ]},
        {"name": "items", "type": "RECORD", "mode": "REPEATED", "fields": [
            {"name": "item_id",             "type": "STRING",  "mode": "NULLABLE"},
            {"name": "item_name",           "type": "STRING",  "mode": "NULLABLE"},
            {"name": "item_brand",          "type": "STRING",  "mode": "NULLABLE"},
            {"name": "item_category",       "type": "STRING",  "mode": "NULLABLE"},
            {"name": "item_category2",      "type": "STRING",  "mode": "NULLABLE"},
            {"name": "price",               "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "price_in_usd",        "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "quantity",            "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "item_revenue",        "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "item_revenue_in_usd", "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "item_refund",         "type": "FLOAT",   "mode": "NULLABLE"},
            {"name": "item_refund_in_usd",  "type": "FLOAT",   "mode": "NULLABLE"},
        ]},
        {"name": "stream_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "platform",  "type": "STRING", "mode": "NULLABLE"},
    ]


# =============================================================================
# WRITE OUTPUTS
# =============================================================================

def write_outputs(events, anomaly_stats):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Group events by date and write daily JSONL files ─────────────────────
    events_by_date = {}
    for ev in events:
        date_key = ev["event_date"]  # Format: "YYYYMMDD"
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(ev)

    print(f"\nWriting {len(events):,} events across {len(events_by_date)} days...")
    jsonl_paths = []
    for date_key in sorted(events_by_date.keys()):
        daily_events = events_by_date[date_key]
        jsonl_path = f"{OUTPUT_DIR}/events_{date_key}.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for ev in daily_events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        jsonl_paths.append(jsonl_path)
        print(f"  {date_key}: {len(daily_events):,} events → events_{date_key}.jsonl")
    print("  Done.")

    # ── ga4_schema.json ───────────────────────────────────────────────────────
    schema_path = f"{OUTPUT_DIR}/ga4_schema.json"
    print(f"Writing schema to {schema_path} ...")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(build_bq_schema(), f, indent=2)
    print("  Done.")

    # ── anomaly_manifest.csv ──────────────────────────────────────────────────
    manifest_path = f"{OUTPUT_DIR}/anomaly_manifest.csv"
    print(f"Writing anomaly manifest to {manifest_path} ...")
    rows = [
        {
            "anomaly_id":   "A",
            "anomaly_type": "PII Leakage in page_location",
            "start_date":   ANOMALY_A_PII_START.strftime("%Y-%m-%d"),
            "end_date":     ANOMALY_A_PII_END.strftime("%Y-%m-%d"),
            "affected_events": anomaly_stats["A"]["count"],
            "affected_sessions": anomaly_stats["A"]["sessions"],
            "affected_field":   "event_params[key=page_location].value.string_value, event_params[key=page_referrer].value.string_value",
            "root_cause":       "Developer accidentally passed user object fields (email, phone, name) into the dataLayer page_path variable via GTM. PII appears as raw query parameters in page_location URLs and propagates to the next page's page_referrer.",
            "detection_hint":   "Query event_params for page_location values containing '@', '+49', or URL-encoded names. Check sessions on /checkout and /account pages during the window.",
        },
        {
            "anomaly_id":   "B",
            "anomaly_type": "Cross-Domain Tracking Failure (Payment Gateway)",
            "start_date":   ANOMALY_B_XDOMAIN_START.strftime("%Y-%m-%d"),
            "end_date":     ANOMALY_B_XDOMAIN_END.strftime("%Y-%m-%d"),
            "affected_events": anomaly_stats["B"]["count"],
            "affected_sessions": anomaly_stats["B"]["sessions"],
            "affected_field":   "session_traffic_source_last_click, collected_traffic_source, event_params[key=page_referrer]",
            "root_cause":       "GA4 linker parameter not configured for pay.stripe.com. Users returning from the payment gateway are assigned a new session attributed as (direct)/(none) instead of inheriting the original session. Sessions start mid-funnel on /order-confirmation with no prior page_views.",
            "detection_hint":   "Find sessions where first event is page_view on /order-confirmation AND page_referrer contains pay.stripe.com AND session_traffic_source_last_click IS NULL. Count = inflated direct sessions, suppressed conversion attribution.",
        },
        {
            "anomaly_id":   "C",
            "anomaly_type": "Missing session_start Events (Bad GTM Deploy)",
            "start_date":   ANOMALY_C_NO_SESSION_START_START.strftime("%Y-%m-%d"),
            "end_date":     ANOMALY_C_NO_SESSION_START_END.strftime("%Y-%m-%d"),
            "affected_events": anomaly_stats["C"]["count"],
            "affected_sessions": anomaly_stats["C"]["sessions"],
            "affected_field":   "event_name = session_start",
            "root_cause":       "A misconfigured GTM trigger condition excluded the session_start event from firing during a 7-day deploy window. page_view and all downstream events still fire normally. Pipelines that COUNT(session_start) to derive session metrics will show a ~100% session drop during this window.",
            "detection_hint":   "Compare COUNT(event_name = 'session_start') vs COUNT(DISTINCT ga_session_id) by date. During the window, the ratio drops to 0. Cross-check: page_view events still have entrances=1 in event_params, confirming real sessions existed.",
        },
        {
            "anomaly_id":   "D",
            "anomaly_type": "Missing Attribution → (not set)",
            "start_date":   ANOMALY_D_NO_ATTR_START.strftime("%Y-%m-%d"),
            "end_date":     ANOMALY_D_NO_ATTR_END.strftime("%Y-%m-%d"),
            "affected_events": anomaly_stats["D"]["count"],
            "affected_sessions": anomaly_stats["D"]["sessions"],
            "affected_field":   "collected_traffic_source, session_traffic_source_last_click",
            "root_cause":       "Consent Management Platform (CMP) blocking analytics_storage before user consent interaction. ~25% of sessions have no UTM data captured at event time and no last-click attribution. Revenue and conversions from these sessions appear under (not set) source/medium. Note: traffic_source (user first-touch) is unaffected for returning users.",
            "detection_hint":   "Filter WHERE collected_traffic_source IS NULL AND session_traffic_source_last_click IS NULL. Check privacy_info.analytics_storage = 'No' co-occurrence. Compare purchase revenue from (not set) sessions during window vs baseline to size the revenue attribution gap.",
        },
        {
            "anomaly_id": "E",
            "anomaly_type": "Session Timeout Continuation (Ghost Sessions)",
            "start_date": "2025-12-19",
            "end_date":   "2025-12-29",
            "affected_events": "...",
            "affected_sessions": "...",
            "affected_field": "event_name = session_start, collected_traffic_source, session_traffic_source_last_click",
            "root_cause": "GA4 session timeout (30 min default) causes a new session to open mid-browse with no session_start and no UTM capture. The user was already active in a prior session. Common when users leave a tab open and return later.",
            "detection_hint": "Find sessions where has_session_start = 0 AND source IS NULL AND prev_session_last_event_ts IS NOT NULL. Gap from previous session is typically 30–120 minutes.",
        }
    ]

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print("  Done.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("="*65)
    print("Generation Summary")
    print("="*65)
    print(f"  Total events written : {len(events):>10,}")
    print(f"  Date range           : {START_DATE.strftime('%Y-%m-%d')} → {END_DATE.strftime('%Y-%m-%d')}")
    print(f"  Days covered         : {(END_DATE - START_DATE).days + 1}")
    print()
    print("  Anomaly injection:")
    labels = {
        "A": "PII leakage",
        "B": "Cross-domain failure",
        "C": "Missing session_start",
        "D": "Missing attribution",
        "E": "Session Timeout Continuation"
    }
    for k, v in anomaly_stats.items():
        print(f"    [{k}] {labels[k]:<25} {v['sessions']:>6,} sessions  |  {v['count']:>7,} events")
    print("="*65)

    # ── Experiment impressions summary
    if EXPERIMENT_STATS:
        print("\nExperiment impressions:")
        for exp_key, dates in EXPERIMENT_STATS.items():
            print(f"  {exp_key}:")
            total_exp = 0
            for date_key in sorted(dates.keys()):
                parts = []
                for variant, cnt in sorted(dates[date_key].items()):
                    parts.append(f"{variant}={cnt}")
                    total_exp += cnt
                print(f"    {date_key}: {' '.join(parts)}")
            print(f"    Total impressions: {total_exp}")

    return jsonl_paths


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("GA4 Sample Data Generator")
    print(f"Generating {(END_DATE - START_DATE).days + 1} days of data "
          f"({START_DATE.strftime('%Y-%m-%d')} → {END_DATE.strftime('%Y-%m-%d')})\n")

    print("Generating events...")
    events, anomaly_stats = generate_all_events()

    jsonl_paths = write_outputs(events, anomaly_stats)
    print(f"\nGenerated {len(jsonl_paths)} daily JSONL files in {OUTPUT_DIR}/")
