"""Generic default policy texts, used until the restaurant writes its own. Restaurants should review them."""

POLICY_TITLES = {
    "privacy-policy": "Privacy Policy",
    "terms-of-use": "Terms of Use",
    "payment-policy": "Payment Policy",
    "refund-and-cancellation-policy": "Refund and Cancellation Policy",
}

_DEFAULTS = {
    "privacy-policy": "{name} collects the personal details you provide (such as your name, email, phone number and delivery "
                      "address) and your order history to prepare and deliver your orders, send receipts and keep your account secure. "
                      "We do not sell your data. To access, correct or delete your information, contact us using the details on this website.",
    "terms-of-use": "By using this website and placing orders with {name} you agree to provide accurate information and to use the "
                    "service lawfully. Prices, availability and preparation times may change. We may refuse or cancel orders in cases of "
                    "suspected abuse or unavailable items.",
    "payment-policy": "Orders are paid by the methods shown at checkout, which may include cash and mobile money. An order is confirmed "
                      "only after payment is confirmed or accepted by our staff. Please keep your receipt as proof of payment.",
    "refund-and-cancellation-policy": "Contact {name} as soon as possible if you need to cancel or have a problem with an order. "
                                      "Orders that have not started preparation can usually be cancelled. Refunds for eligible orders "
                                      "are returned using the original payment method where possible.",
}


def resolve_policies(restaurant):
    custom = restaurant.get_settings().policies or {}
    return {k: (custom.get(k) or _DEFAULTS[k].format(name=restaurant.name)) for k in POLICY_TITLES}
