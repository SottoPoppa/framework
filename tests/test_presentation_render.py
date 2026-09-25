import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infrastructure.presentation.web import starlette


class PresentationRenderTests(unittest.TestCase):
	def test_url_scheme_filter_is_case_insensitive_for_attribute_names(self):
		for name in ("HREF", "Href"):
			with self.subTest(name=name):
				attributes = starlette.attrs(
					"action",
					{"attrs": {name: "javascript:alert(1)"}},
				)
				html = starlette.Adapter.node_create(
					None,
					starlette.htpy.a,
					attributes,
					["Open"],
				)

				self.assertNotIn(name, attributes)
				self.assertNotIn("javascript:", html)

		safe_attributes = starlette.attrs(
			"action",
			{"attrs": {"HREF": "https://example.test"}},
		)
		self.assertEqual(safe_attributes["HREF"], "https://example.test")
