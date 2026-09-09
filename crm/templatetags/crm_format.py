from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def money(value, decimals=2):
    """Format money as 1 000 000,00 for Russian accounting-style screens."""
    if value in (None, ""):
        return "0,00"
    try:
        amount = Decimal(str(value))
        places = int(decimals)
    except (InvalidOperation, TypeError, ValueError):
        return value

    formatted = f"{amount:,.{places}f}"
    return formatted.replace(",", " ").replace(".", ",")


@register.filter
def currency_symbol(value):
    symbols = {
        "RUB": "₽",
        "RUR": "₽",
        "USD": "$",
        "EUR": "€",
        "CNY": "¥",
    }
    if value in (None, ""):
        return ""
    return symbols.get(str(value).upper(), value)


@register.filter
def decimal_input(value, decimals=2):
    """Format decimal value for HTML number inputs as 1000000.00."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
        places = int(decimals)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{amount:.{places}f}"
