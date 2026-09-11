from unittest import TestCase

from ..utils.package import estimate_single_package, optimize_identical_units


class TestPackageEstimator(TestCase):
    def test_eight_identical_units_use_real_grid_optimization(self):
        package = optimize_identical_units(300, 100, 50, 8)
        self.assertEqual(
            (package["length_mm"], package["width_mm"], package["height_mm"]),
            (300.0, 200.0, 200.0),
        )
        self.assertEqual(package["capacity"], 8)

    def test_long_profiles_keep_their_long_axis_single(self):
        package = optimize_identical_units(2000, 30, 10, 10)
        self.assertEqual(package["length_mm"], 2000.0)
        self.assertEqual(package["width_mm"], 60.0)
        self.assertEqual(package["height_mm"], 50.0)

    def test_same_product_split_across_lines_is_optimized_together(self):
        package = estimate_single_package([
            {"group_key": 7, "length_mm": 300, "width_mm": 100, "height_mm": 50, "quantity": 3},
            {"group_key": 7, "length_mm": 300, "width_mm": 100, "height_mm": 50, "quantity": 5},
        ])
        self.assertEqual(package["strategy"], "identical_grid")
        self.assertEqual(package["unit_count"], 8)
        self.assertEqual(
            (package["length_mm"], package["width_mm"], package["height_mm"]),
            (300.0, 200.0, 200.0),
        )

    def test_different_products_are_combined_conservatively(self):
        package = estimate_single_package([
            {"group_key": 1, "length_mm": 300, "width_mm": 100, "height_mm": 50, "quantity": 8},
            {"group_key": 2, "length_mm": 200, "width_mm": 150, "height_mm": 100, "quantity": 1},
        ])
        self.assertEqual(package["strategy"], "mixed_conservative")
        self.assertEqual(package["group_count"], 2)
        self.assertEqual(package["unit_count"], 9)
        self.assertGreater(package["length_mm"], 0)
        self.assertGreater(package["width_mm"], 0)
        self.assertGreater(package["height_mm"], 0)
    def test_three_cubes_use_spare_cell_for_shorter_longest_side(self):
        package = optimize_identical_units(100, 100, 100, 3)
        self.assertEqual(
            (package["length_mm"], package["width_mm"], package["height_mm"]),
            (200.0, 200.0, 100.0),
        )
        self.assertEqual(package["capacity"], 4)

    def test_fractional_quantity_rounds_up_to_physical_units(self):
        package = estimate_single_package([
            {"group_key": 1, "length_mm": 100, "width_mm": 50, "height_mm": 20, "quantity": 1.01},
        ])
        self.assertEqual(package["unit_count"], 2)

    def test_negative_and_zero_quantities_are_ignored(self):
        package = estimate_single_package([
            {"group_key": 1, "length_mm": 100, "width_mm": 50, "height_mm": 20, "quantity": -2},
            {"group_key": 2, "length_mm": 100, "width_mm": 50, "height_mm": 20, "quantity": 0},
        ])
        self.assertEqual(package["strategy"], "empty")
        self.assertEqual(package["unit_count"], 0)

    def test_missing_dimension_fails_closed(self):
        with self.assertRaises(ValueError):
            estimate_single_package([
                {"group_key": 1, "length_mm": 100, "width_mm": 50, "height_mm": 0, "quantity": 1},
            ])

    def test_unhashable_group_key_is_supported_defensively(self):
        package = estimate_single_package([
            {"group_key": ["sku", 1], "length_mm": 100, "width_mm": 50, "height_mm": 20, "quantity": 2},
        ])
        self.assertEqual(package["unit_count"], 2)
        self.assertEqual(package["group_count"], 1)

