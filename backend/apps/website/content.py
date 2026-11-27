"""The platform website's texts: built-in defaults, what the owner changed, and the rules an edit must follow.

Text may mark words as bold by putting two asterisks around them (`**like this**`). The website shows them in bold; search engine
descriptions and other plain-text places use `plain()`.
"""
import copy
import re

from rest_framework.exceptions import ValidationError

from .legal_defaults import LEGAL_DEFAULTS

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def plain(text):
    """The same text without the bold markers."""
    return _BOLD.sub(r"\1", text or "").replace("**", "")


def _t(title, text):
    return {"title": title, "text": text}


def _q(q, a):
    return {"q": q, "a": a}


DEFAULTS = {
    "footer": {
        "about": "Run every restaurant, branch and till from one secure platform: orders, payments, kitchen, stock, staff and reports.",
        "cta_title": "Bring your restaurant online",
        "cta_text": "Tell us about your restaurant and we will set it up with you.",
        "cta_button": "Contact us",
    },
    "home": {
        "pill": "For restaurants and restaurant groups",
        "title": "Run every branch, till and order",
        "title_highlight": "from one place.",
        "lead": "Give each restaurant its own branded website with online ordering and mobile money, plus a point of sale, kitchen display, staff and payroll tools and clear financial reports.",
        "primary_button": "Talk to us",
        "secondary_button": "See features",
        "perks": [{"text": "Online ordering"}, {"text": "Cash and mobile money"}, {"text": "Secure by design"}],
        "features_eyebrow": "Capabilities",
        "features_title": "Everything a restaurant needs to operate",
        "features_text": "One system for the website, the counter, the kitchen and the office.",
        "steps_eyebrow": "Getting started",
        "steps_title": "From registration to your first order",
        "steps": [
            _t("Register", "The platform team registers your restaurant and emails the administrator a secure one-time link."),
            _t("Set up", "Add branches, staff, your menu, prices and your own logo and colours."),
            _t("Sell", "Take orders online, at the counter and from QR codes on your tables."),
            _t("Grow", "Follow sales, stock, payroll and expenses for every branch."),
        ],
        "security_title": "Built for security from the start",
        "security_text": "Permissions are enforced on the server, each restaurant’s records are isolated, and every sensitive action leaves an audit trail.",
        "pricing_title": "Pricing",
        "cta_title": "Ready to bring your restaurant online?",
        "cta_text": "Tell us about your restaurant and we will set it up with you.",
    },
    "features": {
        "eyebrow": "Features",
        "title": "One platform for the whole restaurant",
        "lead": "From the first online order to the month-end payroll.",
        "items": [
            _t("Online ordering", "A branded website for every restaurant with menu, cart and checkout."),
            _t("Multi-branch management", "Run many branches with isolated records and branch-level managers."),
            _t("Payments", "Cash, mobile money and online payments with receipts and reconciliation."),
            _t("Staff management", "Invite staff securely and give each role only the access it needs."),
            _t("QR table ordering", "Diners scan a table code; cashiers review and confirm requests."),
            _t("Salary and payroll", "Salary structures, payroll runs and receipts with approval controls."),
            _t("Financial reporting", "Sales, refunds and payment breakdowns per branch and restaurant."),
            _t("Tenant isolation", "Each restaurant’s data is separated and enforced on the server."),
        ],
    },
    "pricing": {
        "eyebrow": "Plans",
        "title": "Pricing that fits your restaurant",
        "lead": "Choose a plan, or tell us what you need.",
        "note": "Need something different? Contact us and we will help you choose.",
    },
    "about": {
        "eyebrow": "Who we are",
        "title": "About us",
        "lead": "We build software that helps restaurants take orders, accept payments and manage their teams without juggling separate tools.",
        "sections": [
            _t("What we do", "We give every restaurant its own website with online ordering, and the tools to run the counter, the kitchen and the office behind it."),
            _t("How we work with restaurants", "The platform team registers your restaurant, and your administrator sets up branches, staff, menu and branding."),
            _t("What we care about", "Clear records, honest numbers and access limited to what each person’s job needs."),
        ],
    },
    "faq": {
        "eyebrow": "Help",
        "title": "Frequently asked questions",
        "lead": "Quick answers about getting started, payments and your data.",
        "items": [
            _q("How do restaurants get started?", "The platform team registers your restaurant. Your administrator receives an email with a secure one-time link to set a password."),
            _q("Does every restaurant get its own website?", "Yes. Each restaurant has its own address, branding, menu and customer accounts."),
            _q("Which payment methods are supported?", "Cash, mobile money and online payments. Provider availability depends on your plan and configuration."),
            _q("Can one restaurant have several branches?", "Yes. Branch managers only see the branch they are assigned to."),
            _q("How is my data protected?", "Access is checked on the server for every request, passwords are hashed, sign-in attempts are rate limited, and sensitive actions are audit logged."),
        ],
    },
    "contact": {
        "eyebrow": "Contact",
        "title": "Talk to us",
        "lead": "Send us a message and our team will get back to you.",
        "form_title": "Send us a message",
        "phone": "",
        "hours": "",
        "locations": [],
    },
    "legal": copy.deepcopy(LEGAL_DEFAULTS),
    "seo": {
        "home": _t("Restaurant management and online ordering platform", "Websites, online ordering, mobile money, point of sale, kitchen display, staff, payroll and reporting for restaurants, in one platform."),
        "features": _t("Features", "Online ordering, multi-branch management, payments, QR table ordering, payroll and financial reports for restaurants."),
        "pricing": _t("Pricing", "Plans for restaurants and restaurant groups."),
        "about": _t("About", "About the restaurant management and online ordering platform."),
        "faq": _t("Frequently asked questions", "Answers about getting started, restaurant websites, payments, branches and data protection."),
        "contact": _t("Contact us", "Talk to us about bringing your restaurant online."),
    },
}

# the fields of one entry in each list (needed because a list may start empty); the first field is required
ROWS = {
    ("home", "perks"): {"text": 80},
    ("home", "steps"): {"title": 80, "text": 500},
    ("features", "items"): {"title": 80, "text": 500},
    ("faq", "items"): {"q": 200, "a": 2000},
    ("about", "sections"): {"title": 120, "text": 4000},
    ("contact", "locations"): {"name": 120, "address": 255, "latitude": 20, "longitude": 20, "phone": 30, "hours": 200},
}
LEGAL_ROW = {"title": 150, "text": 6000}
LONG = {"lead": 600, "about": 600, "security_text": 800, "features_text": 400, "cta_text": 400, "note": 400, "hours": 300}
MAX_LIST = 30


def _bad(path, message):
    raise ValidationError({path: message})


def _text(path, value, limit):
    if not isinstance(value, str):
        _bad(path, "This must be text.")
    value = value.replace("\r\n", "\n").strip()
    if len(value) > limit:
        _bad(path, f"Keep this under {limit} characters.")
    return value


def _rows(path, value, shape):
    if not isinstance(value, list) or len(value) > MAX_LIST:
        _bad(path, f"Send a list of at most {MAX_LIST} entries.")
    rows = []
    for n, row in enumerate(value, 1):
        if not isinstance(row, dict) or set(row) - set(shape):
            _bad(path, f"Entry {n} has unknown fields.")
        clean = {k: _text(path, row.get(k, ""), limit) for k, limit in shape.items()}
        first = next(iter(shape))
        if not clean[first]:
            _bad(path, f"Entry {n} needs a {first}.")
        if "latitude" in clean:
            _coordinates(path, clean)
        rows.append(clean)
    return rows


def _coordinates(path, row):
    lat, lng = row["latitude"], row["longitude"]
    if not lat and not lng:
        return
    try:
        ok = -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180
    except ValueError:
        ok = False
    if not ok:
        _bad(path, "Give both a latitude (-90 to 90) and a longitude (-180 to 180), or neither.")


def clean_section(section, value):
    """Validate one section sent by the editor and return it ready to store."""
    if section not in DEFAULTS:
        _bad(section, "Unknown section.")
    if not isinstance(value, dict) or set(value) - set(DEFAULTS[section]):
        _bad(section, "Unknown fields in this section.")
    out = {}
    for key, item in value.items():
        path = f"{section}.{key}"
        if section == "legal":
            out[key] = _rows(path, item, LEGAL_ROW)
        elif section == "seo":
            if not isinstance(item, dict) or set(item) - {"title", "text"}:
                _bad(path, "Unknown fields.")
            out[key] = {"title": plain(_text(path, item.get("title", ""), 70)), "text": plain(_text(path, item.get("text", ""), 200))}
        elif (section, key) in ROWS:
            out[key] = _rows(path, item, ROWS[(section, key)])
        else:
            out[key] = _text(path, item, LONG.get(key, 200))
    return out


def merged(stored):
    """Defaults with the owner's changes on top."""
    out = copy.deepcopy(DEFAULTS)
    for section, values in (stored or {}).items():
        if section not in out or not isinstance(values, dict):
            continue
        for key, item in values.items():
            if key in out[section]:
                out[section][key] = item
    return out


def only_changes(section, values):
    """What differs from the built-in texts. An emptied legal page falls back to the draft template."""
    return {k: v for k, v in values.items() if v != DEFAULTS[section][k] and not (section == "legal" and not v)}
