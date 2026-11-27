"""Search and social metadata for each page, written into the HTML the server sends.

The website is a React app, so without this every URL would reach crawlers and link previews as the same empty page. For public pages
the server adds a real title, description, canonical URL, Open Graph / Twitter tags, structured data (JSON-LD) and a short text
version for visitors without JavaScript. Signed-in and transactional pages are marked noindex. All values are escaped.
"""
import json
from html import escape

from django.conf import settings

from apps.website.content import merged, plain

PLATFORM_NAME = "NTS Restaurant Platform"
PLATFORM_PAGES = {
    "": ("Restaurant management and online ordering platform", "Websites, online ordering, mobile money, point of sale, kitchen display, staff, payroll and reporting for restaurants, in one platform."),
    "features": ("Features", "Online ordering, multi-branch management, payments, QR table ordering, payroll and financial reports for restaurants."),
    "pricing": ("Pricing", "Plans for restaurants and restaurant groups."),
    "about": ("About", "About the restaurant management and online ordering platform."),
    "faq": ("Frequently asked questions", "Answers about getting started, restaurant websites, payments, branches and data protection."),
    "contact": ("Contact us", "Talk to us about bringing your restaurant online."),
}
TENANT_PAGES = {
    "": None,  # the restaurant's own title and description
    "menu": ("Menu", "See the menu of {name} and order online."),
    "services": ("Services", "Services offered by {name}."),
    "gallery": ("Gallery", "Photos from {name}."),
    "about": ("About us", "About {name}."),
    "contact": ("Contact and locations", "Find {name}: addresses, opening hours and contacts."),
    "faq": ("Frequently asked questions", "Answers to common questions about ordering from {name}."),
    "catering": ("Catering and events", "Ask {name} to cater your event."),
    "reserve": ("Reserve a table", "Book a table at {name} online."),
}


def _origin():
    return f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}"


def _absolute(url):
    if not url:
        return ""
    return url if url.startswith("http") else _origin() + url


def _platform_pages():
    """Titles and descriptions as the platform owner wrote them in Website content (the built-in ones otherwise)."""
    from apps.website.models import PlatformContent

    row = PlatformContent.objects.filter(pk=1).first()
    seo = merged(row.data if row else {})["seo"]
    pages = {}
    for key, entry in seo.items():
        path = "" if key == "home" else key
        pages[path] = (entry["title"] or PLATFORM_PAGES[path][0], entry["text"] or PLATFORM_PAGES[path][1])
    return pages


def _platform(path):
    if path in PLATFORM_PAGES:
        title, desc = _platform_pages()[path]
    elif path.startswith("legal/"):
        title = path.split("/", 1)[1].replace("-", " ").capitalize()
        desc = f"{title} of the {PLATFORM_NAME}."
    else:
        return None
    url = _origin() + (f"/{path}" if path else "/")
    data = None
    if not path:
        data = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": PLATFORM_NAME, "url": url, "logo": _origin() + "/logo-512.png"},
            {"@type": "WebSite", "name": PLATFORM_NAME, "url": url},
            {"@type": "SoftwareApplication", "name": PLATFORM_NAME, "applicationCategory": "BusinessApplication", "operatingSystem": "Web", "description": desc}]}
    links = [("/features", "Features"), ("/pricing", "Pricing"), ("/about", "About"), ("/faq", "FAQ"), ("/contact", "Contact")]
    return {"title": f"{title} | {PLATFORM_NAME}", "description": desc, "url": url, "image": _origin() + "/logo-512.png",
            "site": PLATFORM_NAME, "data": data, "heading": title, "links": links, "lines": [desc]}


def _tenant(restaurant, path):
    st = restaurant.get_settings()
    base = restaurant.public_url
    name = restaurant.name
    try:
        logo = _absolute(restaurant.logo.url) if restaurant.logo else ""
    except Exception:  # noqa: BLE001 - a storage hiccup must never break the page
        logo = ""
    where = ", ".join(x for x in (restaurant.city, restaurant.country) if x)
    lines, data, image = [], None, logo or _origin() + "/logo-512.png"
    if path == "":
        title = st.seo_title or (f"{name} | {where}" if where else name)
        desc = plain(st.seo_description or restaurant.description) or f"Order online from {name}: see the menu, order for pickup or delivery and reserve a table."
        data = {"@context": "https://schema.org", "@type": "Restaurant", "name": name, "url": base, "image": image, "description": desc,
                "hasMenu": f"{base}/menu", "acceptsReservations": True}
        if restaurant.latitude is not None and restaurant.longitude is not None:
            data["geo"] = {"@type": "GeoCoordinates", "latitude": float(restaurant.latitude), "longitude": float(restaurant.longitude)}
        if restaurant.contact_phone:
            data["telephone"] = restaurant.contact_phone
        if restaurant.address or restaurant.city:
            data["address"] = {"@type": "PostalAddress", "streetAddress": restaurant.address, "addressLocality": restaurant.city, "addressCountry": restaurant.country}
    elif path in TENANT_PAGES:
        label, template = TENANT_PAGES[path]
        title, desc = f"{label} | {name}", template.format(name=name)
        if path == "menu":
            from apps.catalog.models import Product

            names = list(Product.unscoped.filter(restaurant=restaurant, is_archived=False, is_available=True, category__is_active=True).values_list("name", flat=True)[:40])
            lines = names
    elif path.startswith("menu/") and path.count("/") == 1:
        from apps.catalog.models import Product

        p = Product.unscoped.filter(restaurant=restaurant, slug=path.split("/")[1], is_archived=False, category__is_active=True).first()
        if p is None:
            return None
        title, desc = f"{p.name} | {name}", (plain(p.description) or f"{p.name} from {name}.")[:160]
        try:
            image = _absolute(p.image.url) if p.image else image
        except Exception:  # noqa: BLE001
            pass
        data = {"@context": "https://schema.org", "@type": "MenuItem", "name": p.name, "description": desc, "image": image,
                "offers": {"@type": "Offer", "price": str(p.base_price), "priceCurrency": st.currency}}
    elif path.startswith("policies/"):
        label = path.split("/", 1)[1].replace("-", " ").capitalize()
        title, desc = f"{label} | {name}", f"{label} of {name}."
    else:
        return None
    links = [(f"/{restaurant.slug}/menu", "Menu"), (f"/{restaurant.slug}/reserve", "Reserve"), (f"/{restaurant.slug}/contact", "Contact")]
    return {"title": title[:120], "description": desc[:200], "url": base + (f"/{path}" if path else ""), "image": image, "site": name,
            "data": data, "heading": title.split(" | ")[0] if path else name, "links": links, "lines": lines or [desc[:200]]}


def page_meta(request, path):
    """Metadata of a public page, or None for private and unknown pages (which are marked noindex)."""
    path = (path or "").strip("/")
    restaurant = getattr(request, "tenant", None)
    return _tenant(restaurant, path) if restaurant is not None else _platform(path)


def head_tags(meta):
    if meta is None:
        return '<meta name="robots" content="noindex, nofollow" />'
    e = lambda v: escape(str(v), quote=True)  # noqa: E731
    tags = [f'<meta name="description" content="{e(meta["description"])}" />', '<meta name="robots" content="index, follow, max-image-preview:large" />',
            f'<link rel="canonical" href="{e(meta["url"])}" />']
    for prop, value in (("og:type", "website"), ("og:site_name", meta["site"]), ("og:title", meta["title"]), ("og:description", meta["description"]),
                        ("og:url", meta["url"]), ("og:image", meta["image"])):
        tags.append(f'<meta property="{prop}" content="{e(value)}" />')
    for name, value in (("twitter:card", "summary_large_image"), ("twitter:title", meta["title"]), ("twitter:description", meta["description"]), ("twitter:image", meta["image"])):
        tags.append(f'<meta name="{name}" content="{e(value)}" />')
    if meta["data"]:
        # a data block, never executed (so the strict Content-Security-Policy allows it); "<" is escaped so content cannot close it
        blob = json.dumps(meta["data"], ensure_ascii=False).replace("<", "\\u003c")
        tags.append(f'<script type="application/ld+json" id="jsonld">{blob}</script>')
    return "\n    ".join(tags)


def noscript(meta):
    if meta is None:
        return ""
    e = lambda v: escape(str(v), quote=True)  # noqa: E731
    items = "".join(f"<li>{e(line)}</li>" for line in meta["lines"])
    nav = " ".join(f'<a href="{e(href)}">{e(label)}</a>' for href, label in meta["links"])
    return f"<noscript><h1>{e(meta['heading'])}</h1><ul>{items}</ul><nav>{nav}</nav></noscript>"
