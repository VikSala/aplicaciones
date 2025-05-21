# -*- coding: utf-8 -*-
# Copyright (c) 2019-Present Droggol Infotech Private Limited. (<https://www.droggol.com/>)

import re


class DroggolSearchTerm:

    _name = 'product.public.category'

    def __init__(self, ds_name, category_id, formulate, *args, **kwargs):
        self.ds_name = ds_name
        self.id = category_id
        self.formulate = formulate
        args = args
        kwargs = kwargs

    def __repr__(self):
        return f'{self.ds_name}({self.id}:{self.formulate})'


class CategorySearchDB:
    def __init__(self, db):
        self.db = db

    def search(self, term=None, categories_ids=False, options=None, limit=None, parts=None, match_any_word=None):
        result = []

        for category in self.db:
            if category.formulate:
                continue

            if categories_ids and category.id in categories_ids:
                result.append(category)

            if term and category.ds_name:
                re_join_str = '|' if match_any_word else '.+'
                escaped_parts = [f"({re.escape(t)})" for t in term.split(' ') if t]
                search_match = re.search(re_join_str.join(escaped_parts), category.ds_name, re.IGNORECASE)
                if search_match:
                    if parts:
                        matched_parts = [p for p in search_match.groups() if p]
                        result.append((category, matched_parts))
                    else:
                        result.append(category)
            if limit and len(result) == limit:
                break

        return result
