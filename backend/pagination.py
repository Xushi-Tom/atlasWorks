#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_pagination_args(args, default_page_size=20, max_page_size=100):
    raw_page = args.get("page", 1)
    raw_page_size = args.get("pageSize")
    raw_limit = args.get("limit")

    if raw_page_size in {None, ""} and raw_limit not in {None, ""}:
        raw_page_size = raw_limit
        raw_page = 1

    page = max(1, _safe_int(raw_page, 1))
    page_size = max(1, min(_safe_int(raw_page_size, default_page_size), max_page_size))
    return page, page_size


def paginate_items(items, page, page_size):
    normalized_items = list(items or [])
    total = len(normalized_items)
    total_pages = math.ceil(total / page_size) if total else 0
    current_page = min(max(1, page), total_pages or 1)
    start = (current_page - 1) * page_size
    end = start + page_size
    paged_items = normalized_items[start:end]

    return paged_items, {
        "count": len(paged_items),
        "total": total,
        "page": current_page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "hasPrev": current_page > 1 and total > 0,
        "hasNext": current_page < total_pages,
    }
