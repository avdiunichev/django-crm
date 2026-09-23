from django.test import SimpleTestCase

from .addressing import AddressFormatter as F


class AddressFormatterTests(SimpleTestCase):
    def test_address_variants(self):
        region = {"region": "Свердловская", "region_type": "обл"}
        city = {**region, "city": "Екатеринбург", "city_type": "г"}
        village = {**region, "area": "Белоярский", "area_type": "р-н",
                   "settlement": "Белоярский", "settlement_type": "рп"}
        street = {**city, "street": "Центральная", "street_type": "ул",
                  "house": "25", "house_type": "д"}
        cases = [
            (city, "Свердловская обл., г. Екатеринбург"),
            (village, "Свердловская обл., Белоярский р-н, рп. Белоярский"),
            (street, "Свердловская обл., г. Екатеринбург, ул. Центральная, д. 25"),
            ({**street, "block": "3", "block_type": "корпус"},
             "Свердловская обл., г. Екатеринбург, ул. Центральная, д. 25, корп. 3"),
            ({**street, "block": "5", "block_type": "стр"},
             "Свердловская обл., г. Екатеринбург, ул. Центральная, д. 25, стр. 5"),
            ({**city, "house": "8", "house_type": "влд"},
             "Свердловская обл., г. Екатеринбург, влд. 8"),
            ({**region, "planning_structure": "Северная промзона", "planning_structure_type": "тер"},
             "Свердловская обл., тер. Северная промзона"),
            ({**region, "settlement": "Ромашка", "settlement_type": "СНТ", "stead": "25"},
             "Свердловская обл., СНТ Ромашка, уч. 25"),
            ({**region, "area": "Белоярский", "area_type": "р-н",
              "territory": "Автодорога Екатеринбург-Тюмень", "territory_type": "тер",
              "kilometer": "28", "house": "5", "house_type": "стр"},
             "Свердловская обл., Белоярский р-н, тер. Автодорога Екатеринбург-Тюмень, 28-й км, стр. 5"),
            ({"region": "Ленинградская", "region_type": "обл", "settlement": "Новосаратовка",
              "settlement_type": "д", "house": "15", "house_type": "д"},
             "Ленинградская обл., д. Новосаратовка, д. 15"),
            ({"region": "Татарстан", "region_type": "Респ"}, "Респ. Татарстан"),
            ({"region": "Краснодарский", "region_type": "край"}, "Краснодарский край"),
            ({"street": "28-й км автодороги", "street_type": "тер"}, "тер. 28-й км автодороги"),
            ({"street": "Невский", "street_type": "пр-кт"}, "пр-кт Невский"),
            ({"region": "Еврейская", "region_type": "Аобл"}, "Еврейская АО"),
            ({**street, "block": "3", "block_type": "корп", "building": "2",
              "structure": "7", "letter": "А", "flat": "10", "flat_type": "оф"},
             "Свердловская обл., г. Екатеринбург, ул. Центральная, д. 25, корп. 3, стр. 2, соор. 7, лит. А, оф. 10"),
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(F.format(data), expected)

    def test_federal_cities_are_not_duplicated(self):
        for name in ("Москва", "Санкт-Петербург", "Севастополь"):
            self.assertEqual(F.format({
                "region": name, "region_type": "г", "city": name, "city_type": "г",
                "street": "Савушкина", "street_type": "ул", "house": "10", "house_type": "д",
            }), f"г. {name}, ул. Савушкина, д. 10")

    def test_declared_types_are_not_duplicated(self):
        self.assertEqual(F.format({
            "city": "город Екатеринбург", "city_type": "г",
            "street": "улица Ленина", "street_type": "ул",
            "house": "дом 15", "house_type": "д",
        }), "г. Екатеринбург, ул. Ленина, д. 15")
        self.assertEqual(F.format({"street": "ул. улица Ленина", "street_type": "ул"}), "ул. Ленина")

    def test_incomplete_structure_does_not_discard_original_address(self):
        source = {"value": "г Москва, ул Тверская, д 1",
                  "data": {"city_with_type": "г Москва"}}
        self.assertEqual(F.format(source), source["value"])

    def test_original_payload_and_unknown_types_are_preserved(self):
        original = {"value": "неизвестный тип Объект", "data": {
            "street": "Объект", "street_type": "неизвестный тип",
            "fias_id": "fias", "kladr_id": "kladr", "geo_lat": "55.5", "geo_lon": "37.6",
            "future_field": {"value": "Не терять"},
        }}
        snapshot = F.snapshot({"raw_data": original})
        self.assertEqual(snapshot, original)
        self.assertEqual(F.format(snapshot), "неизвестный тип Объект")
        snapshot["data"]["future_field"]["value"] = "Изменено"
        self.assertEqual(original["data"]["future_field"]["value"], "Не терять")
        self.assertEqual(F.format({}, "Адрес из старой базы"), "Адрес из старой базы")

    def test_short_road_address(self):
        self.assertEqual(F.short({"area": "Белоярский", "area_type": "р-н", "kilometer": "28"}),
                         "Белоярский р-н, 28-й км")
