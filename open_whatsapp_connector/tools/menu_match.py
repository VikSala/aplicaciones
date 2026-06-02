"""Resolve a customer's menu reply to an option, robust across delivery modes.

WhatsApp interactive list/button messages are unreliable on the unofficial
(QR-paired) transport — they may silently fail to render. To stay usable, every
menu is *also* shown as a numbered text body, and this helper maps whatever the
customer sends back to the intended option:

    * an interactive tap echo  -- the inbound pipeline records it as
      ``[List] <row title>`` or ``[Button] <button text>``
    * a bare number            -- the 1-based position in the menu
    * the option/product name  -- case-insensitive (tolerating the 24-char
      list-title truncation WhatsApp applies)
"""


def match_menu_choice(labels, body):
    """Return the 0-based index of the chosen option, or ``None``.

    :param labels: ordered list of the option titles as shown to the customer
    :param body: the raw inbound message body
    """
    text = (body or "").strip()
    if not text:
        return None
    # Strip the interactive-response echo the inbound pipeline prepends.
    for prefix in ("[List]", "[Button]"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            # list row echo is "<title> — <description>"; keep the title
            text = text.split(" — ")[0].strip()
            break
    if not text:
        return None
    # Bare number -> Nth option (1-based).
    if text.isdigit():
        n = int(text)
        return n - 1 if 1 <= n <= len(labels) else None
    # Name match (case-insensitive); tolerate the 24-char list-title truncation.
    low = text.lower()
    for index, label in enumerate(labels):
        norm = (label or "").strip().lower()
        if norm and (low == norm or low == norm[:24] or norm == low[:24]):
            return index
    return None
