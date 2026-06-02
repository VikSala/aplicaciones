"""Tests for owa.message._chunk_text — Phase 1 outbound payload shaping."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestChunking(OwaTestCase):

    def test_short_text_one_chunk(self):
        chunks = self.Message._chunk_text('hello world', 4000, 'newline')
        self.assertEqual(chunks, ['hello world'])

    def test_empty_text_returns_one_empty(self):
        chunks = self.Message._chunk_text('', 4000, 'newline')
        self.assertEqual(chunks, [''])

    def test_length_mode_hard_split(self):
        chunks = self.Message._chunk_text('A' * 10_000, 4000, 'length')
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 4000)
        self.assertEqual(len(chunks[1]), 4000)
        self.assertEqual(len(chunks[2]), 2000)

    def test_newline_mode_paragraph_boundary(self):
        # Two paragraphs that together exceed the limit but each fits.
        body = ('A' * 3000) + '\n\n' + ('B' * 3000)
        chunks = self.Message._chunk_text(body, 4000, 'newline')
        # Should split between the two paragraphs.
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= 4000 for c in chunks))
        self.assertIn('A' * 100, chunks[0])
        self.assertIn('B' * 100, chunks[1])

    def test_newline_mode_oversized_single_line(self):
        # Single line longer than the limit should be hard-split.
        chunks = self.Message._chunk_text('X' * 10_000, 4000, 'newline')
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 4000 for c in chunks))

    def test_exactly_at_limit_one_chunk(self):
        text = 'C' * 4000
        chunks = self.Message._chunk_text(text, 4000, 'newline')
        self.assertEqual(chunks, [text])
