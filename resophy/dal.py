"""
Data Access Layer (DAL) for Resophy multi-user MySQL storage.

Every public function takes ``user_id`` as its first argument so that
callers can isolate data per-user.  All database access goes through the
``get_db()`` connection pool defined in ``resophy.db``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from resophy.db import get_db

# Virtual user_id for the global team library (JLU-MCNS-MEC)
GLOBAL_LIBRARY_USER_ID = 0


# ===================================================================
# 1. User Settings
# ===================================================================

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "heatmap_color_scheme": "green",
    "ai_language": "zh",
    "onboarding_done": False,
    "llm_model": "gemini-2.5-flash",
    "llm_base_url": "https://hiapi.online/v1",
    "llm_api_key": None,
    "mineru_server_url": None,
    "mineru_use_api": True,
    "mineru_api_token": None,
    "daily_arxiv_settings": None,
}


def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Return the merged settings dict for *user_id* (defaults filled in)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_settings WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()

    result = dict(_DEFAULT_SETTINGS)
    if row:
        for key in result:
            if key in row and row[key] is not None:
                result[key] = row[key]
        # Parse JSON column
        if row.get("daily_arxiv_settings"):
            if isinstance(row["daily_arxiv_settings"], str):
                result["daily_arxiv_settings"] = json.loads(row["daily_arxiv_settings"])
            else:
                result["daily_arxiv_settings"] = row["daily_arxiv_settings"]
    return result


def save_user_settings(user_id: int, data: Dict[str, Any]) -> None:
    """Upsert user settings.  Only supplied keys are updated."""
    # Map incoming keys to DB columns
    columns = {
        "heatmap_color_scheme": data.get("heatmap_color_scheme") or data.get("heatmapColorScheme"),
        "ai_language": data.get("ai_language") or data.get("aiLanguage"),
        "onboarding_done": data.get("onboarding_done") or data.get("onboardingDontShow"),
        "llm_model": data.get("llm_model") or data.get("llmModel"),
        "llm_base_url": data.get("llm_base_url") or data.get("llmBaseUrl"),
        "llm_api_key": data.get("llm_api_key") or data.get("llmApiKey"),
        "mineru_server_url": data.get("mineru_server_url") or data.get("mineruServerUrl"),
        "mineru_use_api": data.get("mineru_use_api") if data.get("mineru_use_api") is not None else data.get("mineruUseApi"),
        "mineru_api_token": data.get("mineru_api_token") or data.get("mineruApiToken"),
        "daily_arxiv_settings": data.get("daily_arxiv_settings"),
    }

    # Remove None values (only update what's provided)
    columns = {k: v for k, v in columns.items() if v is not None}

    # Serialize JSON column
    if "daily_arxiv_settings" in columns and not isinstance(columns["daily_arxiv_settings"], str):
        columns["daily_arxiv_settings"] = json.dumps(columns["daily_arxiv_settings"], ensure_ascii=False)

    # Convert bool to int for MySQL TINYINT
    for key in ("onboarding_done", "mineru_use_api"):
        if key in columns:
            columns[key] = int(bool(columns[key]))

    if not columns:
        return

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if row exists
            cur.execute("SELECT user_id FROM user_settings WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()

            if exists:
                set_clause = ", ".join(f"{k} = %s" for k in columns)
                values = list(columns.values()) + [user_id]
                cur.execute(f"UPDATE user_settings SET {set_clause} WHERE user_id = %s", values)
            else:
                columns["user_id"] = user_id
                cols = ", ".join(columns.keys())
                placeholders = ", ".join(["%s"] * len(columns))
                cur.execute(f"INSERT INTO user_settings ({cols}) VALUES ({placeholders})", list(columns.values()))
        conn.commit()


# ===================================================================
# 2. Reading History
# ===================================================================

def get_reading_history(user_id: int) -> Dict[str, Any]:
    """Return reading history as ``{date_str: {total: minutes, papers: [ids]}}``."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, total_minutes, paper_ids "
                "FROM user_reading_history WHERE user_id = %s "
                "ORDER BY date",
                (user_id,),
            )
            rows = cur.fetchall()

    result = {}
    for row in rows:
        d = row["date"]
        date_str = d.strftime("%Y-%m-%d") if isinstance(d, (date, datetime)) else str(d)
        paper_ids = row["paper_ids"]
        if isinstance(paper_ids, str):
            paper_ids = json.loads(paper_ids)
        result[date_str] = {
            "total": row["total_minutes"],
            "papers": paper_ids or [],
        }
    return result


def record_reading(user_id: int, date_str: str, minutes: int, paper_id: Optional[str] = None) -> int:
    """
    Add *minutes* to the reading record for *date_str*.

    Returns the new total for that day.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT total_minutes, paper_ids "
                "FROM user_reading_history "
                "WHERE user_id = %s AND date = %s",
                (user_id, date_str),
            )
            row = cur.fetchone()

            if row:
                new_total = row["total_minutes"] + minutes
                paper_ids = row["paper_ids"]
                if isinstance(paper_ids, str):
                    paper_ids = json.loads(paper_ids)
                paper_ids = paper_ids or []
                if paper_id and paper_id not in paper_ids:
                    paper_ids.append(paper_id)
                cur.execute(
                    "UPDATE user_reading_history "
                    "SET total_minutes = %s, paper_ids = %s "
                    "WHERE user_id = %s AND date = %s",
                    (new_total, json.dumps(paper_ids), user_id, date_str),
                )
            else:
                new_total = minutes
                paper_ids = [paper_id] if paper_id else []
                cur.execute(
                    "INSERT INTO user_reading_history (user_id, date, total_minutes, paper_ids) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, date_str, new_total, json.dumps(paper_ids)),
                )
        conn.commit()
    return new_total


def clear_reading_history(user_id: int) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_reading_history WHERE user_id = %s", (user_id,))
        conn.commit()


def get_week_paper_ids(user_id: int) -> List[str]:
    """Return paper IDs read this week (Monday–today)."""
    from datetime import timedelta

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT paper_ids FROM user_reading_history "
                "WHERE user_id = %s AND date BETWEEN %s AND %s",
                (user_id, monday, today),
            )
            rows = cur.fetchall()

    ids: set[str] = set()
    for row in rows:
        paper_ids = row["paper_ids"]
        if isinstance(paper_ids, str):
            paper_ids = json.loads(paper_ids)
        if paper_ids:
            ids.update(paper_ids)
    return list(ids)


# ===================================================================
# 3. Reading List
# ===================================================================

def get_reading_list(user_id: int) -> List[str]:
    """Return the ordered list of paper_ids in the user's reading list."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT paper_id FROM user_reading_list "
                "WHERE user_id = %s ORDER BY added_at",
                (user_id,),
            )
            rows = cur.fetchall()
    return [r["paper_id"] for r in rows]


def add_to_reading_list(user_id: int, paper_id: str) -> bool:
    """Add a paper to the reading list.  Returns True if inserted."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO user_reading_list (user_id, paper_id) VALUES (%s, %s)",
                (user_id, paper_id),
            )
        conn.commit()
    return True


def remove_from_reading_list(user_id: int, paper_id: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_reading_list WHERE user_id = %s AND paper_id = %s",
                (user_id, paper_id),
            )
        conn.commit()
    return True


# ===================================================================
# 4. User Categories (adjacency list → tree)
# ===================================================================

def get_categories_tree(user_id: int) -> Dict[str, Any]:
    """
    Build the category tree for a user from the flat ``user_categories`` table.

    Returns the same ``{id, name, children: [...]}`` structure as the
    legacy ``categories.json``.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, parent_id, name, sort_order, pinned, icon_color "
                "FROM user_categories WHERE user_id = %s "
                "ORDER BY sort_order, created_at",
                (user_id,),
            )
            rows = cur.fetchall()

    # Build lookup
    nodes: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        node: Dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "children": [],
            "_parent_id": row["parent_id"],
        }
        if row.get("pinned"):
            node["pinned"] = True
        if row.get("icon_color"):
            node["iconColor"] = row["icon_color"]
        nodes[row["id"]] = node

    root: Dict[str, Any] = {"id": "root", "name": "Root", "children": []}

    for node in nodes.values():
        parent_id = node.pop("_parent_id")
        if parent_id is None:
            root["children"].append(node)
        elif parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            # Orphaned node, attach to root
            root["children"].append(node)

    return root


def create_category(user_id: int, name: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
    """Insert a new category and return its ``{id, name, children: []}`` dict."""
    cat_id = str(uuid.uuid4())

    # Determine sort_order (append at end)
    with get_db() as conn:
        with conn.cursor() as cur:
            if parent_id:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
                    "FROM user_categories WHERE user_id = %s AND parent_id = %s",
                    (user_id, parent_id),
                )
            else:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
                    "FROM user_categories WHERE user_id = %s AND parent_id IS NULL",
                    (user_id,),
                )
            order_row = cur.fetchone()
            sort_order = order_row["next_order"] if order_row else 0

            cur.execute(
                "INSERT INTO user_categories (id, user_id, parent_id, name, sort_order) "
                "VALUES (%s, %s, %s, %s, %s)",
                (cat_id, user_id, parent_id or None, name, sort_order),
            )
        conn.commit()

    return {"id": cat_id, "name": name, "children": []}


def rename_category(user_id: int, category_id: str, new_name: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_categories SET name = %s "
                "WHERE id = %s AND user_id = %s",
                (new_name, category_id, user_id),
            )
        conn.commit()
        return cur.rowcount > 0


def delete_category(user_id: int, category_id: str) -> List[str]:
    """
    Delete a category and all its descendants.

    Returns the list of all deleted category IDs (for paper cleanup).
    """
    deleted_ids: List[str] = []

    def _collect_ids(cid: str) -> None:
        deleted_ids.append(cid)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM user_categories WHERE parent_id = %s AND user_id = %s",
                    (cid, user_id),
                )
                children = cur.fetchall()
        for child in children:
            _collect_ids(child["id"])

    _collect_ids(category_id)

    if deleted_ids:
        with get_db() as conn:
            with conn.cursor() as cur:
                placeholders = ", ".join(["%s"] * len(deleted_ids))
                cur.execute(
                    f"DELETE FROM user_categories WHERE id IN ({placeholders}) AND user_id = %s",
                    deleted_ids + [user_id],
                )
            conn.commit()

    return deleted_ids


def move_category(user_id: int, category_id: str, target_parent_id: Optional[str]) -> bool:
    """Move a category to a new parent (None = root level)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get new sort_order (append at end of new parent's children)
            if target_parent_id:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
                    "FROM user_categories WHERE user_id = %s AND parent_id = %s",
                    (user_id, target_parent_id),
                )
            else:
                cur.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
                    "FROM user_categories WHERE user_id = %s AND parent_id IS NULL",
                    (user_id,),
                )
            order_row = cur.fetchone()
            sort_order = order_row["next_order"] if order_row else 0

            cur.execute(
                "UPDATE user_categories SET parent_id = %s, sort_order = %s "
                "WHERE id = %s AND user_id = %s",
                (target_parent_id or None, sort_order, category_id, user_id),
            )
        conn.commit()
        return cur.rowcount > 0


def get_category_path_db(user_id: int, category_id: str) -> Optional[List[str]]:
    """
    Build the path from root to *category_id* as ``["Root", "Parent", "Child"]``.

    Returns None if the category doesn't exist.
    """
    path_parts: List[str] = []
    current_id: Optional[str] = category_id

    with get_db() as conn:
        with conn.cursor() as cur:
            while current_id:
                cur.execute(
                    "SELECT id, parent_id, name FROM user_categories "
                    "WHERE id = %s AND user_id = %s",
                    (current_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    break
                path_parts.insert(0, row["name"])
                current_id = row["parent_id"]

    if not path_parts:
        return None

    return ["Root"] + path_parts


def find_category_node_db(user_id: int, category_id: str) -> Optional[Dict[str, Any]]:
    """Check if a category exists for the user."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, parent_id FROM user_categories "
                "WHERE id = %s AND user_id = %s",
                (category_id, user_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"]}


def is_descendant_of(user_id: int, ancestor_id: str, target_id: str) -> bool:
    """Check if *target_id* is a descendant of *ancestor_id*."""
    current = target_id
    with get_db() as conn:
        with conn.cursor() as cur:
            visited = set()
            while current:
                if current in visited:
                    break
                visited.add(current)
                cur.execute(
                    "SELECT parent_id FROM user_categories WHERE id = %s AND user_id = %s",
                    (current, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return False
                if row["parent_id"] == ancestor_id:
                    return True
                current = row["parent_id"]
    return False


def pin_category(user_id: int, category_id: str, pinned: bool) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_categories SET pinned = %s "
                "WHERE id = %s AND user_id = %s",
                (int(pinned), category_id, user_id),
            )
        conn.commit()
        return cur.rowcount > 0


def set_category_color(user_id: int, category_id: str, color: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_categories SET icon_color = %s "
                "WHERE id = %s AND user_id = %s",
                (color, category_id, user_id),
            )
        conn.commit()
        return cur.rowcount > 0


# ===================================================================
# 5. Papers (Shared Layer)
# ===================================================================

# Columns in the papers table that can be set on insert/update
_PAPERS_COLUMNS = {
    "content_hash", "arxiv_id", "title", "authors", "abstract", "year",
    "journal", "affiliation", "keywords", "subject", "summary", "bibtex",
    "pdf_storage_path", "original_filename", "chinese_pdf_path",
    "analysis_result_path", "arxiv_url", "arxiv_published_date",
    "github", "homepage", "translation_status", "translation_task_id",
    "analysis_status", "analysis_task_id", "status_updated_at", "uploaded_by",
}

# camelCase → snake_case mapping for frontend-originated keys
_PAPER_KEY_MAP: Dict[str, str] = {
    "contentHash": "content_hash",
    "arxivId": "arxiv_id",
    "pdfStoragePath": "pdf_storage_path",
    "originalFilename": "original_filename",
    "chinesePdfPath": "chinese_pdf_path",
    "analysisResultPath": "analysis_result_path",
    "arxivUrl": "arxiv_url",
    "arxivPublishedDate": "arxiv_published_date",
    "translationStatus": "translation_status",
    "translationTaskId": "translation_task_id",
    "analysisStatus": "analysis_status",
    "analysisTaskId": "analysis_task_id",
    "statusUpdatedAt": "status_updated_at",
    "uploadedBy": "uploaded_by",
    "filePath": "pdf_storage_path",
    "file_path": "pdf_storage_path",
}


def _normalize_paper_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """Map camelCase / legacy keys to DB column names, filter unknowns."""
    result: Dict[str, Any] = {}
    for k, v in data.items():
        col = _PAPER_KEY_MAP.get(k, k)
        if col in _PAPERS_COLUMNS:
            result[col] = v
    return result


def find_paper_by_hash(content_hash: str) -> Optional[Dict[str, Any]]:
    """Find a paper by its content hash (for dedup on upload)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM papers WHERE content_hash = %s",
                (content_hash,),
            )
            return cur.fetchone()


def find_paper_by_arxiv_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """Find a paper by arXiv ID (for dedup on arXiv import)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM papers WHERE arxiv_id = %s LIMIT 1",
                (arxiv_id,),
            )
            return cur.fetchone()


def get_paper(paper_id: str) -> Optional[Dict[str, Any]]:
    """Get a shared paper row by ID."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM papers WHERE id = %s", (paper_id,))
            return cur.fetchone()


def insert_paper(paper_id: str, data: Dict[str, Any]) -> str:
    """
    Insert a new paper into the shared papers table.

    Returns the paper_id.  If a paper with the same content_hash already
    exists, returns the existing paper's ID instead (dedup).
    """
    # Check for dedup by content_hash
    content_hash = data.get("content_hash") or data.get("contentHash")
    if content_hash:
        existing = find_paper_by_hash(content_hash)
        if existing:
            return existing["id"]

    cols = _normalize_paper_keys(data)
    cols["id"] = paper_id

    with get_db() as conn:
        with conn.cursor() as cur:
            col_names = ", ".join(cols.keys())
            placeholders = ", ".join(["%s"] * len(cols))
            cur.execute(
                f"INSERT INTO papers ({col_names}) VALUES ({placeholders})",
                list(cols.values()),
            )
        conn.commit()
    return paper_id


def update_paper_shared(paper_id: str, data: Dict[str, Any]) -> bool:
    """
    Update shared paper fields (title, abstract, task status, etc.).

    Only known columns are updated; unknown keys are silently ignored.
    """
    cols = _normalize_paper_keys(data)
    if not cols:
        return False

    with get_db() as conn:
        with conn.cursor() as cur:
            set_clause = ", ".join(f"{k} = %s" for k in cols)
            values = list(cols.values()) + [paper_id]
            cur.execute(
                f"UPDATE papers SET {set_clause} WHERE id = %s", values
            )
        conn.commit()
        return cur.rowcount > 0


def delete_paper(paper_id: str) -> bool:
    """Delete a paper from the shared table (cascades to user_papers)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM papers WHERE id = %s", (paper_id,))
        conn.commit()
        return cur.rowcount > 0


# ===================================================================
# 6. User Papers (Per-User Layer)
# ===================================================================

_USER_PAPERS_COLUMNS = {
    "category_id", "notes", "starred", "read_time",
    "analysis_view_time", "upload_source", "use_chinese_version",
}


def link_user_paper(
    user_id: int,
    paper_id: str,
    *,
    category_id: Optional[str] = None,
    upload_source: Optional[str] = None,
) -> bool:
    """
    Create a user ↔ paper association.

    Uses INSERT IGNORE so linking the same paper twice is a no-op.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO user_papers "
                "(user_id, paper_id, category_id, upload_source) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, paper_id, category_id, upload_source),
            )
        conn.commit()
    return True


def get_user_paper(user_id: int, paper_id: str) -> Optional[Dict[str, Any]]:
    """Get the user-specific metadata for a paper (joined with shared data)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.*, "
                "up.category_id, up.notes, up.starred, "
                "up.read_time AS user_read_time, "
                "up.analysis_view_time AS user_analysis_view_time, "
                "up.upload_source, up.use_chinese_version, "
                "up.added_at AS user_added_at "
                "FROM papers p "
                "JOIN user_papers up ON p.id = up.paper_id "
                "WHERE up.user_id = %s AND up.paper_id = %s",
                (user_id, paper_id),
            )
            return cur.fetchone()


def get_user_papers(
    user_id: int,
    *,
    category_id: Optional[str] = None,
    starred_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    Get all papers associated with a user.

    Optionally filter by category or starred status.
    """
    query = (
        "SELECT p.*, "
        "up.category_id, up.notes, up.starred, "
        "up.read_time AS user_read_time, "
        "up.analysis_view_time AS user_analysis_view_time, "
        "up.upload_source, up.use_chinese_version, "
        "up.added_at AS user_added_at "
        "FROM papers p "
        "JOIN user_papers up ON p.id = up.paper_id "
        "WHERE up.user_id = %s"
    )
    params: list = [user_id]

    if category_id is not None:
        query += " AND up.category_id = %s"
        params.append(category_id)

    if starred_only:
        query += " AND up.starred = 1"

    query += " ORDER BY up.added_at DESC"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def update_user_paper(user_id: int, paper_id: str, data: Dict[str, Any]) -> bool:
    """
    Update per-user fields for a paper.

    Accepts both camelCase and snake_case keys:
    - notes, starred, category_id, read_time, analysis_view_time,
      upload_source, use_chinese_version
    """
    # Map camelCase to snake_case
    key_map = {
        "categoryId": "category_id",
        "readTime": "read_time",
        "analysisViewTime": "analysis_view_time",
        "uploadSource": "upload_source",
        "useChinese": "use_chinese_version",
        "useChineseVersion": "use_chinese_version",
    }

    cols: Dict[str, Any] = {}
    for k, v in data.items():
        col = key_map.get(k, k)
        if col in _USER_PAPERS_COLUMNS:
            cols[col] = v

    # Convert booleans to int for MySQL TINYINT
    for key in ("starred", "use_chinese_version"):
        if key in cols:
            cols[key] = int(bool(cols[key]))

    if not cols:
        return False

    with get_db() as conn:
        with conn.cursor() as cur:
            set_clause = ", ".join(f"{k} = %s" for k in cols)
            values = list(cols.values()) + [user_id, paper_id]
            cur.execute(
                f"UPDATE user_papers SET {set_clause} "
                f"WHERE user_id = %s AND paper_id = %s",
                values,
            )
        conn.commit()
        return cur.rowcount > 0


def increment_user_paper_time(
    user_id: int, paper_id: str, field: str, seconds: int
) -> int:
    """
    Atomically increment read_time or analysis_view_time.

    Returns the new total.
    """
    if field not in ("read_time", "analysis_view_time"):
        raise ValueError(f"Invalid field: {field}")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE user_papers SET {field} = {field} + %s "
                f"WHERE user_id = %s AND paper_id = %s",
                (seconds, user_id, paper_id),
            )
            cur.execute(
                f"SELECT {field} FROM user_papers "
                f"WHERE user_id = %s AND paper_id = %s",
                (user_id, paper_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row[field] if row else 0


def unlink_user_paper(user_id: int, paper_id: str) -> bool:
    """Remove a user's association with a paper."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_papers "
                "WHERE user_id = %s AND paper_id = %s",
                (user_id, paper_id),
            )
        conn.commit()
        return cur.rowcount > 0


def count_paper_users(paper_id: str) -> int:
    """Count how many users have this paper (for orphan cleanup)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM user_papers WHERE paper_id = %s",
                (paper_id,),
            )
            row = cur.fetchone()
    return row["cnt"] if row else 0


def search_papers_db(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Full-text search on the shared papers table using MySQL ngram FT index.

    Returns matching paper rows sorted by relevance.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT *, MATCH(title, authors, abstract) AGAINST (%s) AS score "
                "FROM papers "
                "WHERE MATCH(title, authors, abstract) AGAINST (%s) "
                "ORDER BY score DESC LIMIT %s",
                (query, query, limit),
            )
            return cur.fetchall()


# ===================================================================
# 7. Shared Categories
# ===================================================================

def share_category(
    owner_id: int,
    category_id: str,
    shared_with_id: int,
    permission: str = "view",
) -> bool:
    """
    UPSERT a sharing record.  If already shared, update the permission.

    Returns True on success.
    """
    if permission not in ("view", "edit"):
        raise ValueError(f"Invalid permission: {permission}")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO shared_categories "
                "(category_id, owner_id, shared_with, permission) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE permission = VALUES(permission)",
                (category_id, owner_id, shared_with_id, permission),
            )
        conn.commit()
    return True


def unshare_category(owner_id: int, category_id: str, shared_with_id: int) -> bool:
    """Remove a sharing record.  Returns True if a row was deleted."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM shared_categories "
                "WHERE category_id = %s AND owner_id = %s AND shared_with = %s",
                (category_id, owner_id, shared_with_id),
            )
        conn.commit()
        return cur.rowcount > 0


def get_shared_categories_for_user(user_id: int) -> List[Dict[str, Any]]:
    """
    Return categories that others have shared with *user_id*.

    Each row includes the category info, owner info, and permission.
    """
    from resophy.db import get_flarum_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sc.id AS share_id, sc.category_id, sc.owner_id, "
                "sc.permission, sc.created_at AS shared_at, "
                "uc.name AS category_name, uc.parent_id, uc.icon_color "
                "FROM shared_categories sc "
                "JOIN user_categories uc ON sc.category_id = uc.id "
                "WHERE sc.shared_with = %s "
                "ORDER BY sc.owner_id, uc.name",
                (user_id,),
            )
            rows = cur.fetchall()

    if not rows:
        return []

    # Fetch owner display names from Flarum
    owner_ids = list({r["owner_id"] for r in rows})
    owner_names: Dict[int, str] = {}
    try:
        with get_flarum_db() as fconn:
            with fconn.cursor() as fcur:
                placeholders = ", ".join(["%s"] * len(owner_ids))
                fcur.execute(
                    f"SELECT id, username, nickname FROM users "
                    f"WHERE id IN ({placeholders})",
                    owner_ids,
                )
                for u in fcur.fetchall():
                    owner_names[u["id"]] = u.get("nickname") or u["username"]
    except Exception:
        for oid in owner_ids:
            owner_names.setdefault(oid, f"User#{oid}")

    for row in rows:
        row["owner_name"] = owner_names.get(row["owner_id"], f"User#{row['owner_id']}")

    return rows


def get_shared_category_tree(owner_id: int, category_id: str) -> Dict[str, Any]:
    """
    Build the subtree rooted at *category_id* from *owner_id*'s categories.

    Same structure as ``get_categories_tree`` but scoped to one subtree.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all categories of the owner
            cur.execute(
                "SELECT id, parent_id, name, sort_order, pinned, icon_color "
                "FROM user_categories WHERE user_id = %s "
                "ORDER BY sort_order, created_at",
                (owner_id,),
            )
            all_rows = cur.fetchall()

    # Build lookup
    nodes: Dict[str, Dict[str, Any]] = {}
    for row in all_rows:
        node: Dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "children": [],
            "_parent_id": row["parent_id"],
        }
        if row.get("icon_color"):
            node["iconColor"] = row["icon_color"]
        nodes[row["id"]] = node

    if category_id not in nodes:
        return {"id": category_id, "name": "Unknown", "children": []}

    # Build parent→children relationships
    for node in nodes.values():
        parent_id = node.pop("_parent_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)

    return nodes[category_id]


def get_share_permission(
    user_id: int, category_id: str
) -> Optional[str]:
    """
    Check whether *user_id* has access to *category_id* via sharing.

    Walks up the ancestor chain: if any ancestor is shared, returns
    the permission ('view' or 'edit').  Returns None if not shared.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            current_id: Optional[str] = category_id
            visited: set[str] = set()

            while current_id and current_id not in visited:
                visited.add(current_id)

                # Check if this category is directly shared
                cur.execute(
                    "SELECT permission FROM shared_categories "
                    "WHERE category_id = %s AND shared_with = %s",
                    (current_id, user_id),
                )
                row = cur.fetchone()
                if row:
                    return row["permission"]

                # Walk up to parent
                cur.execute(
                    "SELECT parent_id FROM user_categories WHERE id = %s",
                    (current_id,),
                )
                parent_row = cur.fetchone()
                current_id = parent_row["parent_id"] if parent_row else None

    return None


def get_category_shares(
    owner_id: int, category_id: str
) -> List[Dict[str, Any]]:
    """Return the list of users a category is shared with + their permissions."""
    from resophy.db import get_flarum_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, shared_with, permission, created_at "
                "FROM shared_categories "
                "WHERE category_id = %s AND owner_id = %s",
                (category_id, owner_id),
            )
            rows = cur.fetchall()

    if not rows:
        return []

    # Fetch user names from Flarum
    user_ids = [r["shared_with"] for r in rows]
    user_names: Dict[int, str] = {}
    try:
        with get_flarum_db() as fconn:
            with fconn.cursor() as fcur:
                placeholders = ", ".join(["%s"] * len(user_ids))
                fcur.execute(
                    f"SELECT id, username, nickname FROM users "
                    f"WHERE id IN ({placeholders})",
                    user_ids,
                )
                for u in fcur.fetchall():
                    user_names[u["id"]] = u.get("nickname") or u["username"]
    except Exception:
        pass

    for row in rows:
        row["username"] = user_names.get(row["shared_with"], f"User#{row['shared_with']}")

    return rows


def search_flarum_users(
    search: str, exclude_user_id: Optional[int] = None, limit: int = 10
) -> List[Dict[str, Any]]:
    """Search Flarum users by username or nickname (for share dialog)."""
    from resophy.db import get_flarum_db

    with get_flarum_db() as fconn:
        with fconn.cursor() as fcur:
            query = (
                "SELECT id, username, nickname, avatar_url "
                "FROM users WHERE (username LIKE %s OR nickname LIKE %s)"
            )
            params: list = [f"%{search}%", f"%{search}%"]

            if exclude_user_id:
                query += " AND id != %s"
                params.append(exclude_user_id)

            query += " LIMIT %s"
            params.append(limit)

            fcur.execute(query, params)
            return fcur.fetchall()
