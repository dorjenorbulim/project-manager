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

# Render's free web services time out requests at ~30s, and OpenRouter's
# free models often take 15-25s. Cap each AI attempt so a slow model falls
# back to the instant local template instead of 500ing the request.
AI_TIMEOUT = float(os.environ.get('AI_TIMEOUT', '12'))


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
    # On Render's free tier the request timeout is ~30s, so we only attempt
    # the primary model once. If it times out or fails, the caller falls
    # back to the instant local template generator.
    try:
        extra_headers = {}
        if 'openrouter' in AI_BASE_URL:
            extra_headers = {
                'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                'X-Title': 'Project Manager',
            }
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            max_tokens=1400,
            temperature=0.7,
            extra_headers=extra_headers or None,
            timeout=AI_TIMEOUT,
        )
        reply = response.choices[0].message.content or ''
    except Exception as e:
        logger.warning("Charter AI call failed for model %s: %s", AI_MODEL, e)
        raise RuntimeError("AI timed out or failed")

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
            # Milestones and risks must be dicts; coerce or skip malformed entries
            if k == 'milestones':
                for item in outline[k]:
                    if isinstance(item, dict) and item.get('name'):
                        result[k].append({'name': str(item['name']), 'weeks': int(item.get('weeks', 0)) if str(item.get('weeks','0')).isdigit() else 0})
            elif k == 'risks':
                for item in outline[k]:
                    if isinstance(item, dict) and item.get('name'):
                        result[k].append({'name': str(item['name']), 'mitigation': str(item.get('mitigation', ''))})
            else:
                result[k] = [str(x) for x in outline[k] if x]
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
    # Single attempt only - see comment in _ai_charter_outline.
    try:
        extra_headers = {}
        if 'openrouter' in AI_BASE_URL:
            extra_headers = {
                'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                'X-Title': 'Project Manager',
            }
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            max_tokens=900,
            temperature=0.6,
            extra_headers=extra_headers or None,
            timeout=AI_TIMEOUT,
        )
        reply = response.choices[0].message.content or ''
    except Exception as e:
        logger.warning("Stakeholder AI call failed for model %s: %s", AI_MODEL, e)
        raise RuntimeError("AI timed out or failed")

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


# ─── Project proposal scoring (weighted scoring model) ────────────────────

PROPOSAL_SYSTEM_PROMPT = """You are a senior project portfolio manager using a weighted scoring model to evaluate project proposals.

Score each proposal on a 1-10 scale across six criteria. Be realistic and discriminating - do not default to middle scores. Use the full 1-10 range based on evidence in the description.

CRITERIA AND SCORING RUBRIC (1-10):

1. strategic_fit (weight 25%): How well does this align with typical organisational strategy?
   1-2: No clear strategic link, vanity project, "nice to have"
   3-4: Tangential to strategy, unclear business driver
   5-6: Moderately aligned, supports some goals indirectly
   7-8: Directly supports a stated strategic goal (growth, efficiency, compliance, customer)
   9-10: Core strategic imperative, board-level priority, competitive necessity

2. feasibility (weight 15%): Can a typical team realistically deliver this?
   1-2: Requires unknown technology, novel R&D, or capabilities the org doesn't have
   3-4: Significant unknowns, needs new skills/hiring, complex integration
   5-6: Achievable with some stretch, mostly known approaches, minor unknowns
   7-8: Standard delivery, proven approaches, team has relevant experience
   9-10: Straightforward, well-understood, minimal risk of delivery failure

3. business_value (weight 25%): What is the potential return / benefit?
   1-2: Negligible measurable benefit, cosmetic, internal preference
   3-4: Minor efficiency gain, small audience, hard to measure
   5-6: Moderate value, measurable efficiency or revenue, affects one department
   7-8: Significant value, clear ROI, affects multiple departments or customers
   9-10: Transformative, major revenue/cost/efficiency impact, organisation-wide

4. risk_level (weight 15%): INVERTED - 10 = very low risk, 1 = very high risk
   1-2: High risk - regulatory, security, unproven tech, political sensitivity
   3-4: Elevated risk - compliance concerns, dependency on external parties, new domain
   5-6: Moderate risk - some unknowns but manageable with standard mitigation
   7-8: Low risk - well-understood domain, proven patterns, controllable
   9-10: Very low risk - routine, no external dependencies, fully within control

5. cost_efficiency (weight 10%): INVERTED - 10 = very low cost, 1 = very high cost
   1-2: Very expensive - large infrastructure, enterprise licenses, big team, long timeline
   3-4: Costly - significant new investment, multiple licenses, extended duration
   5-6: Moderate cost - standard budget, some new spend, reasonable timeline
   7-8: Cost-efficient - reuses existing resources, incremental, short timeline
   9-10: Very low cost - minimal spend, internal only, quick to deliver

6. urgency (weight 10%): Is there a time pressure or window of opportunity?
   1-2: No time pressure, can wait indefinitely
   3-4: Slight pressure, eventual need but no deadline
   5-6: Moderate urgency, should happen this year, some competitive pressure
   7-8: Time-sensitive, clear deadline, competitive window closing
   9-10: Critical urgency, regulatory deadline, immediate competitive threat

For each criterion provide a one-sentence rationale referencing specific evidence from the description. Then give an overall recommendation (1-2 sentences) that references the weighted strengths and weaknesses.

Output JSON ONLY (no markdown, no prose):
{
  "strategic_fit": <1-10>, "feasibility": <1-10>, "business_value": <1-10>,
  "risk_level": <1-10>, "cost_efficiency": <1-10>, "urgency": <1-10>,
  "rationale": {"strategic_fit": "...", "feasibility": "...", "business_value": "...", "risk_level": "...", "cost_efficiency": "...", "urgency": "..."},
  "recommendation": "..."
}"""


def _template_score_proposal(title, description):
    """Deterministic heuristic scorer for when no AI key is configured.
    Uses multi-signal text analysis to produce realistic, differentiated scores."""
    text = (title + ' ' + (description or '')).lower()
    desc_len = len(description or '')

    def _score(positive_kw, negative_kw, context_kw=None, base=5):
        """Multi-signal scoring: keyword presence + density + context signals."""
        score = base
        pos_hits = sum(1 for kw in positive_kw if kw in text)
        neg_hits = sum(1 for kw in negative_kw if kw in text)
        # Each positive keyword adds up to 1, capped at +3 from keywords
        score += min(pos_hits, 3)
        # Each negative keyword subtracts up to 1, capped at -3
        score -= min(neg_hits, 3)
        # Context adjustments
        if context_kw:
            ctx_hits = sum(1 for kw in context_kw if kw in text)
            if ctx_hits > 2:
                score += 1  # strong context signal
        # Length signal: very short descriptions are vaguer (less confidence)
        if desc_len < 30:
            score -= 1
        return max(1, min(10, score))

    # Strategic fit: keywords indicating strategic drivers
    strategic_fit = _score(
        ['strategic', 'growth', 'competitive', 'market', 'customer', 'revenue',
         'digital', 'transform', 'mission', 'vision', 'core', 'priority', 'board',
         'compliance', 'regulatory', 'mandate', 'initiative'],
        ['experiment', 'nice to have', 'side', 'hobby', 'pet project', 'exploratory',
         'maybe', 'someday', 'if we have time'],
        base=5,
    )

    # Feasibility: indicators of deliverability
    feasibility = _score(
        ['existing', 'platform', 'api', 'integration', 'upgrade', 'website', 'app',
         'standard', 'proven', 'established', 'internal', 'team', 'current',
         'extend', 'enhance', 'update', 'replace', 'migrate'],
        ['research', 'unknown', 'novel', 'breakthrough', 'r&d', 'experimental',
         'cutting edge', 'new technology', 'never done', 'innovative', 'ai',
         'machine learning', 'blockchain', 'unproven'],
        base=5,
    )

    # Business value: ROI / revenue / efficiency signals
    business_value = _score(
        ['revenue', 'growth', 'efficiency', 'automation', 'scale', 'transform',
         'retention', 'cost saving', 'productivity', 'profit', 'margin', 'roi',
         'customer satisfaction', 'competitive advantage', 'market share',
         'impact', 'benefit'],
        ['minor', 'small', 'cosmetic', 'cleanup', 'refactor', 'tidy', 'nice',
         'polish', 'aesthetic', 'no clear', 'no business', 'unclear',
         'no measurable', 'exploratory', 'research', 'r&d'],
        base=5,
    )

    # Risk level (inverted: 10 = low risk)
    risk_level = _score(
        ['proven', 'standard', 'established', 'existing', 'stable', 'routine',
         'internal', 'controlled', 'simple', 'well-known', 'documented'],
        ['experimental', 'cutting edge', 'regulatory', 'compliance', 'security',
         'unknown', 'external', 'third party', 'vendor', 'political', 'sensitive',
         'privacy', 'gdpr', 'data breach'],
        base=5,
    )

    # Cost efficiency (inverted: 10 = low cost)
    cost_efficiency = _score(
        ['existing', 'reuse', 'open source', 'internal', 'small', 'incremental',
         'quick', 'minimal', 'lightweight', 'simple', 'reuse', 'extend'],
        ['enterprise', 'license', 'infrastructure', 'large scale', 'new platform',
         'expensive', 'big', 'major', 'transformation', ' overhaul', 'rebuild',
         'consultant', 'vendor', 'cloud migration'],
        base=5,
    )

    # Urgency: time pressure signals
    urgency = _score(
        ['urgent', 'deadline', 'asap', 'immediate', 'critical', 'now', 'this quarter',
         'this year', 'window', 'opportunity', 'competitive', 'losing', 'falling behind',
         'regulatory deadline', 'compliance deadline', 'compliance', 'expire',
         'mandate', 'required', 'must'],
        ['someday', 'eventually', 'when we have time', 'no rush', 'future', 'long term',
         'nice to have', 'backlog', 'low priority', 'no real deadline', 'no deadline',
         'exploratory', 'no clear'],
        base=4,  # default lower - most proposals aren't urgent
    )

    rationales = {
        'strategic_fit': f"{'Strong' if strategic_fit >= 7 else 'Moderate' if strategic_fit >= 5 else 'Weak'} strategic signal - {'clear strategic driver keywords present' if strategic_fit >= 7 else 'limited strategic language detected' if strategic_fit >= 5 else 'no clear strategic alignment in description'}",
        'feasibility': f"{'Highly feasible' if feasibility >= 7 else 'Achievable' if feasibility >= 5 else 'Challenging'} - {'standard approaches and existing capabilities referenced' if feasibility >= 7 else 'mostly known but some unknowns' if feasibility >= 5 else 'significant unknowns or novel elements detected'}",
        'business_value': f"{'High value' if business_value >= 7 else 'Moderate value' if business_value >= 5 else 'Low value'} - {'clear revenue/efficiency/benefit signals' if business_value >= 7 else 'some benefit indicators' if business_value >= 5 else 'limited measurable benefit in description'}",
        'risk_level': f"{'Low risk' if risk_level >= 7 else 'Moderate risk' if risk_level >= 5 else 'High risk'} - {'well-understood domain with proven patterns' if risk_level >= 7 else 'some risk factors present' if risk_level >= 5 else 'regulatory/technical/external risk signals detected'}",
        'cost_efficiency': f"{'Cost-efficient' if cost_efficiency >= 7 else 'Moderate cost' if cost_efficiency >= 5 else 'Potentially costly'} - {'reuses existing resources, incremental scope' if cost_efficiency >= 7 else 'standard budget expected' if cost_efficiency >= 5 else 'major investment or new infrastructure likely'}",
        'urgency': f"{'Time-critical' if urgency >= 7 else 'Moderate urgency' if urgency >= 5 else 'Low urgency'} - {'clear deadline or competitive pressure' if urgency >= 7 else 'some time sensitivity' if urgency >= 5 else 'no clear time pressure in description'}",
    }

    # Calculate weighted total
    weights = {'strategic_fit': 0.25, 'feasibility': 0.15, 'business_value': 0.25,
               'risk_level': 0.15, 'cost_efficiency': 0.10, 'urgency': 0.10}
    scores = {'strategic_fit': strategic_fit, 'feasibility': feasibility,
              'business_value': business_value, 'risk_level': risk_level,
              'cost_efficiency': cost_efficiency, 'urgency': urgency}
    weighted = round(sum(scores[k] * weights[k] for k in weights), 1)
    pct = round(weighted / 10.0 * 100, 1)

    if pct >= 75:
        rec = f"Weighted score {weighted}/10 ({pct}%). Strongly recommended - clear strategic and value alignment with manageable risk."
    elif pct >= 60:
        rec = f"Weighted score {weighted}/10 ({pct}%). Recommended - worthwhile investment with acceptable risk profile."
    elif pct >= 45:
        rec = f"Weighted score {weighted}/10 ({pct}%). Conditional - viable but has notable weaknesses that need addressing before proceeding."
    else:
        rec = f"Weighted score {weighted}/10 ({pct}%). Not recommended in current form - significant gaps in strategic fit, value, or risk profile."

    return {
        'strategic_fit': strategic_fit, 'feasibility': feasibility,
        'business_value': business_value, 'risk_level': risk_level,
        'cost_efficiency': cost_efficiency, 'urgency': urgency,
        'rationale': rationales,
        'recommendation': rec,
    }


def _ai_score_proposal(title, description):
    """Call the configured LLM to score a proposal using the weighted scoring rubric."""
    user_brief = f"Proposal title: {title}\nDescription: {description or '(none)'}"

    client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    messages = [
        {"role": "system", "content": PROPOSAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_brief},
    ]

    reply = ''
    try:
        extra_headers = {}
        if 'openrouter' in AI_BASE_URL:
            extra_headers = {
                'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                'X-Title': 'Project Manager',
            }
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            max_tokens=800,
            temperature=0.4,
            extra_headers=extra_headers or None,
            timeout=AI_TIMEOUT,
        )
        reply = response.choices[0].message.content or ''
    except Exception as e:
        logger.warning("Proposal AI scoring failed for model %s: %s", AI_MODEL, e)
        raise RuntimeError("AI timed out or failed")

    if not reply.strip():
        raise RuntimeError("AI returned no response")

    cleaned = reply.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('```', 2)[1] if cleaned.count('```') >= 2 else cleaned
        if cleaned.startswith('json'):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip('` \n')

    parsed = json.loads(cleaned)
    # Normalise scores to 1-10
    result = {}
    criteria = ['strategic_fit', 'feasibility', 'business_value', 'risk_level', 'cost_efficiency', 'urgency']
    for k in criteria:
        try:
            result[k] = max(1, min(10, int(parsed.get(k, 5))))
        except (ValueError, TypeError):
            result[k] = 5
    result['rationale'] = {}
    if isinstance(parsed.get('rationale'), dict):
        for k in criteria:
            result['rationale'][k] = str(parsed['rationale'].get(k, ''))
    result['recommendation'] = str(parsed.get('recommendation', ''))
    return result


def score_proposal(title, description):
    """Score a proposal using AI if configured, else the heuristic template."""
    if is_ai_configured():
        try:
            return _ai_score_proposal(title, description)
        except Exception as e:
            logger.warning("AI proposal scoring failed (%s); falling back to heuristic.", e)
    return _template_score_proposal(title, description)
