from __future__ import annotations

import os
import shutil
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, g, jsonify, request, send_file

from resophy import dal


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Any]: ...


class PaperStore(Protocol):
    def list_by_category(self, category_id: str) -> List[Any]: ...
    def remove(self, paper_id: str) -> Optional[Any]: ...


def register_category_routes(
    app: Flask,
    *,
    get_categories: Any = None,  # Deprecated, kept for backward compat
    save_categories: Any = None,  # Deprecated, kept for backward compat
    find_category_node: Any = None,  # Deprecated, kept for backward compat
    get_category_path: GetCategoryPathFn,
    get_papers_in_category: GetPapersInCategoryFn,
    add_pdf_counts_to_categories: Any = None,  # Deprecated
    get_category_pdf_count: Any = None,  # Deprecated
    paper_store: PaperStore,
    upload_folder: str,
) -> None:

    def _count_papers_recursive(node: Dict[str, Any]) -> int:
        """Count papers in a category and all subcategories via paper_store."""
        count = len(paper_store.list_by_category(node["id"]))
        for child in node.get("children", []):
            count += _count_papers_recursive(child)
        return count

    def _add_counts(tree: Dict[str, Any]) -> Dict[str, Any]:
        """Add pdf_count to every node in the tree."""
        tree["pdf_count"] = _count_papers_recursive(tree)
        for child in tree.get("children", []):
            _add_counts(child)
        return tree

    @app.route("/api/categories")
    def api_categories():
        user_id = g.user_id
        categories = dal.get_categories_tree(user_id)
        categories_with_counts = _add_counts(categories)
        return jsonify(categories_with_counts)

    @app.route("/api/categories", methods=["POST"])
    def api_add_category():
        user_id = g.user_id
        data = request.json or {}
        parent_id = data.get("parent_id")
        name = data.get("name")

        if not name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        # Treat "root" as no parent
        if parent_id in (None, "root"):
            parent_id = None
        else:
            # Verify parent exists
            if not dal.find_category_node_db(user_id, parent_id):
                return (
                    jsonify({"success": False, "error": "Parent category not found"}),
                    404,
                )

        new_category = dal.create_category(user_id, name, parent_id)
        return jsonify({"success": True, "category": new_category})

    @app.route("/api/categories/<category_id>", methods=["PUT"])
    def api_rename_category(category_id):
        user_id = g.user_id
        data = request.json or {}
        new_name = data.get("name")

        if not new_name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        if not dal.rename_category(user_id, category_id, new_name):
            return jsonify({"success": False, "error": "Category not found"}), 404

        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>/pin", methods=["PUT"])
    def api_pin_category(category_id):
        """Pin/unpin a category"""
        user_id = g.user_id
        data = request.json or {}
        pinned = data.get("pinned", False)

        if not dal.pin_category(user_id, category_id, pinned):
            return jsonify({"success": False, "error": "Category not found"}), 404

        return jsonify({"success": True, "pinned": pinned})

    @app.route("/api/categories/<category_id>/color", methods=["PUT"])
    def api_change_category_color(category_id):
        """Change category icon color"""
        user_id = g.user_id
        data = request.json or {}
        color = data.get("color")

        if not color:
            return (
                jsonify({"success": False, "error": "Color is required"}),
                400,
            )

        if not dal.set_category_color(user_id, category_id, color):
            return jsonify({"success": False, "error": "Category not found"}), 404

        return jsonify({"success": True, "color": color})

    @app.route("/api/categories/<category_id>", methods=["DELETE"])
    def api_delete_category(category_id):
        user_id = g.user_id

        # Get category path before deletion (for folder cleanup)
        category_path = dal.get_category_path_db(user_id, category_id)

        # Delete from DB (returns all deleted category IDs including descendants)
        deleted_ids = dal.delete_category(user_id, category_id)

        if not deleted_ids:
            return jsonify({"success": False, "error": "Category not found"}), 404

        # Clean up papers in paper_store
        for cat_id in deleted_ids:
            papers = paper_store.list_by_category(cat_id)
            for paper in papers:
                paper_id = paper.id if hasattr(paper, "id") else paper.get("id")
                if paper_id:
                    paper_store.remove(paper_id)

        # Delete physical folder
        if category_path and len(category_path) > 1:
            folder_path = os.path.join(upload_folder, *category_path[1:])
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)

        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>/move", methods=["PUT"])
    def api_move_category(category_id):
        user_id = g.user_id
        data = request.json or {}
        target_parent_id = data.get("target_parent_id")

        if not target_parent_id:
            return (
                jsonify({"success": False, "error": "target parent category ID cannot be empty"}),
                400,
            )

        # Cannot move root
        if category_id == "root":
            return (
                jsonify({"success": False, "error": "Cannot move root category"}),
                400,
            )

        # Cannot move to self
        if category_id == target_parent_id:
            return (
                jsonify({"success": False, "error": "Category cannot be moved to itself"}),
                400,
            )

        # Check for circular reference
        actual_target = None if target_parent_id in ("root",) else target_parent_id
        if actual_target and dal.is_descendant_of(user_id, category_id, actual_target):
            return (
                jsonify({"success": False, "error": "Categories cannot be moved to their subcategories"}),
                400,
            )

        # Get old path for folder move
        old_path = dal.get_category_path_db(user_id, category_id)

        # Move in DB
        if not dal.move_category(user_id, category_id, actual_target):
            return jsonify({"success": False, "error": "Category does not exist"}), 404

        # Get new path
        new_path = dal.get_category_path_db(user_id, category_id)

        # Move physical folder
        if old_path and new_path and len(old_path) > 1 and len(new_path) > 1:
            old_folder = os.path.join(upload_folder, *old_path[1:])
            new_folder = os.path.join(upload_folder, *new_path[1:])

            if os.path.exists(old_folder) and old_folder != new_folder:
                new_parent_folder = os.path.dirname(new_folder)
                os.makedirs(new_parent_folder, exist_ok=True)

                if os.path.exists(new_folder):
                    return (
                        jsonify({"success": False, "error": "A folder with the same name already exists in the target location"}),
                        400,
                    )

                try:
                    shutil.move(old_folder, new_folder)
                except Exception as e:
                    print(f"[move category] Failed to move folder: {e}")

        return jsonify({
            "success": True,
            "old_path": old_path,
            "new_path": new_path,
        })

    @app.route("/api/categories/<category_id>/export-bibtex", methods=["GET"])
    def api_export_category_bibtex(category_id: str):
        """Export all papers under a category as BibTeX"""
        try:
            user_id = g.user_id
            categories = dal.get_categories_tree(user_id)

            # Find node in the tree
            def _find_node(node: Dict[str, Any], target_id: str) -> Optional[Dict[str, Any]]:
                if node.get("id") == target_id:
                    return node
                for child in node.get("children", []):
                    result = _find_node(child, target_id)
                    if result:
                        return result
                return None

            category_node = _find_node(categories, category_id)
            if not category_node:
                return jsonify({"error": "Category not found"}), 404

            # Recursively collect all papers
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                papers = []
                node_path = dal.get_category_path_db(user_id, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))
                return papers

            all_papers = collect_papers_recursive(category_node)

            if not all_papers:
                return jsonify({"error": "There are no papers in this category"}), 404

            bibtex_entries = []
            for paper in all_papers:
                if hasattr(paper, "bibtex"):
                    bibtex = paper.bibtex
                elif isinstance(paper, dict):
                    bibtex = paper.get("bibtex", "")
                else:
                    bibtex = ""

                if bibtex and bibtex.strip():
                    bibtex_entries.append(bibtex.strip())

            if not bibtex_entries:
                return jsonify({"error": "No papers have BibTeX"}), 404

            bibtex_content = "\n\n".join(bibtex_entries)

            category_name = category_node.get("name", "export")
            safe_name = "".join(
                c if c.isalnum() or c in (" ", "-", "_") else "" for c in category_name
            )
            safe_name = safe_name.strip().replace(" ", "_")
            filename = f"{safe_name}_bibtex.bib"

            bibtex_bytes = bibtex_content.encode("utf-8")
            bibtex_file = BytesIO(bibtex_bytes)

            return send_file(
                bibtex_file,
                mimetype="application/x-bibtex",
                as_attachment=True,
                download_name=filename,
            )

        except Exception as exc:
            print(f"Export BibTeX failed: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Export failed: {str(exc)}"}), 500

    @app.route("/api/categories/<category_id>/copy-arxiv-urls", methods=["GET"])
    def api_copy_category_arxiv_urls(category_id: str):
        """Copy all arXiv URLs under a category"""
        try:
            user_id = g.user_id
            categories = dal.get_categories_tree(user_id)

            def _find_node(node: Dict[str, Any], target_id: str) -> Optional[Dict[str, Any]]:
                if node.get("id") == target_id:
                    return node
                for child in node.get("children", []):
                    result = _find_node(child, target_id)
                    if result:
                        return result
                return None

            category_node = _find_node(categories, category_id)
            if not category_node:
                return jsonify({"error": "Category not found"}), 404

            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                papers = []
                node_path = dal.get_category_path_db(user_id, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))
                return papers

            all_papers = collect_papers_recursive(category_node)

            if not all_papers:
                return jsonify({"error": "There are no papers in this category"}), 404

            arxiv_entries = []
            for paper in all_papers:
                arxiv_url = None
                arxiv_id = None
                title = ""

                if hasattr(paper, "arxiv_url"):
                    arxiv_url = paper.arxiv_url
                    arxiv_id = getattr(paper, "arxiv_id", None)
                    title = paper.title or paper.filename or ""
                elif isinstance(paper, dict):
                    arxiv_url = paper.get("arxiv_url")
                    arxiv_id = paper.get("arxiv_id")
                    title = paper.get("title") or paper.get("filename") or ""
                else:
                    continue

                if not arxiv_url or not arxiv_url.strip():
                    if arxiv_id and arxiv_id.strip():
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_id.strip()}"
                    else:
                        continue

                if arxiv_url and arxiv_url.strip():
                    arxiv_entries.append({
                        "title": title.strip() if title else "Untitled paper",
                        "url": arxiv_url.strip(),
                    })

            if not arxiv_entries:
                return jsonify({"error": "No papers have arXiv URL"}), 404

            formatted_text = "\n\n".join(
                [f"{entry['title']}：{entry['url']}" for entry in arxiv_entries]
            )

            return jsonify({
                "success": True,
                "text": formatted_text,
                "count": len(arxiv_entries),
            })

        except Exception as exc:
            print(f"Get arXiv URL failed: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(exc)}), 500
