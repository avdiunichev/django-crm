"""Corporate address presentation, independent of DaData's ready-made string.

Names are never corrected, geocoded or transliterated here. Only object types
and spacing are formatted. Unknown types and nested raw data are preserved.
"""
import re
from copy import deepcopy


class AddressFormatter:
    TYPES = {
        "область": "обл.", "обл": "обл.", "республика": "Респ.", "респ": "Респ.",
        "автономный округ": "АО", "ао": "АО", "автономная область": "АО",
        "аобл": "АО", "край": "край", "город": "г.", "г": "г.",
        "район": "р-н", "р-н": "р-н", "поселок": "п.", "посёлок": "п.",
        "п": "п.", "пос": "п.", "деревня": "д.", "д": "д.",
        "село": "с.", "с": "с.", "рабочий поселок": "рп.",
        "рабочий посёлок": "рп.", "рп": "рп.", "городской поселок": "гп.",
        "городской посёлок": "гп.", "гп": "гп.", "пгт": "пгт.",
        "поселок городского типа": "пгт.", "посёлок городского типа": "пгт.",
        "улица": "ул.", "ул": "ул.", "проспект": "пр-кт", "пр-кт": "пр-кт",
        "переулок": "пер.", "пер": "пер.", "шоссе": "ш.", "ш": "ш.",
        "набережная": "наб.", "наб": "наб.", "бульвар": "б-р", "б-р": "б-р",
        "площадь": "пл.", "пл": "пл.", "проезд": "пр-д", "пр-д": "пр-д",
        "тупик": "туп.", "туп": "туп.", "территория": "тер.", "тер": "тер.",
        "снт": "СНТ", "днп": "ДНП", "дом": "д.", "владение": "влд.",
        "влд": "влд.", "вл": "влд.", "корпус": "корп.", "корп": "корп.",
        "к": "корп.", "строение": "стр.", "стр": "стр.",
        "сооружение": "соор.", "соор": "соор.", "литера": "лит.",
        "лит": "лит.", "помещение": "пом.", "пом": "пом.",
        "офис": "оф.", "оф": "оф.", "квартира": "кв.", "кв": "кв.",
        "комната": "ком.", "ком": "ком.", "участок": "уч.", "уч": "уч.",
        "километр": "км", "км": "км",
    }
    LEVELS = (
        "region", "area", "city", "city_area", "city_district", "settlement",
        "planning_structure", "territory", "street", "additional_address_element",
        "kilometer", "stead", "house", "block", "building", "structure", "letter",
        "flat", "room",
    )
    # These fields have an unambiguous meaning even if their type is absent.
    DEFAULT_TYPES = {
        "stead": "уч.", "building": "стр.", "structure": "соор.",
        "letter": "лит.", "kilometer": "км",
    }

    @staticmethod
    def text(value):
        return re.sub(r"\s+", " ", str(value or "")).strip(" ,")

    @classmethod
    def data(cls, payload):
        if not isinstance(payload, dict):
            return {}
        raw = payload.get("raw_data", payload)
        if not isinstance(raw, dict):
            return {}
        data = raw.get("data", raw)
        return data if isinstance(data, dict) else {}

    @classmethod
    def component(cls, data, key):
        name = cls.text(data.get(key))
        kind = cls.text(data.get(key + "_type") or data.get(key + "_type_full"))
        if not name:
            return cls.text(data.get(key + "_with_type"))
        kind = kind or cls.DEFAULT_TYPES.get(key, "")
        if not kind:
            return name
        canonical = cls.TYPES.get(kind.casefold().rstrip("."), kind)
        aliases = {k for k, v in cls.TYPES.items() if v == canonical}
        aliases.update({kind, canonical})
        previous = None
        while name != previous:
            previous = name
            for alias in sorted(aliases, key=len, reverse=True):
                escaped = re.escape(alias.rstrip("."))
                # Only strip the declared type, never guess a type from the name.
                name = re.sub(r"^" + escaped + r"\.?\s+", "", name, flags=re.I)
                name = re.sub(r"\s+" + escaped + r"\.?$", "", name, flags=re.I)
        if not name:
            return canonical
        if canonical == "км":
            return (name + "-й" if name.isdigit() else name) + " км"
        if key == "region" and canonical in {"обл.", "АО", "край"}:
            return f"{name} {canonical}"
        if key in {"area", "city_district"} and canonical == "р-н":
            return f"{name} {canonical}"
        return f"{canonical} {name}"

    @classmethod
    def format(cls, payload, fallback=""):
        data = cls.data(payload)
        if data.get("country_iso_code") not in (None, "", "RU"):
            return cls.original(payload) or cls.text(fallback)
        components = []
        for key in cls.LEVELS:
            component = cls.component(data, key)
            if not component:
                continue
            if key == "city" and component in components:
                continue  # Federal city supplied as both region and city.
            components.append(component)
        result = ", ".join(components)
        original = cls.original(payload)
        # Incomplete granular responses must not erase a road, km or building
        # that appears only in the original string. Keep it without guessing.
        ignored = {"россия"}
        for kind in (*cls.TYPES.keys(), *cls.TYPES.values()):
            ignored.update(re.findall(r"\w+", kind.casefold()))
        def meaningful_words(value):
            return {word for word in re.findall(r"\w+", value.casefold())
                    if word not in ignored and not re.fullmatch(r"\d{6}", word)}
        address = (
            original
            if original and meaningful_words(original) - meaningful_words(result)
            else result or original or cls.text(fallback)
        )
        # The index is part of the postal address.  DaData keeps it as a
        # separate attribute, so add it explicitly to the normalized value.
        postal_code = cls.text(data.get("postal_code"))
        if postal_code:
            # A manually entered or legacy value can already begin with an
            # outdated index. Keep exactly the index returned by DaData.
            address = re.sub(r"^(?:\d{6}\s*,\s*)+", "", address)
            if not re.match(rf"^{re.escape(postal_code)}(?:,|\s)", address):
                return f"{postal_code}, {address}" if address else postal_code
        return address

    @classmethod
    def original(cls, payload):
        if not isinstance(payload, dict):
            return ""
        raw = payload.get("raw_data", payload)
        if not isinstance(raw, dict):
            return ""
        original = cls.text(raw.get("unrestricted_value") or raw.get("value"))
        # Postal code remains in the raw payload, not in the display hierarchy.
        postal_code = cls.text(cls.data(payload).get("postal_code"))
        if postal_code:
            original = re.sub(r"^" + re.escape(postal_code) + r",\s*", "", original)
        return original

    @classmethod
    def short(cls, payload, fallback=""):
        data = cls.data(payload)
        locality = cls.component(data, "city") or cls.component(data, "settlement")
        if locality:
            return locality
        return ", ".join(filter(None, (
            cls.component(data, "area"), cls.component(data, "kilometer"),
        ))) or cls.component(data, "region") or cls.format(payload, fallback)

    @classmethod
    def snapshot(cls, suggestion):
        """A lossless payload to store, including IDs, coordinates and source."""
        if not isinstance(suggestion, dict):
            return {}
        return deepcopy(suggestion.get("raw_data", suggestion))
