import json
import hashlib
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


class DadataError(Exception):
    """Base error raised while requesting organization details."""


class DadataNotConfigured(DadataError):
    pass


class DadataUnavailable(DadataError):
    pass


STATUS_LABELS = {
    "ACTIVE": "Действующая",
    "LIQUIDATING": "Ликвидируется",
    "LIQUIDATED": "Ликвидирована",
    "BANKRUPT": "Банкротство",
    "REORGANIZING": "Реорганизация",
}


def _first_value(items):
    if not items:
        return ""
    first = items[0] or {}
    return first.get("value") or first.get("unrestricted_value") or ""


def _normalize_party(suggestion):
    data = suggestion.get("data") or {}
    names = data.get("name") or {}
    address = data.get("address") or {}
    management = data.get("management") or {}
    state = data.get("state") or {}
    status = state.get("status") or ""
    registration_timestamp = state.get("registration_date")
    registration_date = ""
    if isinstance(registration_timestamp, (int, float)):
        registration_date = datetime.fromtimestamp(
            registration_timestamp / 1000,
            tz=timezone.utc,
        ).date().isoformat()
    return {
        "full_name": names.get("full_with_opf") or suggestion.get("value") or "",
        "short_name": names.get("short_with_opf") or suggestion.get("value") or "",
        "inn": data.get("inn") or "",
        "kpp": data.get("kpp") or "",
        "ogrn": data.get("ogrn") or "",
        "okato": data.get("okato") or "",
        "registration_date": registration_date,
        "legal_address": (
            address.get("unrestricted_value") or address.get("value") or ""
        ),
        "director_name": management.get("name") or "",
        "director_post": management.get("post") or "",
        "phone": _first_value(data.get("phones")),
        "email": _first_value(data.get("emails")),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "is_invalid": bool(data.get("invalid")),
        "organization_type": data.get("type") or "",
        "address_data": {
            "fias_id": address.get("fias_id") or "",
            "postal_code": address.get("postal_code") or "",
            "region_code": str(address.get("region_kladr_id") or "")[:2],
            "region": address.get("region_with_type") or "",
            "area": address.get("area_with_type") or "",
            "city": address.get("city_with_type") or "",
            "settlement": address.get("settlement_with_type") or "",
            "street": address.get("street_with_type") or "",
            "house": address.get("house") or "",
            "block": " ".join(
                part
                for part in (address.get("block_type"), address.get("block"))
                if part
            ),
            "flat": address.get("flat") or "",
        },
    }


def _request_suggestions(url, payload):
    token = settings.DADATA_API_TOKEN
    if not token:
        raise DadataNotConfigured(
            "Не задан серверный ключ DaData (DADATA_API_TOKEN)."
        )

    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "User-Agent": "ExpeditorCRM/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.DADATA_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in {401, 403}:
            message = "DaData отклонила API-ключ. Проверьте DADATA_API_TOKEN."
        elif error.code == 429:
            message = "Превышен лимит запросов DaData."
        else:
            message = f"DaData временно недоступна (HTTP {error.code})."
        raise DadataUnavailable(message) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise DadataUnavailable(
            "Не удалось получить ответ DaData. Попробуйте ещё раз позже."
        ) from error


def find_party_by_inn(inn):
    cache_key = f"dadata-party:{inn}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _request_suggestions(
        settings.DADATA_PARTY_URL,
        {"query": inn, "count": 1, "branch_type": "MAIN"},
    )

    suggestions = result.get("suggestions") or []
    party = _normalize_party(suggestions[0]) if suggestions else None
    cache.set(cache_key, party, timeout=60 * 60 * 12)
    return party


def suggest_addresses(query, city="", count=10):
    """Return normalized DaData address suggestions without exposing the token."""

    query = " ".join(str(query or "").split())
    city = " ".join(str(city or "").split())
    full_query = query
    if city and city.casefold() not in query.casefold():
        full_query = f"{city}, {query}"

    digest = hashlib.sha256(full_query.casefold().encode("utf-8")).hexdigest()
    cache_key = f"dadata-address:{digest}:{count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _request_suggestions(
        settings.DADATA_ADDRESS_URL,
        {"query": full_query, "count": max(1, min(int(count), 20))},
    )
    suggestions = []
    for suggestion in result.get("suggestions") or []:
        data = suggestion.get("data") or {}
        value = suggestion.get("value") or suggestion.get("unrestricted_value") or ""
        if not value:
            continue
        suggestions.append(
            {
                "value": value,
                "unrestricted_value": suggestion.get("unrestricted_value") or value,
                "postal_code": data.get("postal_code") or "",
                "region": data.get("region_with_type") or "",
                "region_code": str(data.get("region_kladr_id") or "")[:2],
                "area": data.get("area_with_type") or "",
                "city": (
                    data.get("city_with_type")
                    or data.get("settlement_with_type")
                    or ""
                ),
                "settlement": data.get("settlement_with_type") or "",
                "street": data.get("street_with_type") or "",
                "house": data.get("house") or "",
                "block": " ".join(
                    part
                    for part in (
                        data.get("block_type"),
                        data.get("block"),
                    )
                    if part
                ),
                "flat": data.get("flat") or "",
                "fias_id": data.get("fias_id") or "",
            }
        )
    cache.set(cache_key, suggestions, timeout=60 * 30)
    return suggestions


def suggest_person_names(query, part, count=10):
    """Return granular surname, name or patronymic suggestions."""

    part = str(part or "").upper()
    if part not in {"SURNAME", "NAME", "PATRONYMIC"}:
        raise ValueError("Unsupported FIO part")
    query = " ".join(str(query or "").split())
    digest = hashlib.sha256(f"{part}:{query.casefold()}".encode("utf-8")).hexdigest()
    cache_key = f"dadata-fio:{digest}:{count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _request_suggestions(
        settings.DADATA_FIO_URL,
        {
            "query": query,
            "count": max(1, min(int(count), 20)),
            "parts": [part],
        },
    )
    suggestions = []
    for suggestion in result.get("suggestions") or []:
        data = suggestion.get("data") or {}
        value = suggestion.get("value") or ""
        if not value:
            continue
        suggestions.append(
            {
                "value": value,
                "surname": data.get("surname") or "",
                "name": data.get("name") or "",
                "patronymic": data.get("patronymic") or "",
                "gender": data.get("gender") or "UNKNOWN",
            }
        )
    cache.set(cache_key, suggestions, timeout=60 * 60 * 12)
    return suggestions


def suggest_fms_units(query, count=10):
    """Return passport-issuing authority suggestions from DaData."""

    query = " ".join(str(query or "").split())
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    cache_key = f"dadata-fms:{digest}:{count}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _request_suggestions(
        settings.DADATA_FMS_UNIT_URL,
        {"query": query, "count": max(1, min(int(count), 20))},
    )
    suggestions = []
    for suggestion in result.get("suggestions") or []:
        data = suggestion.get("data") or {}
        name = data.get("name") or suggestion.get("value") or ""
        if not name:
            continue
        suggestions.append(
            {
                "value": name,
                "code": data.get("code") or "",
                "region_code": data.get("region_code") or "",
                "unit_type": data.get("type") or "",
            }
        )
    cache.set(cache_key, suggestions, timeout=60 * 60 * 12)
    return suggestions
