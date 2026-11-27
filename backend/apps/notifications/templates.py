"""Branded transactional email templates. All dynamic values are HTML-escaped."""
from contextvars import ContextVar

from django.conf import settings
from django.utils.html import escape

PLATFORM_COLOR = "#0a72e0"


_CURRENT = ContextVar("email_restaurant", default=None)
PLATFORM_NAVY = "#0b3f93"
PLATFORM_CYAN = "#14b4f5"


def _site_base():
    return f"{settings.PUBLIC_URL_SCHEME}://{settings.PLATFORM_DOMAIN}"


def _abs(url):
    if not url:
        return ""
    return url if url.startswith(("http://", "https://")) else f"{_site_base()}{url}"


def _restaurant_logo(r):
    try:
        return _abs(r.logo.url) if r.logo else ""
    except Exception:  # noqa: BLE001
        return ""


def _layout(brand, color, heading, body_html):
    """Two looks. Platform mail (sign-up, staff invitations, security) carries the NTS logo on the platform blue.
    Restaurant mail carries that restaurant's logo, colour, contact details and its own footer text."""
    r = _CURRENT.get()
    if r is None:
        logo = _abs("/logo-192.png")
        accent = PLATFORM_CYAN
        head_logo = f'<img src="{escape(logo)}" width="44" height="44" alt="" style="vertical-align:middle;border-radius:8px;margin-right:12px;background:#fff">'
        footer = (f'<p style="margin:0 0 6px">This is an automated message from <b>{escape(brand)}</b>. If you did not expect it, you can ignore it.</p>'
                  f'<p style="margin:0">Need help? Write to <a href="mailto:{escape(settings.BREVO_SENDER_EMAIL)}" style="color:{PLATFORM_NAVY}">{escape(settings.BREVO_SENDER_EMAIL)}</a></p>')
        powered = ""
    else:
        logo = _restaurant_logo(r)
        accent = r.secondary_color or color
        head_logo = (f'<img src="{escape(logo)}" width="44" height="44" alt="" style="vertical-align:middle;border-radius:8px;margin-right:12px;background:#fff;object-fit:cover">' if logo else "")
        st = r.get_settings()
        contact = " &middot; ".join(escape(x) for x in (r.address, r.contact_phone, r.contact_email) if x)
        custom = f'<p style="margin:0 0 6px">{escape(st.email_footer)}</p>' if st.email_footer else ""
        footer = (f'{custom}<p style="margin:0 0 6px"><b>{escape(r.name)}</b>' + (f" &middot; {contact}" if contact else "") + "</p>"
                  f'<p style="margin:0"><a href="{escape(r.public_url)}" style="color:{escape(color)}">{escape(r.public_url)}</a></p>')
        powered = '<p style="margin:10px 0 0;color:#9aa6b8">Sent through NTS Restaurant Platform</p>'
    return f"""<!doctype html><html><body style="margin:0;background:#eef3fa;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #dbe5f3">
<tr><td style="background:{escape(color)};color:#fff;padding:18px 24px;font-size:19px;font-weight:bold">{head_logo}<span style="vertical-align:middle">{escape(brand)}</span></td></tr>
<tr><td style="height:4px;background:{escape(accent)};font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:26px 24px;color:#0c1b33;font-size:15px;line-height:1.6"><h2 style="margin:0 0 14px;font-size:22px;color:#0c1b33">{escape(heading)}</h2>{body_html}</td></tr>
<tr><td style="padding:16px 24px;background:#f6f9ff;color:#566883;font-size:12px;line-height:1.5;border-top:1px solid #dbe5f3">{footer}{powered}</td></tr>
</table></td></tr></table></body></html>"""


def _code_block(code):
    return (f'<p style="font-size:28px;letter-spacing:6px;font-weight:bold;background:#f3f4f6;'
            f'padding:12px 16px;text-align:center;border-radius:6px">{escape(code)}</p>')


def _button(url, label, color):
    return (f'<p><a href="{escape(url)}" style="background:{escape(color)};color:#fff;padding:12px 20px;'
            f'border-radius:6px;text-decoration:none;display:inline-block">{escape(label)}</a></p>')


def _minutes():
    return settings.VERIFICATION_CODE_TTL_SECONDS // 60


def render_email(template, ctx, restaurant=None):
    token = _CURRENT.set(restaurant)
    try:
        return _render(template, ctx, restaurant)
    finally:
        _CURRENT.reset(token)


def _render(template, ctx, restaurant=None):
    brand = restaurant.name if restaurant else settings.BREVO_SENDER_NAME
    color = restaurant.primary_color if restaurant else PLATFORM_COLOR
    name = escape(ctx.get("name") or "there")

    if template == "verify_email":
        return f"Your {brand} verification code", _layout(brand, color, "Verify your email", (
            f"<p>Hello {name}, enter this code to verify your email address.</p>{_code_block(ctx['code'])}"
            f"<p>It expires in {_minutes()} minutes. Never share this code with anyone.</p>"))
    if template == "password_reset":
        return f"{brand} password reset code", _layout(brand, color, "Reset your password", (
            f"<p>Hello {name}, use this code to reset your password.</p>{_code_block(ctx['code'])}"
            f"<p>It expires in {_minutes()} minutes. If you did not request this, no action is needed.</p>"))
    if template == "password_changed":
        return f"Your {brand} password was changed", _layout(brand, color, "Password changed", (
            f"<p>Hello {name}, the password on your account was just changed. If this was not you, "
            f"reset your password immediately and contact support.</p>"))
    if template == "account_exists":
        return f"{brand}: sign-in instructions", _layout(brand, color, "You already have an account", (
            f"<p>Hello {name}, someone tried to register with this email address. You can sign in, "
            f"or reset your password if you have forgotten it.</p>" + _button(ctx["login_url"], "Go to sign in", color)))
    if template == "staff_invitation":
        return f"You have been invited to {brand}", _layout(brand, color, "Welcome to the team", (
            f"<p>Hello {name}, you have been added to {escape(brand)} as <b>{escape(ctx['role_label'])}</b>.</p>"
            f"<p>Your sign-in email: <b>{escape(ctx['email'])}</b></p>"
            f"<p>Set your password using the secure link below. The link works once and expires in "
            f"{settings.SETUP_TOKEN_TTL_HOURS} hours. You must choose your own password before using the system.</p>"
            + _button(ctx["setup_url"], "Set my password", color)
            + f"<p>Login page: {escape(ctx['login_url'])}</p>"))
    if template == "restaurant_onboarding":
        return f"Your restaurant {ctx['restaurant_name']} is ready", _layout(brand, color, "Welcome aboard", (
            f"<p>Hello {name}, <b>{escape(ctx['restaurant_name'])}</b> has been registered on {escape(brand)} "
            f"and you are its administrator.</p>"
            f"<p>Your sign-in email: <b>{escape(ctx['email'])}</b><br>Restaurant system login: {escape(ctx['login_url'])}</p>"
            f"<p>Create your password with the secure one-time link below. It expires in {settings.SETUP_TOKEN_TTL_HOURS} hours "
            f"and stops working once used. You must set your own password before you can use the system.</p>"
            + _button(ctx["setup_url"], "Set my password", color)))
    if template == "order_confirmation":
        items = "".join(f"<li>{escape(i)}</li>" for i in ctx["items"])
        return f"Order {ctx['number']} received", _layout(brand, color, "Thank you for your order", (
            f"<p>Hello {name}, we received your order <b>{escape(ctx['number'])}</b>.</p><ul>{items}</ul>"
            f"<p>{escape(ctx['fulfilment'])} · {escape(ctx['payment'])}<br>Total: <b>{escape(ctx['total'])}</b></p>"
            f"<p>The restaurant will confirm it shortly. You will be emailed as the status changes.</p>"
            + _button(ctx["url"], "Track my order", color)))
    if template == "order_status":
        extra = f"<p>Note from the restaurant: {escape(ctx['note'])}</p>" if ctx.get("note") else ""
        return f"Order {ctx['number']}: {ctx['status']}", _layout(brand, color, f"Your order is now {ctx['status']}", (
            f"<p>Hello {name}, the status of order <b>{escape(ctx['number'])}</b> changed to <b>{escape(ctx['status'])}</b>.</p>{extra}"
            + _button(ctx["url"], "View order", color)))
    if template == "salary_structure_updated":
        return f"Your salary details were updated at {brand}", _layout(brand, color, "Salary details updated", (
            f"<p>Hello {name}, your salary structure was updated, effective <b>{escape(ctx['effective'])}</b>. "
            f"You can review it under My pay.</p>"))
    if template == "salary_paid":
        return f"Salary paid: {ctx['period']}", _layout(brand, color, "Your salary has been paid", (
            f"<p>Hello {name}, your salary for <b>{escape(ctx['period'])}</b> was paid. Net pay: <b>{escape(ctx['net'])}</b>. "
            f"Receipt: {escape(ctx['number'])}.</p>" + _button(ctx["url"], "View my pay slip", color)))
    if template == "invoice_issued":
        return f"Invoice {ctx['number']} from {brand}", _layout(brand, color, f"Invoice {escape(ctx['number'])}", (
            f"<p>Hello {name}, an invoice for <b>{escape(ctx['total'])}</b> has been issued to you by {escape(brand)}. "
            f"Payment is due by <b>{escape(ctx['due'])}</b>. Please contact the restaurant for a copy or payment details.</p>"))
    if template == "payroll_update":
        rows = "".join(f"<li>{escape(line)}</li>" for line in ctx["lines"])
        note = f"<p>{escape(ctx['note'])}</p>" if ctx["note"] else ""
        return f"{ctx['subject']} ({brand})", _layout(brand, color, escape(ctx["heading"]), (
            f"<p>Hello {name},</p><p>{escape(ctx['text'])}</p>" + (f"<ul>{rows}</ul>" if rows else "") + note
            + _button(ctx["url"], "Open payroll", color)))
    if template == "contact_received":
        body = escape(ctx["message"]).replace("\n", "<br>")
        return f"New website message {ctx['reference']}: {' '.join(str(ctx['subject']).split())[:100]}", _layout(brand, color, "A new message from your website", (
            f"<p><b>{escape(ctx['name'])}</b> wrote to you.<br>Email: {escape(ctx['email'])}<br>Phone: {escape(ctx['phone'])}</p>"
            f"<p><b>{escape(ctx['subject'])}</b><br>{body}</p>" + _button(ctx["url"], "Open the message", color)))
    if template == "contact_reply":
        reply = escape(ctx["reply"]).replace("\n", "<br>")
        original = escape(ctx["original"][:1500]).replace("\n", "<br>")
        return f"Re: {' '.join(str(ctx['subject']).split())[:120]} ({ctx['reference']})", _layout(brand, color, "We have replied to your message", (
            f"<p>Hello {name},</p><p>{reply}</p>"
            f'<p style="margin:18px 0 6px;color:#566883;font-size:13px">Your message ({escape(ctx["reference"])}):</p>'
            f'<div style="padding:10px 12px;background:#f6f9ff;border:1px solid #dbe5f3;border-radius:8px;color:#566883;font-size:13px">{original}</div>'))
    if template == "reservation_confirmed":
        return f"Your reservation at {brand}", _layout(brand, color, "Reservation confirmed", (
            f"<p>Hello {name}, your table for <b>{escape(ctx['party'])}</b> is booked for <b>{escape(ctx['when'])}</b>. "
            f"Reference: <b>{escape(ctx['reference'])}</b>.</p>" + _button(ctx["url"], "View or cancel my booking", color)))
    if template == "reservation_cancelled":
        return f"Your reservation at {brand} was cancelled", _layout(brand, color, "Reservation cancelled", (
            f"<p>Hello {name}, your reservation <b>{escape(ctx['reference'])}</b> for {escape(ctx['when'])} has been cancelled.</p>"))
    if template == "account_deactivated":
        return f"Your {brand} account has been deactivated", _layout(brand, color, "Account deactivated", (
            f"<p>Hello {name}, your account at <b>{escape(brand)}</b> has been deactivated. You have been signed out and can no longer sign in.</p>"
            f"<p>If you think this is a mistake, please contact the restaurant.</p>"))
    if template == "account_activated":
        return f"Your {brand} account has been activated", _layout(brand, color, "Account activated", (
            f"<p>Hello {name}, your account at <b>{escape(brand)}</b> has been activated again. You can sign in now.</p>"
            + _button(ctx["login_url"], "Sign in", color)))
    if template == "email_changed":
        return f"Your {brand} email address was changed", _layout(brand, color, "Email address changed", (
            f"<p>Hello {name}, the sign-in email on your account was changed to <b>{escape(ctx['new_email'])}</b>. "
            f"If this was not you, contact the restaurant immediately.</p>"))
    if template == "payment_receipt":
        return f"Receipt {ctx['number']} for order {ctx['order_number']}", _layout(brand, color, "Payment received", (
            f"<p>Hello {name}, we received your payment of <b>{escape(ctx['amount'])}</b> ({escape(ctx['method'])}) "
            f"for order <b>{escape(ctx['order_number'])}</b>.</p><p>Receipt number: <b>{escape(ctx['number'])}</b></p>"
            + _button(ctx["url"], "View order and receipt", color)))
    if template == "refund_notice":
        return f"Refund for order {ctx['number']}", _layout(brand, color, "Refund processed", (
            f"<p>Hello {name}, a refund of <b>{escape(ctx['amount'])}</b> was issued for order <b>{escape(ctx['number'])}</b>. "
            f"It may take time to appear with your payment provider.</p>"))
    if template == "catering_received":
        return f"We received your catering request {ctx['reference']}", _layout(brand, color, "Request received", (
            f"<p>Hello {name}, thank you for your {escape(ctx['event'])} request for <b>{escape(ctx['date'])}</b>. "
            f"Your reference is <b>{escape(ctx['reference'])}</b>.</p>"
            f"<p>Our team will review it and contact you with a quotation or any questions. This message is not a booking confirmation.</p>"))
    if template == "catering_staff_alert":
        return f"Catering {ctx['reference']}: {ctx['event']}", _layout(brand, color, "Catering update", (
            f"<p><b>{escape(ctx['reference'])}</b>: {escape(ctx['event'])}<br>Event date: {escape(ctx['date'])} · Guests: {escape(str(ctx['guests']))}</p>"
            + _button(ctx["url"], "Open catering dashboard", color)))
    if template == "catering_quotation":
        return f"Your catering quotation {ctx['reference']}", _layout(brand, color, "Your quotation is ready", (
            f"<p>Hello {name}, we have prepared a quotation for request <b>{escape(ctx['reference'])}</b>.</p>"
            f"<p>Total: <b>{escape(ctx['total'])}</b><br>Valid until: {escape(ctx['valid_until'])}</p>"
            f"<p>Review the full details and accept or decline using the private link below. Please do not forward this email: anyone with the link can respond.</p>"
            + _button(ctx["url"], "View quotation", color)))
    if template == "catering_status":
        extra = f"<p>Note: {escape(ctx['note'])}</p>" if ctx.get("note") else ""
        return f"Catering request {ctx['reference']}: {ctx['status']}", _layout(brand, color, f"Your request is now: {ctx['status']}", (
            f"<p>Hello {name}, the status of your catering request <b>{escape(ctx['reference'])}</b> changed to <b>{escape(ctx['status'])}</b>.</p>{extra}"))
    if template == "catering_message":
        body = escape(ctx["message"]).replace("\n", "<br>")
        return " ".join(str(ctx["subject"]).split())[:150], _layout(brand, color, "A message about your event", (
            f"<p>Hello {name},</p><p>{body}</p><p>Reference: {escape(ctx['reference'])}. Reply to this email to reach the restaurant.</p>"))
    if template == "catering_payment":
        what = "refund" if ctx["kind"] == "refund" else "payment"
        return f"Catering {what} recorded for {ctx['reference']}", _layout(brand, color, f"{what.capitalize()} recorded", (
            f"<p>Hello {name}, we recorded a {what} of <b>{escape(ctx['amount'])}</b> for booking <b>{escape(ctx['reference'])}</b>.</p>"
            f"<p>Remaining balance: <b>{escape(ctx['balance'])}</b></p>"))
    if template == "staff_added":
        return f"You now have access to {brand}", _layout(brand, color, "Access granted", (
            f"<p>Hello {name}, your existing account now has the role <b>{escape(ctx['role_label'])}</b> at "
            f"{escape(brand)}. Sign in with your current password.</p>" + _button(ctx["login_url"], "Sign in", color)))
    raise KeyError(f"Unknown email template: {template}")
