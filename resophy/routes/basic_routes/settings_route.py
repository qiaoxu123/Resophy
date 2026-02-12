from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict

from flask import Flask, g, jsonify, request, send_from_directory

from resophy import dal


def register_settings_routes(
    app: Flask,
    *,
    user_settings_file: str,
    default_user_settings: Dict[str, Any],
    reading_history_file: str,
    agentic_settings_file: str,
    default_agentic_settings: Dict[str, Any],
    avatars_dir: str,
    start_daily_arxiv_callback=None,
) -> None:

    # ========================================
    # User Settings (name, avatar, heatmap color)
    # ========================================
    @app.route("/api/settings/user", methods=["GET", "POST"])
    def api_user_settings():
        user_id = g.user_id

        if request.method == "GET":
            settings = dal.get_user_settings(user_id)
            # Check if user has an avatar file on disk
            avatar_filename = None
            for ext in ("jpg", "png", "gif"):
                candidate = f"avatar_{user_id}.{ext}"
                if os.path.exists(os.path.join(avatars_dir, candidate)):
                    avatar_filename = candidate
                    break
            # Map DB column names to camelCase for frontend
            return jsonify({
                "name": g.username or "Paper Reader",
                "avatar": avatar_filename,
                "heatmapColorScheme": settings.get("heatmap_color_scheme", "green"),
                "onboardingDontShow": bool(settings.get("onboarding_done", False)),
                "aiLanguage": settings.get("ai_language", "zh"),
            })

        data = request.json or {}
        dal.save_user_settings(user_id, data)
        return jsonify({"success": True})

    # ========================================
    # Avatar Upload
    # ========================================
    @app.route("/api/settings/avatar", methods=["POST"])
    def api_upload_avatar():
        try:
            user_id = g.user_id
            data = request.json or {}
            avatar_data = data.get("avatarData")

            if not avatar_data:
                return jsonify({"success": False, "error": "No avatar data"}), 400

            if "," in avatar_data:
                header, encoded = avatar_data.split(",", 1)
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "png" in header:
                    ext = "png"
                elif "gif" in header:
                    ext = "gif"
                else:
                    ext = "jpg"
            else:
                encoded = avatar_data
                ext = "jpg"

            image_data = base64.b64decode(encoded)
            # Remove old avatar files (different extension)
            for old_ext in ("jpg", "png", "gif"):
                old_path = os.path.join(avatars_dir, f"avatar_{user_id}.{old_ext}")
                if os.path.exists(old_path):
                    os.remove(old_path)
            # Per-user avatar filename
            filename = f"avatar_{user_id}.{ext}"
            filepath = os.path.join(avatars_dir, filename)

            with open(filepath, "wb") as f:
                f.write(image_data)

            return jsonify({"success": True, "avatar": filename})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/avatar", methods=["GET"])
    def api_get_avatar():
        user_id = g.user_id
        # Try per-user avatar
        for ext in ("jpg", "png", "gif"):
            filename = f"avatar_{user_id}.{ext}"
            if os.path.exists(os.path.join(avatars_dir, filename)):
                return send_from_directory(avatars_dir, filename)
        return jsonify({"error": "No avatar"}), 404

    # ========================================
    # Reading History (daily reading time)
    # ========================================
    @app.route("/api/settings/reading-history", methods=["GET", "POST"])
    def api_reading_history():
        user_id = g.user_id

        if request.method == "GET":
            history = dal.get_reading_history(user_id)
            return jsonify(history)

        # POST: batch merge
        data = request.json or {}
        try:
            for date_str, minutes in data.items():
                dal.record_reading(user_id, date_str, minutes)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/record", methods=["POST"])
    def api_record_reading():
        user_id = g.user_id
        try:
            data = request.json or {}
            minutes = data.get("minutes", 0)
            date_str = data.get("date")
            paper_id = data.get("paper_id")

            if not date_str:
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")

            total = dal.record_reading(user_id, date_str, minutes, paper_id)
            return jsonify({"success": True, "total": total})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/clear", methods=["POST"])
    def api_clear_reading_history():
        try:
            dal.clear_reading_history(g.user_id)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/week-papers", methods=["GET"])
    def api_week_papers():
        try:
            paper_ids = dal.get_week_paper_ids(g.user_id)
            return jsonify({
                "success": True,
                "papers": paper_ids,
                "count": len(paper_ids),
            })
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Agentic Settings (LLM / MinerU config)
    # ========================================
    @app.route("/api/settings/agentic", methods=["GET", "POST"])
    def api_agentic_settings():
        user_id = g.user_id

        if request.method == "GET":
            settings = dal.get_user_settings(user_id)
            return jsonify({
                "llmModel": settings.get("llm_model") or "",
                "llmBaseUrl": settings.get("llm_base_url") or "",
                "llmApiKey": settings.get("llm_api_key") or "",
                "mineruServerUrl": settings.get("mineru_server_url") or "",
                "mineruUseApi": bool(settings.get("mineru_use_api", False)),
                "mineruApiToken": settings.get("mineru_api_token") or "",
            })

        data = request.json or {}
        try:
            # Check LLM config completeness
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()
            is_llm_configured = bool(llm_model and llm_base_url and llm_api_key)

            # Check previous config
            old_settings = dal.get_user_settings(user_id)
            was_llm_configured = bool(
                old_settings.get("llm_model")
                and old_settings.get("llm_base_url")
                and old_settings.get("llm_api_key")
            )

            # Save to DB
            dal.save_user_settings(user_id, data)

            # Also save to agentic_settings.json for backward compat
            # (Daily arXiv and other modules still read from file)
            try:
                try:
                    with open(agentic_settings_file, "r", encoding="utf-8") as fp:
                        file_settings = json.load(fp)
                except (FileNotFoundError, json.JSONDecodeError):
                    file_settings = default_agentic_settings.copy()

                file_settings.update(data)
                file_settings.pop("analysisSystemPrompt", None)
                file_settings.pop("analysisSystemPromptZh", None)
                file_settings.pop("analysisSystemPromptEn", None)

                with open(agentic_settings_file, "w", encoding="utf-8") as fp:
                    json.dump(file_settings, fp, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Settings] Failed to sync agentic_settings.json: {e}")

            # Check if LLM config changed
            llm_config_changed = False
            if was_llm_configured and is_llm_configured:
                if (
                    (old_settings.get("llm_model") or "") != llm_model
                    or (old_settings.get("llm_base_url") or "") != llm_base_url
                    or (old_settings.get("llm_api_key") or "") != llm_api_key
                ):
                    llm_config_changed = True

            # Trigger Daily arXiv if config changed
            if is_llm_configured and (llm_config_changed or not was_llm_configured):
                try:
                    import threading
                    from resophy.tools.basic_tools.daily_arxiv import get_manager

                    papers_dir = os.path.dirname(agentic_settings_file)
                    daily_arxiv_settings_file = os.path.join(papers_dir, "daily_arxiv_settings.json")
                    temp_papers_dir = os.path.join(papers_dir, ".daily_arxiv_temp")
                    manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)

                    if hasattr(manager, "_llm_api_failed"):
                        manager._llm_api_failed = False
                        manager._llm_api_error_message = ""

                    if not manager._scheduler_running:
                        if start_daily_arxiv_callback:
                            start_daily_arxiv_callback()
                        else:
                            manager.start_scheduler()
                    else:
                        def trigger_fetch():
                            try:
                                manager._do_scheduled_fetch()
                            except Exception:
                                pass
                        threading.Thread(target=trigger_fetch, daemon=True).start()
                except Exception as e:
                    print(f"[Settings] Daily arXiv trigger error (non-fatal): {e}")

            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # Deprecated endpoints
    @app.route("/api/settings/translation", methods=["GET", "POST"])
    def api_translation_settings_deprecated():
        return jsonify({"error": "This endpoint is deprecated. Use /api/settings/agentic instead"}), 410

    @app.route("/api/settings/analysis", methods=["GET", "POST"])
    def api_analysis_settings_deprecated():
        return jsonify({"error": "This endpoint is deprecated. Use /api/settings/agentic instead"}), 410

    # ========================================
    # API Test Endpoints (unchanged, no per-user data)
    # ========================================
    @app.route("/api/settings/test/llm", methods=["POST"])
    def api_test_llm():
        try:
            data = request.json or {}
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()

            if not llm_model or not llm_base_url or not llm_api_key:
                return jsonify({"success": False, "error": "Please fill in complete LLM API config"}), 400

            try:
                from openai import OpenAI
            except ImportError:
                return jsonify({"success": False, "error": "OpenAI library not installed"}), 500

            client = OpenAI(base_url=llm_base_url, api_key=llm_api_key, timeout=30.0)
            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": "Can you see my message, if you can, respond with Yes."}],
                    max_tokens=50,
                )

                if response.choices and len(response.choices) > 0:
                    reply = response.choices[0].message.content.strip()
                    if "yes" in reply.lower():
                        return jsonify({"success": True, "message": "LLM API Connection successful!", "reply": reply})
                    else:
                        return jsonify({"success": False, "error": f"Unexpected reply: {reply}", "reply": reply})
                else:
                    return jsonify({"success": False, "error": "LLM API returned empty reply"})

            except Exception as e:
                error_msg = str(e)
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return jsonify({"success": False, "error": "API Key invalid or unauthorized"})
                elif "404" in error_msg or "Not Found" in error_msg:
                    return jsonify({"success": False, "error": "API endpoint not found, check Base URL"})
                elif "timeout" in error_msg.lower():
                    return jsonify({"success": False, "error": "Connection timed out"})
                else:
                    return jsonify({"success": False, "error": f"LLM API call failed: {error_msg}"})

        except Exception as exc:
            return jsonify({"success": False, "error": f"Test failed: {str(exc)}"}), 500

    @app.route("/api/settings/test/mineru", methods=["POST"])
    def api_test_mineru():
        try:
            import requests as req_lib
            data = request.json or {}
            mineru_server_url = data.get("mineruServerUrl", "").strip()
            if not mineru_server_url:
                return jsonify({"success": False, "error": "Please fill in MinerU Server URL"}), 400

            test_url = f"{mineru_server_url.rstrip('/')}/health"
            try:
                response = req_lib.get(test_url, timeout=10)
                if response.status_code == 200:
                    return jsonify({"success": True, "message": "MinerU server is accessible", "tested_url": test_url})
                else:
                    return jsonify({"success": False, "error": f"Server returned status {response.status_code}"})
            except req_lib.exceptions.ConnectionError:
                return jsonify({"success": False, "error": f"Cannot connect to {mineru_server_url}"})
            except req_lib.exceptions.Timeout:
                return jsonify({"success": False, "error": "Connection timeout"})
        except Exception as exc:
            return jsonify({"success": False, "error": f"Test failed: {str(exc)}"}), 500

    @app.route("/api/settings/test/mineru-api", methods=["POST"])
    def api_test_mineru_api_token():
        try:
            from resophy.tools.api_test_utils import test_mineru_api_token
            data = request.json or {}
            api_token = data.get("apiToken", "").strip()
            if not api_token:
                return jsonify({"success": False, "error": "Please enter API token"}), 400

            success, error_msg = test_mineru_api_token(api_token)
            if success:
                return jsonify({"success": True, "message": "API token is valid and working"})
            else:
                return jsonify({"success": False, "error": error_msg})
        except Exception as exc:
            return jsonify({"success": False, "error": f"Test failed: {str(exc)}"}), 500
