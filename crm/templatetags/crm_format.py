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


@register.filter
def days(value):
    """Render a number of days using the correct Russian form."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return value
    remainder = abs(number) % 100
    if 11 <= remainder <= 14:
        suffix = "дней"
    else:
        tail = abs(number) % 10
        suffix = "день" if tail == 1 else "дня" if 2 <= tail <= 4 else "дней"
    return f"{number} {suffix}"


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Return current query string with selected parameters replaced/removed."""
    request = context.get("request")
    if request is None:
        return ""
    query = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == "":
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()
