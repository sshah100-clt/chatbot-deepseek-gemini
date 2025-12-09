
import os
import uuid
import json
import pathlib
import time
import logging
import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db.models import Count, Sum, Max
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import Profile, ConversationSession, ConversationTurn

try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(getattr(settings, "BASE_DIR", ".")) / ".env")
except Exception:
    pass

logger = logging.getLogger(__name__)

def _current_profile(request):
    ident = request.session.get("profile_identifier")
    if not ident:
        return None
    try:
        return Profile.objects.filter(identifier=ident).first()
    except Exception as exc:
        logger.warning("Unable to load profile (%s): %s", ident, exc)
        return None

def index(request):
    profile = _current_profile(request)
    if not profile:
        return redirect("profile_login")
    selected_provider = _resolve_provider(request.session.get("selected_provider") or DEFAULT_MODEL_PROVIDER)
    session_map = {}
    if request.session.get("profile_identifier") == profile.identifier:
        try:
            raw_map = request.session.get("chat_sessions_by_provider") or {}
            if isinstance(raw_map, dict):
                session_map = {str(k): str(v) for k, v in raw_map.items()}
        except Exception:
            session_map = {}
    stored_session_id = session_map.get(selected_provider, "")
    history_payload = []
    for turn in _get_recent_turns(profile, MAX_CONTEXT_TURNS, stored_session_id, selected_provider):
        history_payload.append({"role": "user", "content": turn.prompt})
        history_payload.append({"role": "assistant", "content": turn.response})

    context = {
        "profile": profile,
        "is_admin": bool(request.session.get("is_admin")),
        "stored_session_id": stored_session_id,
        "selected_provider": selected_provider,
        "available_providers": AVAILABLE_PROVIDERS,
        "sessions_by_provider_json": json.dumps(session_map),
        "history_json": json.dumps(history_payload),
    }
    return render(request, "index.html", context)

def profile_login(request):
    error = ""
    token_required = bool(PORTAL_ADMIN_TOKEN)
    selected_provider = _resolve_provider(request.session.get("selected_provider") or DEFAULT_MODEL_PROVIDER)
    if request.method == "POST":
        identifier = (request.POST.get("identifier") or "").strip()
        display_name = (request.POST.get("display_name") or "").strip()
        admin_token = (request.POST.get("admin_token") or "").strip()
        selected_provider = _resolve_provider(request.POST.get("provider") or DEFAULT_MODEL_PROVIDER)
        if not identifier:
            error = "Name is required."
        else:
            profile = _get_profile(identifier, display_name or identifier)
            if profile:
                request.session["profile_identifier"] = profile.identifier
                request.session["profile_display_name"] = profile.display_name or profile.identifier
                request.session["selected_provider"] = selected_provider
                request.session.pop("chat_sessions_by_provider", None)
                request.session.pop("chat_session_id", None)
                is_admin = bool(PORTAL_ADMIN_TOKEN) and admin_token and admin_token == PORTAL_ADMIN_TOKEN
                request.session["is_admin"] = is_admin
                return redirect("admin_dashboard" if is_admin else "index")
            else:
                error = "Failed to create profile. Please try again."
    elif _current_profile(request):
        target = "admin_dashboard" if request.session.get("is_admin") else "index"
        return redirect(target)

    return render(
        request,
        "login.html",
        {
            "error": error,
            "token_required": token_required,
            "available_providers": AVAILABLE_PROVIDERS,
            "selected_provider": selected_provider,
        },
    )

def profile_logout(request):
    request.session.flush()
    return redirect("profile_login")

def admin_dashboard(request):
    if not request.session.get("is_admin"):
        return redirect("profile_login")

    profile = _current_profile(request)
    selected_identifier = request.GET.get("profile", "").strip()
    selected_session = request.GET.get("session", "").strip()
    if selected_identifier:
        # Normalize identifier to the stored casing to keep filters consistent.
        match_ident = (
            Profile.objects.filter(identifier__iexact=selected_identifier)
            .values_list("identifier", flat=True)
            .first()
        )
        if match_ident:
            selected_identifier = match_ident
        else:
            selected_identifier = ""
    try:
        profile_stats = list(
            Profile.objects.annotate(
                total_turns=Count("turns"),
                total_tokens=Coalesce(Sum("turns__total_tokens"), 0),
                last_activity=Max("turns__created_at"),
            )
            .order_by("-last_activity", "display_name", "identifier")
            .values(
                "identifier",
                "display_name",
                "total_turns",
                "total_tokens",
                "last_activity",
            )
        )
        session_stats_qs = (
            ConversationSession.objects.select_related("profile")
            .annotate(
                total_turns=Count("turns"),
                total_tokens=Coalesce(Sum("turns__total_tokens"), 0),
                last_turn_at=Coalesce(Max("turns__created_at"), "created_at"),
            )
            .order_by("-last_turn_at")
        )
        if selected_identifier:
            session_stats_qs = session_stats_qs.filter(profile__identifier=selected_identifier)
        session_stats = list(session_stats_qs[:200])

        turn_qs = ConversationTurn.objects.select_related("profile", "session").order_by("-created_at")
        if selected_identifier:
            turn_qs = turn_qs.filter(profile__identifier=selected_identifier)
        if selected_session:
            try:
                session_uuid = uuid.UUID(selected_session)
                turn_qs = turn_qs.filter(session__session_id=session_uuid)
            except ValueError:
                selected_session = ""
        recent_turns = list(turn_qs[:200])
        profile_choices = list(Profile.objects.order_by("display_name", "identifier").values("identifier", "display_name"))
        session_choices = [
            {
                "session_id": str(item.session_id),
                "profile_identifier": item.profile.identifier,
                "profile_display_name": item.profile.display_name or item.profile.identifier,
                "last_turn_at": item.last_turn_at,
            }
            for item in session_stats
        ]
    except Exception as exc:
        logger.warning("Unable to read analytics: %s", exc)
        profile_stats = []
        recent_turns = []
        profile_choices = []
        session_stats = []
        session_choices = []

    # Attach provider metadata for template safety (avoids missing-key errors).
    try:
        for session_item in session_stats:
            meta = session_item.metadata or {}
            session_item.provider_for_display = meta.get("provider") or "-"
    except Exception:
        pass
    try:
        for turn_item in recent_turns:
            turn_meta = turn_item.metadata or {}
            session_meta = (turn_item.session.metadata if turn_item.session else {}) or {}
            turn_item.provider_for_display = turn_meta.get("provider") or session_meta.get("provider") or "-"
    except Exception:
        pass

    return render(
        request,
        "admin_dashboard.html",
        {
            "profile": profile,
            "profile_stats": profile_stats,
            "recent_turns": recent_turns,
            "profile_choices": profile_choices,
            "selected_identifier": selected_identifier,
            "session_stats": session_stats,
            "session_choices": session_choices,
            "selected_session": selected_session,
        },
    )

DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
DEEPSEEK_API_BASE = (os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1").strip().rstrip("/")
DEEPSEEK_SYSTEM_PROMPT = (os.getenv("DEEPSEEK_SYSTEM_PROMPT") or "").strip()

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
GEMINI_API_BASE = (os.getenv("GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
GEMINI_SYSTEM_PROMPT = (os.getenv("GEMINI_SYSTEM_PROMPT") or "").strip()

DEFAULT_MODEL_PROVIDER = (os.getenv("DEFAULT_MODEL_PROVIDER") or "deepseek").strip().lower() or "deepseek"
PORTAL_ADMIN_TOKEN = (os.getenv("PORTAL_ADMIN_TOKEN") or "").strip()

MAX_CONTEXT_TURNS = 12  # includes user+assistant pairs
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_GEMINI = "gemini"
AVAILABLE_PROVIDERS = [PROVIDER_DEEPSEEK, PROVIDER_GEMINI]

def _normalize_identifier(value: str | None, fallback: str = "default") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback

def _resolve_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    if provider in AVAILABLE_PROVIDERS:
        return provider
    if DEFAULT_MODEL_PROVIDER in AVAILABLE_PROVIDERS:
        return DEFAULT_MODEL_PROVIDER
    return PROVIDER_DEEPSEEK

def _system_prompt(provider: str) -> str:
    if provider == PROVIDER_GEMINI:
        return GEMINI_SYSTEM_PROMPT
    return DEEPSEEK_SYSTEM_PROMPT

def _get_profile(identifier: str, display_name: str | None = None) -> Profile:
    ident = _normalize_identifier(identifier)
    defaults = {"display_name": display_name or ident}
    try:
        profile, _ = Profile.objects.get_or_create(identifier=ident, defaults=defaults)
        if display_name and display_name.strip() and profile.display_name != display_name.strip():
            profile.display_name = display_name.strip()
            profile.save(update_fields=["display_name"])
        return profile
    except Exception as exc:
        logger.warning("Profile persistence unavailable: %s", exc)
        return None

def _get_session(
    profile: Profile,
    session_token: str | None,
    stored_session_token: str | None = None,
    provider: str = PROVIDER_DEEPSEEK,
) -> ConversationSession | None:
    if not profile:
        return None
    candidate_tokens = [session_token, stored_session_token]
    for token in candidate_tokens:
        if not token:
            continue
        try:
            session_uuid = uuid.UUID(str(token))
        except ValueError:
            continue
        session = ConversationSession.objects.filter(session_id=session_uuid, profile=profile).first()
        if session:
            return session
    try:
        session = ConversationSession.objects.create(profile=profile, metadata={"provider": provider})
        return session
    except Exception as exc:
        logger.warning("Unable to create session for %s: %s", profile.identifier, exc)
        return None


def _log_turn(
    profile: Profile | None,
    session: ConversationSession | None,
    prompt: str,
    response: str,
    usage: dict,
    latency_ms: int,
    metadata: dict,
) -> None:
    if not profile or not session:
        return
    try:
        ConversationTurn.objects.create(
            profile=profile,
            session=session,
            prompt=prompt,
            response=response,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            latency_ms=latency_ms,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("Failed to record conversation turn: %s", exc)
    else:
        try:
            ConversationSession.objects.filter(pk=session.pk).update(last_activity=timezone.now())
        except Exception:
            pass

def _get_recent_turns(
    profile: Profile | None,
    limit: int | None = None,
    session_id: str | None = None,
    provider: str | None = None,
):
    if not profile:
        return []
    qs = ConversationTurn.objects.filter(profile=profile)
    if provider:
        qs = qs.filter(metadata__provider=provider)
    if session_id:
        try:
            session_uuid = uuid.UUID(str(session_id))
            qs = qs.filter(session__session_id=session_uuid)
        except ValueError:
            pass
    qs = qs.order_by("-created_at")
    turns = list(qs[:limit]) if limit else list(qs)
    turns.reverse()
    return turns

def _build_message_history(
    profile: Profile | None,
    user_text: str,
    session_id: str | None = None,
    provider: str = PROVIDER_DEEPSEEK,
):
    messages = []
    system_prompt = _system_prompt(provider)
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for turn in _get_recent_turns(profile, MAX_CONTEXT_TURNS, session_id, provider):
        messages.append({"role": "user", "content": turn.prompt})
        messages.append({"role": "assistant", "content": turn.response})
    messages.append({"role": "user", "content": user_text})
    return messages

def call_deepseek(messages: list[dict]) -> tuple[str, dict]:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY missing (set it in .env).")
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "stream": False,
    }
    try:
        resp = requests.post(
            f"{DEEPSEEK_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"DeepSeek response was not valid JSON: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DeepSeek response missing completion text.") from exc
    return content, data

def call_gemini(messages: list[dict]) -> tuple[str, dict]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing (set it in .env).")

    contents = []
    for msg in messages:
        role = (msg.get("role") or "user").lower()
        if role == "system":
            # System prompt is passed separately via system_instruction.
            continue
        text = msg.get("content") or ""
        gem_role = "model" if role == "assistant" else "user"
        contents.append({"role": gem_role, "parts": [{"text": text}]})

    payload = {"contents": contents}
    if GEMINI_SYSTEM_PROMPT:
        payload["system_instruction"] = {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]}

    try:
        resp = requests.post(
            f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"Gemini response was not valid JSON: {exc}") from exc

    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini response missing completion text.") from exc

    usage_meta = data.get("usageMetadata") or {}
    data["usage"] = {
        "prompt_tokens": usage_meta.get("promptTokenCount") or 0,
        "completion_tokens": usage_meta.get("candidatesTokenCount") or 0,
        "total_tokens": usage_meta.get("totalTokenCount") or 0,
    }
    return content, data

@csrf_exempt
def chat(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    q = (request.POST.get("q") or "").strip()

    try:
        raw = (request.body or b"").decode("utf-8")
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    if not q:
        q = (data.get("prompt") or data.get("q") or data.get("text") or "").strip()

    if not q:
        return JsonResponse({"error": "Empty prompt"}, status=400)

    session_profile = _current_profile(request)
    profile_identifier = (
        request.POST.get("profile_id")
        or request.POST.get("profile")
        or data.get("profile_id")
        or data.get("profile")
        or (session_profile.identifier if session_profile else "")
        or "default"
    )
    profile_name = request.POST.get("profile_name") or data.get("profile_name")
    if not profile_name and session_profile:
        profile_name = session_profile.display_name
    provider = _resolve_provider(request.POST.get("provider") or data.get("provider") or DEFAULT_MODEL_PROVIDER)
    session_token = request.POST.get("session_id") or data.get("session_id")
    profile = _get_profile(profile_identifier, profile_name) or session_profile
    if not profile:
        return JsonResponse({"error": "Profile not configured. Please log in again."}, status=403)

    request.session["selected_provider"] = provider
    stored_session_token = ""
    session_map: dict[str, str] = {}
    if request.session.get("profile_identifier") == profile.identifier:
        try:
            raw_map = request.session.get("chat_sessions_by_provider") or {}
            if isinstance(raw_map, dict):
                session_map = {str(k): str(v) for k, v in raw_map.items()}
        except Exception:
            session_map = {}
        stored_session_token = session_map.get(provider) or ""

    session = _get_session(profile, session_token, stored_session_token, provider) if profile else None
    session_identifier = ""
    if session:
        session_identifier = str(session.session_id)
    else:
        session_identifier = str(session_token or uuid.uuid4())
    session_map[provider] = session_identifier
    request.session["chat_sessions_by_provider"] = session_map
    request.session["chat_session_id"] = session_identifier

    try:
        start_ts = time.perf_counter()
        history_messages = _build_message_history(profile, q, session_identifier, provider)
        if provider == PROVIDER_GEMINI:
            answer, raw_payload = call_gemini(history_messages)
        else:
            answer, raw_payload = call_deepseek(history_messages)
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
    except Exception as e:
        return JsonResponse({"error": f"{provider.capitalize()} failed: {e}"}, status=500)

    usage = raw_payload.get("usage") or {} if isinstance(raw_payload, dict) else {}

    extra_meta = {
        "usage": usage,
        "model": raw_payload.get("model") if isinstance(raw_payload, dict) else "",
        "response_id": raw_payload.get("id") if isinstance(raw_payload, dict) else "",
        "provider": provider,
        "session_identifier": session_identifier,
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }

    _log_turn(
        profile=profile,
        session=session,
        prompt=q,
        response=answer,
        usage=usage,
        latency_ms=latency_ms,
        metadata=extra_meta,
    )

    response_payload = {
        "answer": answer,
        "session_id": session_identifier,
        "provider": provider,
        "profile": profile.identifier if profile else _normalize_identifier(profile_identifier),
        "profile_name": profile.display_name or profile.identifier,
        "latency_ms": latency_ms,
    }
    if usage:
        response_payload["usage"] = usage

    return JsonResponse(response_payload)
