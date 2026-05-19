import os
import json
import re
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

# Configuration via environment variables:
#   AI_API_KEY    — required, your API key
#   AI_MODEL      — model name (default: meta-llama/llama-4-scout:free)
#   AI_BASE_URL   — OpenAI-compatible endpoint (default: https://openrouter.ai/api/v1)
AI_API_KEY = os.environ.get('AI_API_KEY', '')
AI_BASE_URL = os.environ.get('AI_BASE_URL', 'https://openrouter.ai/api/v1')
AI_MODEL = os.environ.get('AI_MODEL', 'openai/gpt-oss-120b:free')

# Fallback models if the primary is rate-limited or returns empty
FALLBACK_MODELS = [
    'nvidia/nemotron-3-super-120b-a12b:free',
    'qwen/qwen3-next-80b-a3b-instruct:free',
]


def is_ai_configured():
    """Check if AI API key is available."""
    return bool(AI_API_KEY)


def get_ai_config():
    """Get AI configuration from environment variables."""
    return AI_API_KEY, AI_BASE_URL, AI_MODEL


def get_ai_status():
    """Get AI status for the UI."""
    configured = bool(AI_API_KEY)
    provider = 'OpenRouter' if 'openrouter' in AI_BASE_URL else ('OpenAI' if 'api.openai' in AI_BASE_URL else 'Custom')
    return {
        'configured': configured,
        'model': AI_MODEL if configured else None,
        'type': provider.lower() if configured else None,
        'provider': provider,
    }


def _start_server_placeholder():
    """No longer needed — kept for route compatibility."""
    return None


def get_project_context():
    """Build a snapshot of current project data for AI context, including role-based workload analysis."""
    from app.models import Member, Milestone, Task, BudgetCategory, Contribution
    from datetime import date

    ctx = {}

    members = Member.query.all()
    member_data = []
    for m in members:
        active_tasks = [t for t in m.tasks if t.status != 'done']
        completed_tasks = [t for t in m.tasks if t.status == 'done']
        hours = sum(c.hours for c in m.contributions)
        member_data.append({
            'name': m.name,
            'role': m.role or 'No role',
            'email': m.email or '',
            'tasks_total': m.task_count,
            'tasks_done': m.completed_task_count,
            'tasks_active': len(active_tasks),
            'hours_logged': hours,
            'active_task_titles': [t.title for t in active_tasks],
            'overdue_tasks': [t.title for t in active_tasks if t.due_date and t.due_date < date.today()],
            'workload_score': len(active_tasks) * 2 + hours,
        })
    ctx['members'] = member_data

    # Role-based workload summary
    role_summary = {}
    for md in member_data:
        role = md['role']
        if role not in role_summary:
            role_summary[role] = {'members': [], 'total_active': 0, 'total_hours': 0}
        role_summary[role]['members'].append(md['name'])
        role_summary[role]['total_active'] += md['tasks_active']
        role_summary[role]['total_hours'] += md['hours_logged']
    ctx['role_summary'] = role_summary

    # Least busy members per role
    least_busy = {}
    for role, info in role_summary.items():
        role_members = [m for m in member_data if m['role'] == role]
        if role_members:
            least_busy[role] = min(role_members, key=lambda x: x['workload_score'])['name']
    ctx['least_busy_by_role'] = least_busy

    milestones = Milestone.query.order_by(Milestone.deadline).all()
    ctx['milestones'] = [{
        'name': m.name, 'description': m.description or '', 'status': m.status, 'progress': m.progress,
        'start': m.start_date.isoformat() if m.start_date else None,
        'deadline': m.deadline.isoformat(),
        'is_overdue': m.deadline < date.today() and m.status != 'done',
        'tasks': [{'title': t.title, 'status': t.status, 'priority': t.priority,
                   'assignee': t.assignee.name if t.assignee else None,
                   'assignee_role': t.assignee.role if t.assignee else None,
                   'due': t.due_date.isoformat() if t.due_date else None} for t in m.tasks]
    } for m in milestones]

    tasks = Task.query.all()
    ctx['tasks'] = [{
        'title': t.title, 'description': t.description or '', 'status': t.status, 'priority': t.priority,
        'assignee': t.assignee.name if t.assignee else None,
        'assignee_role': t.assignee.role if t.assignee else 'Unassigned',
        'milestone': t.milestone.name if t.milestone else None,
        'due': t.due_date.isoformat() if t.due_date else None,
        'is_overdue': t.due_date < date.today() if t.due_date and t.status != 'done' else False,
    } for t in tasks]

    categories = BudgetCategory.query.all()
    ctx['budget'] = {
        'total_allocated': sum(c.allocated for c in categories),
        'total_spent': sum(c.spent for c in categories),
        'categories': [{
            'name': c.name, 'allocated': c.allocated, 'spent': c.spent,
            'remaining': c.remaining,
            'usage_pct': round(c.spent / c.allocated * 100) if c.allocated > 0 else 0,
            'expenses': [{'desc': e.description, 'amount': e.amount, 'paid_by': e.paid_by} for e in c.expenses]
        } for c in categories]
    }

    contribs = Contribution.query.order_by(Contribution.date.desc()).limit(10).all()
    ctx['recent_contributions'] = [{
        'member': c.member.name, 'role': c.member.role or 'No role',
        'hours': c.hours, 'description': c.description, 'date': c.date.isoformat()
    } for c in contribs]

    ctx['today'] = date.today().isoformat()

    # Proactive insights
    insights = []
    overdue_tasks = [t for t in tasks if t.due_date and t.due_date < date.today() and t.status != 'done']
    if overdue_tasks:
        insights.append(f"{len(overdue_tasks)} overdue task(s): {', '.join(t.title for t in overdue_tasks[:5])}")
    unassigned = [t for t in tasks if t.assignee is None and t.status != 'done']
    if unassigned:
        insights.append(f"{len(unassigned)} unassigned task(s): {', '.join(t.title for t in unassigned[:5])}")
    overloaded = [m for m in member_data if m['tasks_active'] >= 5]
    if overloaded:
        insights.append(f"Overloaded member(s): {', '.join(m['name'] for m in overloaded)}")
    ctx['insights'] = insights

    return ctx


SYSTEM_PROMPT = """You are a smart project management assistant with FULL CONTROL over the dashboard. You can actually create tasks, add members, assign work, update statuses, and more — your changes are REAL and take effect immediately.

CRITICAL RULE: When you want to change any data (add, update, delete, assign, etc.), you MUST output an ACTION BLOCK. Without an action block, NOTHING will actually happen — you will just be describing changes that don't take effect.

CORRECT example — this actually creates a task and assigns it:
I'll create a risk assessment task and assign it to Alex, our Risk Manager.
<<<ACTION>>>
action_type: add_task
params:
  title: Risk assessment for vendor contract
  priority: high
  due_date: 2026-06-15
  assignee_name: Alex
<<<END_ACTION>>>

WRONG — this does NOTHING (no action block, so the task is NOT created):
"I've created a task called Risk Assessment and assigned it to Alex."
(No action block = no change made)

ALWAYS use action blocks for ANY change to the project data. This includes: adding, updating, deleting, assigning, or logging.

ROLE-BASED ASSIGNMENT RULES:
- Always consider a member's ROLE when assigning tasks. For example:
  - A "Risk Manager" should handle risk assessment and mitigation tasks
  - A "Developer" should handle coding and technical tasks
  - A "Designer" should handle UI/UX and visual tasks
  - A "QA Lead" should handle testing and quality assurance tasks
- When a task matches a member's role, assign it to them even if they have a slightly higher workload
- When no role match exists, assign to the member with the lowest workload
- Always explain your assignment reasoning: mention WHY that person is the best fit (role match + workload)

PROACTIVE BEHAVIOR:
- When the user describes a need, create the tasks AND assignments with action blocks
- For example, "we need to handle two risky decisions" → create two risk tasks with action blocks and assign them to the Risk Manager
- When creating tasks, always set appropriate priority and due dates
- If a milestone is overdue, update its status with an action block

WORKLOAD ANALYSIS:
- When discussing team members, show their workload: active tasks, completed tasks, hours logged, and role
- Suggest redistributing work when someone is overloaded

Supported action types and their params:
- add_member: name, role (optional), email (optional)
- update_member: member_name, name (optional), role (optional), email (optional)
- add_task: title, description (optional), priority (optional, default medium), due_date (optional, YYYY-MM-DD), milestone_name (optional), assignee_name (optional)
- update_task: task_title, title (optional), description (optional), priority (optional, low/medium/high), assignee_name (optional), milestone_name (optional), due_date (optional, YYYY-MM-DD)
- update_task_status: task_title, status (todo/in_progress/done)
- add_milestone: name, deadline (YYYY-MM-DD), start_date (optional, YYYY-MM-DD)
- update_milestone_status: milestone_name, status (upcoming/in_progress/done/overdue)
- assign_task: task_title, member_name
- set_task_priority: task_title, priority (low/medium/high)
- add_category: name, allocated (number)
- add_expense: description, amount (number), category_name, paid_by (optional)
- log_hours: member_name, hours (number), description (optional)
- remove_member: name
- remove_task: title
- remove_milestone: name
- remove_category: name

You can include multiple actions in one response. Always include the action block so your changes actually take effect.
If the user just asks a question (no changes needed), answer from the project data — no action block needed.
Keep responses concise and practical.
"""


def chat_with_ai(user_message, conversation_history=None):
    """Send message to AI and return (text_response, actions_list)."""
    api_key, base_url, model = get_ai_config()

    if not api_key:
        return "AI is not configured. Set the AI_API_KEY environment variable.", []

    client = OpenAI(api_key=api_key, base_url=base_url)

    # Build context
    project_data = get_project_context()
    context_msg = f"Current project data:\n{json.dumps(project_data, indent=2, default=str)}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_msg},
    ]

    if conversation_history:
        # Filter out entries with None content (some models return None)
        valid = [m for m in conversation_history[-10:] if m.get('content')]
        messages.extend(valid)

    messages.append({"role": "user", "content": user_message})

    import time
    # Try primary model, then fallbacks if rate-limited or empty response
    reply = ''
    used_model = model
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None

    for attempt, try_model in enumerate(models_to_try):
        try:
            extra_headers = {}
            if 'openrouter' in base_url:
                extra_headers = {
                    'HTTP-Referer': 'https://project-manager-vqcr.onrender.com',
                    'X-Title': 'Project Manager',
                }
            response = client.chat.completions.create(
                model=try_model,
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
                extra_headers=extra_headers or None,
            )
            reply = response.choices[0].message.content or ''
            if reply.strip():
                used_model = try_model
                if attempt > 0:
                    logger.info("Fallback to %s succeeded (primary %s failed)", try_model, model)
                break
            logger.warning("Empty response from model %s (attempt %d), trying fallback", try_model, attempt + 1)
        except Exception as e:
            last_error = str(e)
            # If rate-limited, try next model immediately
            if '429' in last_error or 'rate' in last_error.lower():
                logger.warning("Model %s rate-limited (attempt %d), trying next", try_model, attempt + 1)
                continue
            logger.warning("Model %s failed: %s (attempt %d), trying fallback", try_model, e, attempt + 1)
            continue

    if not reply.strip():
        if last_error:
            return f"AI is temporarily unavailable (all models rate-limited). Last error: {last_error}. Please try again in a minute.", []
        return "AI returned an empty response. Please try again.", []

    # Extract actions from reply
    actions = []
    action_blocks = re.findall(r'<<<ACTION>>>(.+?)<<<END_ACTION>>>', reply, re.DOTALL)
    for block in action_blocks:
        action = parse_action_block(block.strip())
        if action:
            actions.append(action)

    # Clean the reply text (remove action blocks)
    clean_reply = re.sub(r'<<<ACTION>>>.+?<<<END_ACTION>>>', '', reply, flags=re.DOTALL).strip()

    return clean_reply, actions


def parse_action_block(block):
    """Parse an action block into action_type and params dict."""
    try:
        lines = block.strip().split('\n')
        action_type = None
        params = {}
        for line in lines:
            line = line.strip()
            if line.startswith('action_type:'):
                action_type = line.split(':', 1)[1].strip()
            elif ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                try:
                    if '.' in val:
                        val = float(val)
                    else:
                        val = int(val)
                except (ValueError, TypeError):
                    pass
                params[key] = val
        if action_type:
            return {'action_type': action_type, 'params': params}
    except Exception:
        pass
    return None


def execute_action(action):
    """Execute a parsed action against the database. Returns a result message."""
    from app.models import Member, Milestone, Task, BudgetCategory, Expense, Contribution
    from app import db
    from datetime import datetime, date

    def clean_param(val):
        """Clean parameter value - treat 'null', 'none', 'n/a' as None."""
        if isinstance(val, str) and val.lower() in ('null', 'none', 'n/a', 'nil', 'undefined'):
            return None
        return val

    atype = action['action_type']
    params = {k: clean_param(v) for k, v in action['params'].items()}

    try:
        if atype == 'add_member':
            m = Member(name=params.get('name', ''), email=params.get('email', ''), role=params.get('role', ''))
            db.session.add(m)
            db.session.commit()
            return f"Added member **{m.name}**!"

        elif atype == 'add_task':
            task = Task(
                title=params.get('title', ''),
                priority=params.get('priority', 'medium'),
                due_date=datetime.strptime(params['due_date'], '%Y-%m-%d').date() if params.get('due_date') else None,
            )
            if params.get('milestone_name'):
                ms = Milestone.query.filter(Milestone.name.ilike(f'%{params["milestone_name"]}%')).first()
                if ms:
                    task.milestone_id = ms.id
            if params.get('assignee_name'):
                member = Member.query.filter(Member.name.ilike(f'%{params["assignee_name"]}%')).first()
                if member:
                    task.assignee_id = member.id
            db.session.add(task)
            db.session.commit()
            return f"Added task **{task.title}**!"

        elif atype == 'add_milestone':
            deadline = datetime.strptime(params['deadline'], '%Y-%m-%d').date()
            start = datetime.strptime(params['start_date'], '%Y-%m-%d').date() if params.get('start_date') else None
            ms = Milestone(name=params.get('name', ''), deadline=deadline, start_date=start)
            db.session.add(ms)
            db.session.commit()
            return f"Added milestone **{ms.name}** (deadline: {deadline.strftime('%b %d, %Y')})!"

        elif atype == 'add_category':
            cat = BudgetCategory(name=params.get('name', ''), allocated=float(params.get('allocated', 0)))
            db.session.add(cat)
            db.session.commit()
            return f"Added category **{cat.name}** with ${cat.allocated:.2f}!"

        elif atype == 'add_expense':
            cat = BudgetCategory.query.filter(BudgetCategory.name.ilike(f'%{params.get("category_name", "")}%')).first()
            if not cat:
                cats = BudgetCategory.query.all()
                return f"Category not found. Available: {', '.join(c.name for c in cats)}" if cats else "No budget categories yet."
            exp = Expense(
                description=params.get('description', ''),
                amount=float(params.get('amount', 0)),
                category_id=cat.id,
                paid_by=params.get('paid_by', ''),
                date=date.today()
            )
            db.session.add(exp)
            db.session.commit()
            return f"Added expense **{exp.description}** (${exp.amount:.2f}) to **{cat.name}**!"

        elif atype == 'log_hours':
            member = Member.query.filter(Member.name.ilike(f'%{params.get("member_name", "")}%')).first()
            if not member:
                return "Member not found."
            c = Contribution(
                member_id=member.id,
                hours=float(params.get('hours', 0)),
                description=params.get('description', ''),
                date=date.today()
            )
            db.session.add(c)
            db.session.commit()
            return f"Logged **{c.hours}h** for **{member.name}**!"

        elif atype == 'update_task':
            task = Task.query.filter(Task.title.ilike(f'%{params.get("task_title", "")}%')).first()
            if not task:
                return "Task not found."
            if params.get('priority'):
                task.priority = params['priority']
            if params.get('description'):
                task.description = params['description']
            if params.get('due_date'):
                task.due_date = datetime.strptime(params['due_date'], '%Y-%m-%d').date()
            if params.get('assignee_name'):
                member = Member.query.filter(Member.name.ilike(f'%{params["assignee_name"]}%')).first()
                if member:
                    task.assignee_id = member.id
                else:
                    return f"Member '{params['assignee_name']}' not found for task update."
            if params.get('milestone_name'):
                ms = Milestone.query.filter(Milestone.name.ilike(f'%{params["milestone_name"]}%')).first()
                if ms:
                    task.milestone_id = ms.id
            db.session.commit()
            changes = []
            if params.get('priority'):
                changes.append(f"priority → {task.priority}")
            if params.get('assignee_name') and task.assignee:
                changes.append(f"assigned to → {task.assignee.name}")
            if params.get('milestone_name') and task.milestone:
                changes.append(f"milestone → {task.milestone.name}")
            if params.get('due_date'):
                changes.append(f"due → {task.due_date.strftime('%b %d, %Y')}")
            return f"Updated task **{task.title}** ({', '.join(changes)})" if changes else f"Updated task **{task.title}**."

        elif atype == 'update_member':
            member = Member.query.filter(Member.name.ilike(f'%{params.get("member_name", "")}%')).first()
            if not member:
                return "Member not found."
            if params.get('name'):
                member.name = params['name']
            if params.get('role'):
                member.role = params['role']
            if params.get('email'):
                member.email = params['email']
            db.session.commit()
            return f"Updated member **{member.name}** (Role: {member.role or 'No role'})"

        elif atype == 'set_task_priority':
            task = Task.query.filter(Task.title.ilike(f'%{params.get("task_title", "")}%')).first()
            if not task:
                return "Task not found."
            task.priority = params.get('priority', task.priority)
            db.session.commit()
            return f"Set **{task.title}** priority to **{task.priority}**!"

        elif atype == 'assign_task':
            task = Task.query.filter(Task.title.ilike(f'%{params.get("task_title", "")}%')).first()
            member = Member.query.filter(Member.name.ilike(f'%{params.get("member_name", "")}%')).first()
            if not task:
                return "Task not found."
            if not member:
                return "Member not found."
            task.assignee_id = member.id
            db.session.commit()
            return f"Assigned **{task.title}** to **{member.name}**!"

        elif atype == 'update_task_status':
            task = Task.query.filter(Task.title.ilike(f'%{params.get("task_title", "")}%')).first()
            if not task:
                return "Task not found."
            task.status = params.get('status', task.status)
            db.session.commit()
            return f"Marked **{task.title}** as **{task.status}**!"

        elif atype == 'update_milestone_status':
            ms = Milestone.query.filter(Milestone.name.ilike(f'%{params.get("milestone_name", "")}%')).first()
            if not ms:
                return "Milestone not found."
            ms.status = params.get('status', ms.status)
            db.session.commit()
            return f"Marked milestone **{ms.name}** as **{ms.status}**!"

        elif atype == 'remove_member':
            m = Member.query.filter(Member.name.ilike(f'%{params.get("name", "")}%')).first()
            if not m:
                return "Member not found."
            Task.query.filter_by(assignee_id=m.id).update({'assignee_id': None})
            db.session.delete(m)
            db.session.commit()
            return f"Removed member **{m.name}**!"

        elif atype == 'remove_task':
            t = Task.query.filter(Task.title.ilike(f'%{params.get("title", "")}%')).first()
            if not t:
                return "Task not found."
            db.session.delete(t)
            db.session.commit()
            return f"Deleted task **{t.title}**!"

        elif atype == 'remove_milestone':
            ms = Milestone.query.filter(Milestone.name.ilike(f'%{params.get("name", "")}%')).first()
            if not ms:
                return "Milestone not found."
            Task.query.filter_by(milestone_id=ms.id).update({'milestone_id': None})
            db.session.delete(ms)
            db.session.commit()
            return f"Deleted milestone **{ms.name}**!"

        elif atype == 'remove_category':
            cat = BudgetCategory.query.filter(BudgetCategory.name.ilike(f'%{params.get("name", "")}%')).first()
            if not cat:
                return "Category not found."
            db.session.delete(cat)
            db.session.commit()
            return f"Deleted category **{cat.name}**!"

        else:
            return f"Unknown action: {atype}"

    except Exception as e:
        db.session.rollback()
        return f"Error executing {atype}: {str(e)}"
