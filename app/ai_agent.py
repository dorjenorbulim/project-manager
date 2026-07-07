"""Charter and stakeholder generation helpers.

This module previously hosted a free-form chat assistant. That has been
removed in favour of two focused builders:

  * generate_charter_outline()  -> smartly suggests a project charter
    outline from minimal input (name + short description).
  * suggest_stakeholders()      -> suggests an initial stakeholder list
    for a charter, which the user then tunes with interest/influence
    ratings to drive a Mendelow power/interest grid.

When AI_API_KEY is set, the calls go to the OpenAI-compatible endpoint
configured via AI_BASE_URL / AI_MODEL (defaults: OpenRouter). When no
key is set, a deterministic local template generator produces a useful
starter outline, so the app always works.
"""

import os
import json
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

AI_API_KEY = os.environ.get('AI_API_KEY', '')
AI_BASE_URL = os.environ.get('AI_BASE_URL', 'https://openrouter.ai/api/v1')
AI_MODEL = os.environ.get('AI_MODEL', 'openai/gpt-oss-120b:free')

FALLBACK_MODELS = [
    'nvidia/nemotron-3-super-120b-a12b:free',
    'qwen/qwen3-next-80b-a3b-instruct:free',
]


def is_ai_configured():
    return bool(AI_API_KEY)


def get_ai_status():
    configured = bool(AI_API_KEY)
    provider = 'OpenRouter' if 'openrouter' in AI_BASE_URL else ('OpenAI' if 'api.openai' in AI_BASE_URL else 'Custom')
    return {
        'configured': configured,
        'model': AI_MODEL if configured else None,
        'provider': provider,
    }


# ─── Charter outline generation ───────────────────────────────────────────

CHARTER_KEYS = ['objectives', 'scope_in', 'scope_out', 'deliverables', 'milestones', 'success_criteria', 'risks', 'assumptions']


def _empty_outline():
    return {k: [] for k in CHARTER_KEYS}


def _template_charter_outline(name, description, start_date=None, end_date=None, budget=None):
    """Deterministic local fallback that produces a useful starter outline
    from minimal input. Keeps the app fully functional without an AI key."""
    desc = (description or '').strip()
    name_clean = (name or 'the project').strip()
    base = _empty_outline()

    base['objectives'] = [
        f"Deliver {name_clean} on time and within budget",
        f"Meet the core need described as: {desc[:140]}" if desc else "Define and meet the core project objectives",
        "Achieve stakeholder satisfaction with the delivered outcome",
    ]

    base['scope_in'] = [
        "Project planning and scoping",
        "Design and development of deliverables",
        "Testing and quality assurance",
        "Documentation and handover",
    ]

    base['scope_out'] = [
        "Ongoing operational support after handover",
        "Changes requested after scope is baselined",
    ]

    base['deliverables'] = [
        f"{name_clean} - completed product/outcome",
        "Project plan and schedule",
        "Status reports and final closure report",
    ]

    base['milestones'] = [
        {"name": "Project kickoff", "weeks": 0},
        {"name": "Scope and plan baselined", "weeks": 2},
        {"name": "Design/requirements approved", "weeks": 4},
        {"name": "Build/delivery complete", "weeks": 8},
        {"name": "Testing and UAT complete", "weeks": 10},
        {"name": "Go-live and handover", "weeks": 12},
    ]

    base['success_criteria'] = [
        "All agreed deliverables accepted by the sponsor",
        "Project completes within the approved budget",
        "Project completes on or before the target end date",
        "Stakeholders report satisfaction with the outcome",
    ]

    base['risks'] = [
        {"name": "Scope creep", "mitigation": "Change control process with sponsor sign-off"},
        {"name": "Resource availability", "mitigation": "Confirm key contributors up front; identify backups"},
        {"name": "Schedule slippage", "mitigation": "Weekly progress tracking and buffer in the plan"},
    ]

    base['assumptions'] = [
        "The team has the skills required to deliver the project",
        "Budget approval is in place for the planned scope",
        "Key stakeholders are available for decisions when needed",
    ]

    return base


CHARTER_SYSTEM_PROMPT = """You are a senior project manager helping a user build a project charter from minimal input.

Given the project name, description and optional dates/budget, produce a SMART charter outline as JSON ONLY (no markdown, no prose, no code fences).

The JSON must have exactly these keys, each a list of short strings:
- "objectives": 3-5 measurable objectives
- "scope_in": 4-6 things explicitly in scope
- "scope_out": 2-4 things explicitly out of scope
- "deliverables": 3-5 concrete deliverables
- "milestones": list of {name, weeks} (weeks = week offset from start)
- "success_criteria": 3-5 acceptance criteria
- "risks": list of {name, mitigation}
- "assumptions": 2-4 assumptions

Tailor every section to the specific project. Keep entries concise and specific. Output valid JSON only."""


def _ai_charter_outline(name, description, start_date=None, end_date=None, budget=None):
    """Call the configured LLM to draft a tailored charter outline."""
    user_brief = f"Project name: {name}\nDescription: {description or '(none provided)'}"
    if start_date:
        user_brief += f"\nStart date: {start_date}"
    if end_date:
        user_brief += f"\nTarget end date: {end_date}"
    if budget is not None:
        user_brief += f"\nIndicative budget: {budget}"

    client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    messages = [
        {"role": "system", "content": CHARTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_brief},
    ]

    reply = ''
    models_to_try = [AI_MODEL] + [m for m in FALLBACK_MODELS if m != AI_MODEL]
    for try_model in models_to_try:
        try:
            extra_headers = {}
            if 'openrouter' in AI_BASE_URL:
                extra_headers = {
                    'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                    'X-Title': 'Project Manager',
                }
            response = client.chat.completions.create(
                model=try_model,
                messages=messages,
                max_tokens=1400,
                temperature=0.7,
                extra_headers=extra_headers or None,
            )
            reply = response.choices[0].message.content or ''
            if reply.strip():
                break
        except Exception as e:
            logger.warning("Charter AI call failed for model %s: %s", try_model, e)
            continue

    if not reply.strip():
        raise RuntimeError("AI returned no response")

    # Strip any accidental markdown fences
    cleaned = reply.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('```', 2)[1] if cleaned.count('```') >= 2 else cleaned
        if cleaned.startswith('json'):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip('` \n')

    outline = json.loads(cleaned)
    # Normalise to expected keys
    result = _empty_outline()
    for k in CHARTER_KEYS:
        if k in outline and isinstance(outline[k], list):
            result[k] = outline[k]
    return result


def generate_charter_outline(name, description, start_date=None, end_date=None, budget=None):
    """Generate a charter outline, using AI if configured, else the template."""
    if is_ai_configured():
        try:
            return _ai_charter_outline(name, description, start_date, end_date, budget)
        except Exception as e:
            logger.warning("AI charter generation failed (%s); falling back to template.", e)
    return _template_charter_outline(name, description, start_date, end_date, budget)


# ─── Stakeholder suggestions ───────────────────────────────────────────────

def _template_stakeholders(name, description, outline=None):
    """Deterministic starter stakeholder list tied to the charter."""
    stakeholders = [
        {"name": "Project Sponsor", "role": "Executive sponsor", "organization": "Leadership", "interest": 5, "influence": 5, "notes": "Funds the project; approves scope changes"},
        {"name": "Project Manager", "role": "Delivery lead", "organization": "Project team", "interest": 5, "influence": 4, "notes": "Owns the plan and delivery"},
        {"name": "Core Team", "role": "Delivery team", "organization": "Project team", "interest": 5, "influence": 3, "notes": "Does the work day-to-day"},
        {"name": "End Users", "role": "Users / customers", "organization": "Business", "interest": 4, "influence": 2, "notes": "Receive the outcome; care about usability"},
        {"name": "Finance", "role": "Budget owner", "organization": "Finance", "interest": 2, "influence": 4, "notes": "Controls budget and approvals"},
        {"name": "External Regulator", "role": "Compliance", "organization": "External", "interest": 1, "influence": 5, "notes": "Sets constraints; monitor with minimal effort"},
    ]
    if outline:
        for risk in outline.get('risks', [])[:2]:
            if isinstance(risk, dict) and risk.get('name'):
                stakeholders.append({
                    "name": f"Risk owner: {risk['name']}",
                    "role": "Risk owner",
                    "organization": "Project team",
                    "interest": 4,
                    "influence": 3,
                    "notes": f"Mitigates: {risk.get('mitigation', '')}",
                })
    return stakeholders


STAKEHOLDER_SYSTEM_PROMPT = """You are a senior project manager helping identify stakeholders for a project charter.

Given the project name, description and charter outline, suggest 5-8 realistic stakeholders as JSON ONLY (no markdown, no prose).

Each stakeholder is an object with keys:
- name: short label for the stakeholder (e.g. "Project Sponsor", "Finance Director")
- role: their role/title
- organization: which group they belong to
- interest: integer 1-5 (1 = very low interest, 5 = very high)
- influence: integer 1-5 (1 = very low power, 5 = very high)
- notes: one short sentence on how to engage them

Output a JSON array only."""


def _ai_stakeholders(name, description, outline=None):
    user_brief = f"Project name: {name}\nDescription: {description or '(none provided)'}"
    if outline:
        # Trim the outline to keep the prompt small
        summary = {k: outline.get(k, []) for k in ('objectives', 'deliverables', 'risks')}
        user_brief += f"\nCharter summary (JSON): {json.dumps(summary, default=str)[:800]}"

    client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    messages = [
        {"role": "system", "content": STAKEHOLDER_SYSTEM_PROMPT},
        {"role": "user", "content": user_brief},
    ]

    reply = ''
    models_to_try = [AI_MODEL] + [m for m in FALLBACK_MODELS if m != AI_MODEL]
    for try_model in models_to_try:
        try:
            extra_headers = {}
            if 'openrouter' in AI_BASE_URL:
                extra_headers = {
                    'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                    'X-Title': 'Project Manager',
                }
            response = client.chat.completions.create(
                model=try_model,
                messages=messages,
                max_tokens=900,
                temperature=0.6,
                extra_headers=extra_headers or None,
            )
            reply = response.choices[0].message.content or ''
            if reply.strip():
                break
        except Exception as e:
            logger.warning("Stakeholder AI call failed for model %s: %s", try_model, e)
            continue

    if not reply.strip():
        raise RuntimeError("AI returned no response")

    cleaned = reply.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('```', 2)[1] if cleaned.count('```') >= 2 else cleaned
        if cleaned.startswith('json'):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip('` \n')

    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise RuntimeError("AI did not return a stakeholder list")
    return parsed


def suggest_stakeholders(name, description, outline=None):
    """Suggest a starter stakeholder list, using AI if configured else template."""
    if is_ai_configured():
        try:
            return _ai_stakeholders(name, description, outline)
        except Exception as e:
            logger.warning("AI stakeholder suggestion failed (%s); falling back to template.", e)
    return _template_stakeholders(name, description, outline)
