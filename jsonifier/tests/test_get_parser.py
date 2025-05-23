# Copyright 2017 ACSONE SA/NV
# Copyright 2022 Camptocamp SA (http://www.camptocamp.com)
# Simone Orsi <simahawk@gmail.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).


from odoo import tools
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.utils import convert_simple_to_full_parser


def jsonify_custom(self, field_name):
    return "yeah!"


class TestParser(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # disable tracking test suite wise
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env.user.tz = "Europe/Brussels"
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Akretion",
                "country_id": cls.env.ref("base.fr").id,
                "lang": "en_US",  # default
                "category_id": [(0, 0, {"name": "Inovator"})],
                "child_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Sebatien Beau",
                            "country_id": cls.env.ref("base.fr").id,
                        },
                    )
                ],
            }
        )
        Langs = cls.env["res.lang"].with_context(active_test=False)
        cls.lang = Langs.search([("code", "=", "fr_FR")])
        cls.lang.active = True
        category = cls.env["res.partner.category"].create({"name": "name"})
        cls.translated_target = f"name_{cls.lang.code}"
        category.with_context(lang=cls.lang.code).write({"name": cls.translated_target})
        cls.global_resolver = cls.env["ir.exports.resolver"].create(
            {"python_code": "value['X'] = 'X'; result = value", "type": "global"}
        )
        cls.resolver = cls.env["ir.exports.resolver"].create(
            {"python_code": "result = value + '_pidgin'", "type": "field"}
        )
        cls.category_export = cls.env["ir.exports"].create(
            {
                "global_resolver_id": cls.global_resolver.id,
                "language_agnostic": True,
                "export_fields": [
                    (0, 0, {"name": "name"}),
                    (
                        0,
                        0,
                        {
                            "name": "name",
                            "target": f"name:{cls.translated_target}",
                            "lang_id": cls.lang.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "name",
                            "target": "name:name_resolved",
                            "resolver_id": cls.resolver.id,
                        },
                    ),
                ],
            }
        )
        cls.category = category.with_context(lang=None)
        cls.category_lang = category.with_context(lang=cls.lang.code)

    def test_getting_parser(self):
        expected_parser = [
            "name",
            "active",
            "partner_latitude",
            "color",
            ("category_id", ["name"]),
            ("country_id", ["name", "code"]),
            (
                "child_ids",
                [
                    "name",
                    "id",
                    "email",
                    ("country_id", ["name", "code"]),
                    ("child_ids", ["name"]),
                ],
            ),
            "lang",
            "comment",
        ]

        exporter = self.env.ref("jsonifier.ir_exp_partner")
        parser = exporter.get_json_parser()
        expected_full_parser = convert_simple_to_full_parser(expected_parser)
        self.assertEqual(parser, expected_full_parser)

        # modify an ir.exports_line to put a target for a field
        self.env.ref("jsonifier.category_id_name").write(
            {"target": "category_id:category/name"}
        )
        expected_parser[4] = ("category_id:category", ["name"])
        parser = exporter.get_json_parser()
        expected_full_parser = convert_simple_to_full_parser(expected_parser)
        self.assertEqual(parser, expected_full_parser)

    def test_json_export(self):
        # will allow to view large dict diff in case of regression
        self.maxDiff = None
        # Enforces TZ to validate the serialization result of a Datetime
        parser = [
            "lang",
            "comment",
            "partner_latitude",
            "name",
            "color",
            (
                "child_ids:children",
                [
                    ("child_ids:children", ["name"]),
                    "email",
                    ("country_id:country", ["code", "name"]),
                    "name",
                    "id",
                ],
            ),
            ("country_id:country", ["code", "name"]),
            "active",
            ("category_id", ["name"]),
            "create_date",
        ]
        # put our own create date to ease tests
        self.env.cr.execute(
            "update res_partner set create_date=%s where id=%s",
            ("2019-10-31 14:39:49", self.partner.id),
        )
        expected_json = {
            "lang": "en_US",
            "comment": None,
            "partner_latitude": 0.0,
            "name": "Akretion",
            "color": 0,
            "country": {"code": "FR", "name": "France"},
            "active": True,
            "category_id": [{"name": "Inovator"}],
            "children": [
                {
                    "id": self.partner.child_ids.id,
                    "country": {"code": "FR", "name": "France"},
                    "children": [],
                    "name": "Sebatien Beau",
                    "email": None,
                }
            ],
            "create_date": "2019-10-31T14:39:49",
        }
        expected_json_with_fieldname = {
            "_fieldname_lang": "Language",
            "lang": "en_US",
            "_fieldname_comment": "Notes",
            "comment": None,
            "partner_latitude": 0.0,
            "_fieldname_name": "Name",
            "name": "Akretion",
            "_fieldname_color": "Color Index",
            "color": 0,
            "_fieldname_children": "Contact",
            "children": [
                {
                    "_fieldname_children": "Contact",
                    "children": [],
                    "_fieldname_email": "Email",
                    "email": None,
                    "_fieldname_country": "Country",
                    "country": {
                        "_fieldname_code": "Country Code",
                        "code": "FR",
                        "_fieldname_name": "Country Name",
                        "name": "France",
                    },
                    "_fieldname_name": "Name",
                    "name": "Sebatien Beau",
                    "_fieldname_id": "ID",
                    "id": self.partner.child_ids.id,
                }
            ],
            "_fieldname_country": "Country",
            "country": {
                "_fieldname_code": "Country Code",
                "code": "FR",
                "_fieldname_name": "Country Name",
                "name": "France",
            },
            "_fieldname_active": "Active",
            "active": True,
            "_fieldname_category_id": "Tags",
            "category_id": [{"_fieldname_name": "Name", "name": "Inovator"}],
            "_fieldname_create_date": "Created on",
            "_fieldname_partner_latitude": "Geo Latitude",
            "create_date": "2019-10-31T14:39:49",
        }
        expected_json_with_fieldname = {
            "_fieldname_lang": "Language",
            "lang": "en_US",
            "_fieldname_comment": "Notes",
            "comment": None,
            "_fieldname_partner_latitude": "Geo Latitude",
            "_fieldname_name": "Name",
            "name": "Akretion",
            "_fieldname_color": "Color Index",
            "color": 0,
            "_fieldname_children": "Contact",
            "children": [
                {
                    "_fieldname_children": "Contact",
                    "children": [],
                    "_fieldname_email": "Email",
                    "email": None,
                    "_fieldname_country": "Country",
                    "country": {
                        "_fieldname_code": "Country Code",
                        "code": "FR",
                        "_fieldname_name": "Country Name",
                        "name": "France",
                    },
                    "_fieldname_name": "Name",
                    "name": "Sebatien Beau",
                    "_fieldname_id": "ID",
                    "id": self.partner.child_ids.id,
                }
            ],
            "_fieldname_country": "Country",
            "country": {
                "_fieldname_code": "Country Code",
                "code": "FR",
                "_fieldname_name": "Country Name",
                "name": "France",
            },
            "_fieldname_active": "Active",
            "active": True,
            "_fieldname_category_id": "Tags",
            "category_id": [{"_fieldname_name": "Name", "name": "Inovator"}],
            "_fieldname_create_date": "Created on",
            "create_date": "2019-10-31T14:39:49",
            "partner_latitude": 0.0,
        }
        json_partner = self.partner.jsonify(parser)
        self.assertDictEqual(json_partner[0], expected_json)
        json_partner_with_fieldname = self.partner.jsonify(
            parser=parser, with_fieldname=True
        )
        self.assertDictEqual(
            json_partner_with_fieldname[0], expected_json_with_fieldname
        )
        # Check that only boolean fields have boolean values into json
        # By default if a field is not set into Odoo, the value is always False
        # This value is not the expected one into the json
        self.partner.write({"child_ids": [(6, 0, [])], "active": False, "lang": False})
        json_partner = self.partner.jsonify(parser)
        expected_json["active"] = False
        expected_json["lang"] = None
        expected_json["children"] = []
        self.assertDictEqual(json_partner[0], expected_json)

    def test_one(self):
        parser = [
            "name",
        ]
        expected_json = {
            "name": "Akretion",
        }
        json_partner = self.partner.jsonify(parser, one=True)
        self.assertDictEqual(json_partner, expected_json)
        # cannot call on multiple records
        with self.assertRaises(ValueError) as err:
            self.env["res.partner"].search([]).jsonify(parser, one=True)
        self.assertIn("Expected singleton", str(err.exception))

    def test_json_export_callable_parser(self):
        self.partner.__class__.jsonify_custom = jsonify_custom
        parser = [
            # callable subparser
            ("name", lambda rec, fname: rec[fname] + " rocks!"),
            ("name:custom", "jsonify_custom"),
            ("unknown_field", lambda rec, fname: "yeah again!"),
        ]
        expected_json = {
            "name": "Akretion rocks!",
            "custom": "yeah!",
            "unknown_field": "yeah again!",
        }
        json_partner = self.partner.jsonify(parser)
        self.assertDictEqual(json_partner[0], expected_json)
        del self.partner.__class__.jsonify_custom

    def test_full_parser(self):
        parser = self.category_export.get_json_parser()
        json = self.category.jsonify(parser)[0]
        json_fr = self.category_lang.jsonify(parser)[0]

        self.assertEqual(
            json, json_fr
        )  # starting from different languages should not change anything
        self.assertEqual(json[self.translated_target], self.translated_target)
        self.assertEqual(json["name_resolved"], "name_pidgin")  # field resolver
        self.assertEqual(json["X"], "X")  # added by global resolver

    def test_full_parser_resolver_json_key_override(self):
        self.resolver.write(
            {"python_code": """result = {"_json_key": "foo", "_value": record.id}"""}
        )
        parser = self.category_export.get_json_parser()
        json = self.category.jsonify(parser)[0]
        self.assertNotIn("name_resolved", json)
        self.assertEqual(json["foo"], self.category.id)  # field resolver
        self.assertEqual(json["X"], "X")  # added by global resolver

    def test_simple_parser_translations(self):
        """The simple parser result should depend on the context language."""
        parser = ["name"]
        json = self.category.jsonify(parser)[0]
        json_fr = self.category_lang.jsonify(parser)[0]

        self.assertEqual(json["name"], "name")
        self.assertEqual(json_fr["name"], self.translated_target)

    def test_simple_star_target_and_field_resolver(self):
        """The simple parser result should depend on the context language."""
        code = (
            "is_number = field_type in ('integer', 'float');"
            "ftype = 'NUMBER' if is_number else 'TEXT';"
            "value = value if is_number else str(value);"
            "result = {'Key': name, 'Value': value, 'Type': ftype, 'IsPublic': True}"
        )
        resolver = self.env["ir.exports.resolver"].create({"python_code": code})
        lang_parser = [
            {"target": "customTags=list", "name": "name", "resolver": resolver},
            {"target": "customTags=list", "name": "id", "resolver": resolver},
        ]
        parser = {"language_agnostic": True, "langs": {False: lang_parser}}
        expected_json = {
            "customTags": [
                {"Value": "name", "Key": "name", "Type": "TEXT", "IsPublic": True},
                {
                    "Value": self.category.id,
                    "Key": "id",
                    "Type": "NUMBER",
                    "IsPublic": True,
                },
            ]
        }

        json = self.category.jsonify(parser)[0]
        self.assertEqual(json, expected_json)

    def test_simple_export_with_function(self):
        self.category.__class__.jsonify_custom = jsonify_custom
        export = self.env["ir.exports"].create(
            {
                "export_fields": [
                    (0, 0, {"name": "name", "instance_method_name": "jsonify_custom"}),
                ],
            }
        )

        json = self.category.jsonify(export.get_json_parser())[0]
        self.assertEqual(json, {"name": "yeah!"})

    def test_export_relational_display_names(self):
        """If we export a relational, we get its display_name in the json."""
        parser = [
            "state_id",
            "country_id",
            "category_id",
            "user_ids",
        ]
        expected_json = {
            "state_id": None,
            "country_id": "France",
            "category_id": ["Inovator"],
            "user_ids": [],
        }

        json_partner = self.partner.jsonify(parser, one=True)

        self.assertDictEqual(json_partner, expected_json)

    def test_export_reference_display_names(self):
        """Reference work the same as relational"""
        menu = self.env.ref("base.menu_action_res_users")

        json_menu = menu.jsonify(["action"], one=True)

        self.assertDictEqual(json_menu, {"action": "Users"})

    def test_bad_parsers_strict(self):
        rec = self.category.with_context(jsonify_record_strict=True)
        bad_field_name = ["Name"]
        with self.assertRaises(KeyError):
            rec.jsonify(bad_field_name, one=True)

        bad_function_name = {"fields": [{"name": "name", "function": "notafunction"}]}
        with self.assertRaises(UserError):
            rec.jsonify(bad_function_name, one=True)

        bad_subparser = {"fields": [({"name": "name"}, [{"name": "subparser_name"}])]}
        with self.assertRaises(UserError):
            rec.jsonify(bad_subparser, one=True)

    def test_bad_parsers_fail_gracefully(self):
        rec = self.category

        # logging is disabled when testing as it makes too much noise
        tools.config["test_enable"] = False

        logger_name = "odoo.addons.jsonifier.models.models"
        bad_field_name = ["Name"]
        with self.assertLogs(logger=logger_name, level="WARNING") as capt:
            rec.jsonify(bad_field_name, one=True)
            self.assertIn("res.partner.category.Name not availabl", capt.output[0])

        bad_function_name = {"fields": [{"name": "name", "function": "notafunction"}]}
        with self.assertLogs(logger=logger_name, level="WARNING") as capt:
            rec.jsonify(bad_function_name, one=True)
            self.assertIn(
                "res.partner.category.notafunction not available", capt.output[0]
            )

        bad_subparser = {"fields": [({"name": "name"}, [{"name": "subparser_name"}])]}
        with self.assertLogs(logger=logger_name, level="WARNING") as capt:
            rec.jsonify(bad_subparser, one=True)
            self.assertIn("res.partner.category.name not relational", capt.output[0])

        tools.config["test_enable"] = True
