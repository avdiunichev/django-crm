"""Small client for generating a final Diadoc/Контур title XML."""

import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class KonturError(Exception):
    """Base error for the Контур/Диадок integration."""


class KonturNotConfigured(KonturError):
    """Raised when the API token or sender box is missing."""


class KonturUnavailable(KonturError):
    """Raised when Контур rejects a request or is temporarily unavailable."""


def _decode_xml(content):
    """Decode an operator response while respecting its XML declaration."""

    match = re.search(rb"encoding=[\"']([^\"']+)[\"']", content[:300], re.I)
    declared = match.group(1).decode("ascii", errors="ignore").lower() if match else ""
    encoding = {
        "windows-1251": "cp1251",
        "cp1251": "cp1251",
    }.get(declared, declared or "utf-8")
    try:
        return content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def generate_ezz_title_xml(transportation, user_data_xml):
    """Generate a loadable ON_ZAKZVGO title through Diadoc.

    Kontur's ``UserDataXml`` is only an input to ``GenerateTitleXml``. The
    response from this method is the final XML file (usually Windows-1251)
    that can be imported or sent further through the operator.
    """

    token = getattr(settings, "KONTUR_DIADOC_API_TOKEN", "").strip()
    if not token:
        raise KonturNotConfigured(
            "Не задан токен API Контур.Диадок (KONTUR_DIADOC_API_TOKEN)."
        )
    owner_company = transportation.owner_company
    box_id = getattr(owner_company, "edo_id", "").strip()
    if not box_id:
        raise KonturNotConfigured(
            "Укажите идентификатор ящика ЭДО нашей компании (boxId) "
            "в карточке контрагента."
        )

    api_url = getattr(
        settings,
        "KONTUR_DIADOC_API_URL",
        "https://diadoc-api.kontur.ru",
    ).rstrip("/")
    query = urlencode(
        {
            "boxId": box_id,
            "documentTypeNamedId": "LogisticsOrderRequest",
            "documentFunction": "default",
            "documentVersion": "zakzvper_05_01_01",
            "titleIndex": "0",
        }
    )
    request = Request(
        f"{api_url}/GenerateTitleXml?{query}",
        data=user_data_xml.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/xml",
            "Content-Type": "application/xml; charset=utf-8",
            "User-Agent": "ExpeditorCRM/1.0",
        },
        method="POST",
    )
    timeout = float(getattr(settings, "KONTUR_DIADOC_API_TIMEOUT", 30))
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        suffix = f" {detail[:300]}" if detail else ""
        raise KonturUnavailable(
            f"Контур отклонил XML (HTTP {error.code}).{suffix}"
        ) from error
    except (URLError, TimeoutError) as error:
        raise KonturUnavailable(
            "Не удалось обратиться к API Контур.Диадок. Проверьте сеть "
            "и настройки интеграции."
        ) from error

    if not content.strip():
        raise KonturUnavailable("Контур вернул пустой XML-файл.")
    return _decode_xml(content)
