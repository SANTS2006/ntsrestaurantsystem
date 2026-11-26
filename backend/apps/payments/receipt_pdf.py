"""The PDF of a sales receipt, laid out for an 80 mm thermal roll: one page, 80 mm wide and exactly as long as the receipt,
72 mm printable, black only (thermal printers have no colour). The content comes from the receipt's stored snapshot."""
import io
from datetime import datetime
from decimal import Decimal

import qrcode
from django.utils import timezone
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

WIDTH = 80 * mm
MARGIN = 4 * mm
INNER = WIDTH - 2 * MARGIN
FULFILMENT = {"dine_in": "Dine in", "pickup": "Takeaway / pickup", "delivery": "Delivery"}
METHODS = {"cash": "Cash", "mobile_money": "Mobile money"}


def money(currency, value):
    return f"{currency} {Decimal(str(value or 0)):,.2f}"


def _clean(text):
    """The built-in PDF fonts cover Latin text only: anything else is replaced rather than printed as boxes."""
    return str(text or "").replace("−", "-").replace("×", "x").encode("cp1252", "replace").decode("cp1252")


def _wrap(text, font, size, width):
    words, lines, current = _clean(text).split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if stringWidth(trial, font, size) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        while stringWidth(word, font, size) > width and len(word) > 1:  # a single very long word is cut across lines
            cut = len(word)
            while cut > 1 and stringWidth(word[:cut], font, size) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


class _Roll:
    """Collects drawing steps from the top down, so the page can be made exactly as tall as the content."""

    def __init__(self):
        self.y = 5 * mm
        self.steps = []

    def text(self, value, size=8, bold=False, align="left", indent=0, gap=1.32):
        font = "Helvetica-Bold" if bold else "Helvetica"
        for line in _wrap(value, font, size, INNER - indent):
            self.y += size * gap
            y = self.y
            if align == "center":
                self.steps.append(lambda c, h, line=line, y=y, font=font, size=size: (c.setFont(font, size), c.drawCentredString(WIDTH / 2, h - y, line)))
            else:
                self.steps.append(lambda c, h, line=line, y=y, font=font, size=size, indent=indent: (c.setFont(font, size), c.drawString(MARGIN + indent, h - y, line)))

    def row(self, left, right, size=8, bold=False, indent=0):
        font = "Helvetica-Bold" if bold else "Helvetica"
        right = _clean(right)
        room = INNER - indent - stringWidth(right, font, size) - 3 * mm
        lines = _wrap(left, font, size, max(room, 20 * mm))
        for n, line in enumerate(lines):
            self.y += size * 1.36
            y = self.y

            def draw(c, h, line=line, y=y, n=n, font=font, size=size, right=right, indent=indent):
                c.setFont(font, size)
                c.drawString(MARGIN + indent, h - y, line)
                if n == 0:
                    c.drawRightString(WIDTH - MARGIN, h - y, right)

            self.steps.append(draw)

    def rule(self, dashed=True):
        self.y += 6
        y = self.y

        def draw(c, h, y=y):
            c.setDash(2, 2) if dashed else c.setDash()
            c.setLineWidth(0.7)
            c.line(MARGIN, h - y, WIDTH - MARGIN, h - y)
            c.setDash()

        self.steps.append(draw)
        self.y += 2

    def image(self, reader, width, height):
        self.y += 3
        top = self.y
        self.steps.append(lambda c, h, top=top: c.drawImage(reader, (WIDTH - width) / 2, h - top - height, width, height, mask="auto"))
        self.y += height + 2

    def render(self, title):
        height = self.y + 8 * mm
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(WIDTH, height))
        c.setTitle(title)
        for step in self.steps:
            step(c, height)
        c.showPage()
        c.save()
        return buf.getvalue()


def _qr(text):
    buf = io.BytesIO()
    qrcode.make(text, box_size=6, border=1).save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _logo(restaurant):
    """The restaurant's logo in grey, if its file can be read (never fails the receipt)."""
    try:
        from PIL import Image

        with restaurant.logo.open("rb") as handle:
            picture = Image.open(io.BytesIO(handle.read()))
        picture.thumbnail((360, 200))
        flat = Image.new("RGBA", picture.size, "white")
        flat.alpha_composite(picture.convert("RGBA"))
        grey = io.BytesIO()
        flat.convert("L").save(grey, format="PNG")
        grey.seek(0)
        width = 22 * mm
        height = min(18 * mm, width * picture.size[1] / picture.size[0])
        return ImageReader(grey), height * picture.size[0] / picture.size[1], height
    except Exception:  # noqa: BLE001
        return None


def when(value):
    try:
        moment = datetime.fromisoformat(value)
        return timezone.localtime(moment).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return ""


def render_pdf(data, restaurant=None) -> bytes:
    r, b, t, p = data["restaurant"], data["branch"], data["totals"], data["payment"]
    cur = data["currency"]
    roll = _Roll()
    logo = _logo(restaurant) if restaurant is not None and restaurant.logo else None
    if logo:
        roll.image(*logo)
    roll.text(r["name"].upper(), 13, True, "center", gap=1.25)
    address = ", ".join(x for x in (r.get("address"), r.get("city")) if x)
    for line in (address, f"Branch: {b['name']}" + (f", {b['address']}" if b.get("address") else ""),
                 " | ".join(x for x in (b.get("phone") or r.get("phone"), r.get("email")) if x)):
        if line:
            roll.text(line, 7.5, align="center")
    roll.rule()
    roll.text("SALES RECEIPT", 9.5, True, "center", gap=1.4)
    roll.row("Receipt no.", data["number"], bold=True)
    roll.row("Order no.", data["order_number"])
    roll.row("Date", when(p.get("paid_at") or data.get("issued_at")))
    roll.row("Order type", FULFILMENT.get(data.get("fulfilment"), data.get("fulfilment", "")))
    if data.get("table"):
        roll.row("Table", data["table"])
    if data.get("cashier"):
        roll.row("Served by", data["cashier"])
    if data["customer"].get("name"):
        roll.row("Customer", data["customer"]["name"])
    roll.rule()
    roll.row("ITEM", "AMOUNT", 7.5, True)
    for item in data["items"]:
        name = item["name"] + (f" ({item['variation']})" if item.get("variation") else "")
        roll.row(name, money(cur, item["line_total"]), 8.5, True)
        roll.text(f"{item['quantity']} x {money(cur, item['unit_price'])}", 7.5, indent=3 * mm)
        for extra in item.get("addons") or []:
            roll.text(f"+ {extra['quantity']} x {extra['name']}", 7.5, indent=3 * mm)
    roll.rule()
    roll.row("Subtotal", money(cur, t["subtotal"]))
    for label, key, sign in (("Discount", "discount", "-"), ("Tax", "tax", ""), ("Delivery fee", "delivery_fee", "")):
        if Decimal(t[key]) != 0:
            roll.row(label, sign + money(cur, t[key]))
    roll.rule(dashed=False)
    roll.row("TOTAL", money(cur, t["total"]), 12, True)
    roll.rule(dashed=False)
    roll.row(f"Paid ({METHODS.get(p['method'], p['method'])})", money(cur, p["amount"]), bold=True)
    if p.get("received"):
        roll.row("Cash received", money(cur, p["received"]))
        roll.row("Change", money(cur, p.get("change")))
    if Decimal(t["total"]) > Decimal(p["amount"]):
        roll.row("This is a part payment of", money(cur, t["total"]))
    roll.text(f"Ref: {p['reference']}", 7)
    roll.rule()
    roll.text(data.get("footer") or "Thank you for your order. Please come again!", 8.5, True, "center", gap=1.4)
    if data.get("website"):
        roll.image(_qr(data["website"]), 24 * mm, 24 * mm)
        roll.text("Scan to order online", 7, align="center")
        roll.text(data["website"].split("://", 1)[-1], 7, align="center")
    roll.text("Please keep this receipt.", 7, align="center", gap=1.8)
    return roll.render(f"Receipt {data['number']}")
