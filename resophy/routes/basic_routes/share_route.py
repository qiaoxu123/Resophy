"""
Shared Library routes: sharing categories between users + global team library.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from flask import Flask, g, jsonify, request
from werkzeug.utils import secure_filename

from resophy import dal
from resophy.config import AppConfig
from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store
from resophy.dal import GLOBAL_LIBRARY_USER_ID


def register_share_routes(
    app: Flask, *, cfg: AppConfig, upload_folder: str = ""
) -> None:

    # ------------------------------------------------------------------
    # Shared categories for the current user (what others shared with me)
    # ------------------------------------------------------------------

    @app.route("/api/shared/categories")
    def api_shared_categories():
        """Get categories shared with me, grouped by owner."""
        user_id = g.user_id
        shares = dal.get_shared_categories_for_user(user_id)

        # Build subtrees for each shared category
        result = []
        for share in shares:
            tree = dal.get_shared_category_tree(
                share["owner_id"], share["category_id"]
            )
            # Count papers in the subtree
            paper_count = _count_owner_papers_recursive(
                share["owner_id"], tree
            )
            result.append({
                "share_id": share["share_id"],
                "category_id": share["category_id"],
                "category_name": share["category_name"],
                "owner_id": share["owner_id"],
                "owner_name": share["owner_name"],
                "permission": share["permission"],
                "icon_color": share.get("icon_color"),
                "tree": tree,
                "paper_count": paper_count,
            })

        return jsonify(result)

    @app.route("/api/shared/papers/<category_id>")
    def api_shared_papers(category_id):
        """Get papers in a shared category (non-recursive)."""
        user_id = g.user_id
        owner_id = request.args.get("owner_id", type=int)

        if not owner_id:
            return jsonify({"error": "owner_id is required"}), 400

        # Verify share permission
        perm = dal.get_share_permission(user_id, category_id)
        if not perm:
            return jsonify({"error": "Access denied"}), 403

        papers = dal.get_user_papers(owner_id, category_id=category_id)
        return jsonify(_serialize_papers(papers))

    @app.route("/api/shared/papers/<category_id>/recursive")
    def api_shared_papers_recursive(category_id):
        """Recursively get all papers in a shared category and its children."""
        user_id = g.user_id
        owner_id = request.args.get("owner_id", type=int)

        if not owner_id:
            return jsonify({"error": "owner_id is required"}), 400

        perm = dal.get_share_permission(user_id, category_id)
        if not perm:
            return jsonify({"error": "Access denied"}), 403

        tree = dal.get_shared_category_tree(owner_id, category_id)
        all_papers = _collect_owner_papers_recursive(owner_id, tree)
        return jsonify(_serialize_papers(all_papers))

    # ------------------------------------------------------------------
    # Edit permission: add/remove papers in shared categories
    # ------------------------------------------------------------------

    @app.route("/api/shared/papers/<category_id>/add", methods=["POST"])
    def api_shared_add_paper(category_id):
        """Add an existing paper to a shared category (requires edit perm)."""
        user_id = g.user_id
        data = request.json or {}
        paper_id = data.get("paper_id")

        if not paper_id:
            return jsonify({"error": "paper_id is required"}), 400

        # Find the owner from the share record
        owner_id = _get_owner_for_shared_category(user_id, category_id)
        if not owner_id:
            return jsonify({"error": "Access denied"}), 403

        perm = dal.get_share_permission(user_id, category_id)
        if perm != "edit":
            return jsonify({"error": "Edit permission required"}), 403

        # Link the paper to the owner's category
        dal.link_user_paper(
            owner_id, paper_id, category_id=category_id, upload_source="shared"
        )
        return jsonify({"success": True})

    @app.route(
        "/api/shared/papers/<category_id>/<paper_id>", methods=["DELETE"]
    )
    def api_shared_remove_paper(category_id, paper_id):
        """Remove a paper from a shared category (requires edit perm)."""
        user_id = g.user_id

        owner_id = _get_owner_for_shared_category(user_id, category_id)
        if not owner_id:
            return jsonify({"error": "Access denied"}), 403

        perm = dal.get_share_permission(user_id, category_id)
        if perm != "edit":
            return jsonify({"error": "Edit permission required"}), 403

        dal.unlink_user_paper(owner_id, paper_id)
        return jsonify({"success": True})

    # ------------------------------------------------------------------
    # Owner: manage sharing
    # ------------------------------------------------------------------

    @app.route("/api/categories/<category_id>/share", methods=["POST"])
    def api_share_category(category_id):
        """Share a category with another user."""
        user_id = g.user_id
        data = request.json or {}
        target_user_id = data.get("user_id")
        permission = data.get("permission", "view")

        if not target_user_id:
            return jsonify({"error": "user_id is required"}), 400

        if int(target_user_id) == user_id:
            return jsonify({"error": "Cannot share with yourself"}), 400

        # Verify the category belongs to the current user
        cat = dal.find_category_node_db(user_id, category_id)
        if not cat:
            return jsonify({"error": "Category not found"}), 404

        dal.share_category(user_id, category_id, int(target_user_id), permission)
        return jsonify({"success": True})

    @app.route(
        "/api/categories/<category_id>/share/<int:target_user_id>",
        methods=["PUT"],
    )
    def api_update_share(category_id, target_user_id):
        """Update the permission of an existing share."""
        user_id = g.user_id
        data = request.json or {}
        permission = data.get("permission", "view")

        cat = dal.find_category_node_db(user_id, category_id)
        if not cat:
            return jsonify({"error": "Category not found"}), 404

        dal.share_category(user_id, category_id, target_user_id, permission)
        return jsonify({"success": True})

    @app.route(
        "/api/categories/<category_id>/share/<int:target_user_id>",
        methods=["DELETE"],
    )
    def api_unshare_category(category_id, target_user_id):
        """Remove sharing for a specific user."""
        user_id = g.user_id

        cat = dal.find_category_node_db(user_id, category_id)
        if not cat:
            return jsonify({"error": "Category not found"}), 404

        dal.unshare_category(user_id, category_id, target_user_id)
        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>/shares")
    def api_category_shares(category_id):
        """Get the list of users a category is shared with."""
        user_id = g.user_id

        cat = dal.find_category_node_db(user_id, category_id)
        if not cat:
            return jsonify({"error": "Category not found"}), 404

        shares = dal.get_category_shares(user_id, category_id)
        return jsonify(shares)

    # ------------------------------------------------------------------
    # User search (for share dialog)
    # ------------------------------------------------------------------

    @app.route("/api/users/search")
    def api_search_users():
        """Search Flarum users (for the share dialog autocomplete)."""
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([])

        user_id = g.user_id
        users = dal.search_flarum_users(q, exclude_user_id=user_id)
        return jsonify([
            {
                "id": u["id"],
                "username": u["username"],
                "nickname": u.get("nickname") or u["username"],
                "avatar_url": u.get("avatar_url"),
            }
            for u in users
        ])

    # ==================================================================
    # Global Team Library (JLU-MCNS-MEC)  — user_id = 0
    # All authenticated users have full access.
    # ==================================================================

    GID = GLOBAL_LIBRARY_USER_ID  # shorthand

    @app.route("/api/global/categories")
    def api_global_categories():
        """Get the global library category tree with paper counts."""
        tree = dal.get_categories_tree(GID)
        _add_paper_counts(tree)
        return jsonify(tree)

    @app.route("/api/global/categories", methods=["POST"])
    def api_global_create_category():
        data = request.json or {}
        name = data.get("name", "").strip()
        parent_id = data.get("parent_id")
        if not name:
            return jsonify({"error": "name is required"}), 400
        cat = dal.create_category(GID, name, parent_id or None)
        return jsonify({"success": True, "category": cat})

    @app.route("/api/global/categories/<category_id>", methods=["PUT"])
    def api_global_rename_category(category_id):
        data = request.json or {}
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        dal.rename_category(GID, category_id, name)
        return jsonify({"success": True})

    @app.route("/api/global/categories/<category_id>", methods=["DELETE"])
    def api_global_delete_category(category_id):
        deleted_ids = dal.delete_category(GID, category_id)
        # Also remove user_papers linked to deleted categories
        if deleted_ids:
            from resophy.db import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    ph = ", ".join(["%s"] * len(deleted_ids))
                    cur.execute(
                        f"DELETE FROM user_papers "
                        f"WHERE user_id = %s AND category_id IN ({ph})",
                        [GID] + deleted_ids,
                    )
                conn.commit()
        return jsonify({"success": True, "deleted_ids": deleted_ids})

    @app.route("/api/global/categories/<category_id>/move", methods=["PUT"])
    def api_global_move_category(category_id):
        data = request.json or {}
        target_parent_id = data.get("target_parent_id")
        dal.move_category(GID, category_id, target_parent_id or None)
        return jsonify({"success": True})

    @app.route("/api/global/categories/<category_id>/pin", methods=["PUT"])
    def api_global_pin_category(category_id):
        data = request.json or {}
        pinned = bool(data.get("pinned", False))
        dal.pin_category(GID, category_id, pinned)
        return jsonify({"success": True})

    @app.route("/api/global/categories/<category_id>/color", methods=["PUT"])
    def api_global_color_category(category_id):
        data = request.json or {}
        color = data.get("color", "")
        dal.set_category_color(GID, category_id, color)
        return jsonify({"success": True})

    # ---- Global papers ----

    @app.route("/api/global/papers/<category_id>")
    def api_global_papers(category_id):
        papers = dal.get_user_papers(GID, category_id=category_id)
        return jsonify(_serialize_papers(papers))

    @app.route("/api/global/papers/<category_id>/recursive")
    def api_global_papers_recursive(category_id):
        tree = dal.get_categories_tree(GID)
        node = _find_node(tree, category_id)
        if not node:
            return jsonify([])
        all_papers = _collect_owner_papers_recursive(GID, node)
        return jsonify(_serialize_papers(all_papers))

    @app.route("/api/global/upload", methods=["POST"])
    def api_global_upload():
        """Upload a PDF into the global library."""
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        category_id = request.form.get("category_id", "global-jlu-mcns-mec")

        if not file.filename or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "Only PDF files are supported"}), 400

        # Build storage path under _global/
        cat_path = dal.get_category_path_db(GID, category_id)
        if not cat_path:
            return jsonify({"error": "Category not found"}), 404

        # cat_path = ["Root", "JLU-MCNS-MEC", ...] → store under _global/JLU-MCNS-MEC/...
        rel_parts = cat_path[1:]  # skip "Root"
        storage_dir = os.path.join(upload_folder, "_global", *rel_parts)
        os.makedirs(storage_dir, exist_ok=True)

        # Secure filename
        original_filename = file.filename
        safe_name = secure_filename(original_filename) or f"{uuid.uuid4().hex[:8]}.pdf"
        dest_path = os.path.join(storage_dir, safe_name)

        # Avoid overwrite
        counter = 1
        base, ext = os.path.splitext(safe_name)
        while os.path.exists(dest_path):
            dest_path = os.path.join(storage_dir, f"{base}_{counter}{ext}")
            counter += 1

        file.save(dest_path)

        # Compute content hash for dedup
        sha256 = hashlib.sha256()
        with open(dest_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        content_hash = sha256.hexdigest()

        # Dedup check
        existing = dal.find_paper_by_hash(content_hash)
        if existing:
            paper_id = existing["id"]
            # Just link to this category if not already linked
            dal.link_user_paper(
                GID, paper_id, category_id=category_id, upload_source="global_upload"
            )
            # Remove duplicate file
            os.remove(dest_path)
            return jsonify({
                "success": True,
                "paper": {"id": paper_id, "title": existing.get("title", "")},
                "deduplicated": True,
            })

        # Create new paper
        paper_id = str(uuid.uuid4())
        final_filename = os.path.basename(dest_path)
        title = os.path.splitext(original_filename)[0]

        dal.insert_paper(paper_id, {
            "content_hash": content_hash,
            "title": title,
            "original_filename": original_filename,
            "pdf_storage_path": dest_path,
            "uploaded_by": g.user_id,
        })
        dal.link_user_paper(
            GID, paper_id, category_id=category_id, upload_source="global_upload"
        )

        # Register in paper_store for PDF viewer
        paper = Paper.from_dict({
            "id": paper_id,
            "title": title,
            "filename": final_filename,
            "file_path": dest_path,
            "original_filename": original_filename,
            "upload_date": datetime.now().isoformat(),
        })
        paper_store.upsert(paper, category_id=category_id, category_path=cat_path)

        # Trigger background metadata extraction
        def _bg_metadata():
            try:
                from resophy.tools.basic_tools.upload_paper import (
                    process_uploaded_pdf_fast,
                )
                info = process_uploaded_pdf_fast(dest_path, original_filename)
                if info and info.get("title"):
                    dal.update_paper_shared(paper_id, {
                        "title": info.get("title", title),
                        "authors": info.get("authors", ""),
                        "abstract": info.get("abstract", ""),
                        "year": info.get("year", ""),
                        "arxiv_id": info.get("arxiv_id", ""),
                        "arxiv_url": info.get("arxiv_url", ""),
                        "affiliation": info.get("affiliation", ""),
                        "summary": info.get("summary", ""),
                        "bibtex": info.get("bibtex", ""),
                    })
                    # Update paper_store
                    p = paper_store.get(paper_id)
                    if p:
                        p.title = info.get("title", p.title)
                        p.authors = info.get("authors", "")
                        p.abstract = info.get("abstract", "")
                        p.year = info.get("year", "")
                        p.arxiv_id = info.get("arxiv_id", "")
                        p.affiliation = info.get("affiliation", "")
                        paper_store.upsert(p, category_id=category_id, category_path=cat_path)
            except Exception as exc:
                print(f"[Global upload] background metadata failed: {exc}")

        threading.Thread(target=_bg_metadata, daemon=True).start()

        return jsonify({
            "success": True,
            "paper": {"id": paper_id, "title": title, "filename": final_filename},
        })

    @app.route("/api/global/paper/<paper_id>", methods=["DELETE"])
    def api_global_delete_paper(paper_id):
        """Remove a paper from the global library."""
        # Unlink from global user
        dal.unlink_user_paper(GID, paper_id)

        # If no other users reference this paper, delete files + shared row
        remaining = dal.count_paper_users(paper_id)
        if remaining == 0:
            db_paper = dal.get_paper(paper_id)
            if db_paper and db_paper.get("pdf_storage_path"):
                try:
                    path = db_paper["pdf_storage_path"]
                    if os.path.exists(path):
                        os.remove(path)
                    # Remove companion JSON
                    json_path = os.path.splitext(path)[0] + ".json"
                    if os.path.exists(json_path):
                        os.remove(json_path)
                except Exception as exc:
                    print(f"[Global delete] file cleanup error: {exc}")
            dal.delete_paper(paper_id)

        paper_store.remove(paper_id)
        return jsonify({"success": True})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_paper_counts(node: dict) -> int:
        """Recursively add paper_count to each node. Returns total."""
        own = len(dal.get_user_papers(GID, category_id=node.get("id")))
        total = own
        for child in node.get("children", []):
            total += _add_paper_counts(child)
        node["paper_count"] = total
        return total

    def _find_node(tree: dict, target_id: str) -> Optional[dict]:
        """DFS find a node by id in a category tree."""
        if tree.get("id") == target_id:
            return tree
        for child in tree.get("children", []):
            found = _find_node(child, target_id)
            if found:
                return found
        return None

    def _get_owner_for_shared_category(
        user_id: int, category_id: str
    ) -> int | None:
        """Find the owner of the category that is shared with *user_id*."""
        from resophy.db import get_db as _get_db

        with _get_db() as conn:
            with conn.cursor() as cur:
                # Walk up ancestors to find the shared root
                current_id = category_id
                visited: set[str] = set()
                while current_id and current_id not in visited:
                    visited.add(current_id)
                    cur.execute(
                        "SELECT owner_id FROM shared_categories "
                        "WHERE category_id = %s AND shared_with = %s",
                        (current_id, user_id),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["owner_id"]

                    cur.execute(
                        "SELECT parent_id FROM user_categories WHERE id = %s",
                        (current_id,),
                    )
                    parent = cur.fetchone()
                    current_id = parent["parent_id"] if parent else None
        return None

    def _count_owner_papers_recursive(
        owner_id: int, node: dict
    ) -> int:
        """Count papers owned by *owner_id* in a category tree node."""
        count = len(dal.get_user_papers(owner_id, category_id=node["id"]))
        for child in node.get("children", []):
            count += _count_owner_papers_recursive(owner_id, child)
        return count

    def _collect_owner_papers_recursive(
        owner_id: int, node: dict
    ) -> list:
        """Collect all papers owned by *owner_id* in a category tree."""
        papers = list(dal.get_user_papers(owner_id, category_id=node["id"]))
        for child in node.get("children", []):
            papers.extend(_collect_owner_papers_recursive(owner_id, child))
        return papers

    def _serialize_papers(papers: list) -> list:
        """Convert paper dicts to JSON-safe format."""
        result = []
        for p in papers:
            item = dict(p)
            # Convert datetime objects to strings
            for key in ("created_at", "updated_at", "user_added_at", "status_updated_at"):
                if key in item and item[key] is not None:
                    item[key] = str(item[key])
            result.append(item)
        return result
