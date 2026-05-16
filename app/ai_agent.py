import os
import json
import re
import logging
import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

# QVAC settings — QVAC standalone always runs on port 11435
QVAC_PORT = 11435
QVAC_BASE_URL = f"http://localhost:{QVAC_PORT}/v1"
QVAC_DEFAULT_MODEL = "qwen2.5"


def is_ai_configured():
    """Check if the QVAC server is running."""
    if os.environ.get('AI_API_BASE'):
        return True
    return is_qvac_server_running()


def is_qvac_server_running():
    """Check if QVAC OpenAI-compatible server is running on its dedicated port."""
    try:
        resp = requests.get(f"http://localhost:{QVAC_PORT}/v1/models", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def get_ai_config():
    """Get AI configuration — QVAC only, no Ollama."""
    base_url = os.environ.get('AI_API_BASE')
    api_key = os.environ.get('AI_API_KEY', 'not-needed')
    model = os.environ.get('AI_MODEL')

    if not base_url:
        if is_qvac_server_running():
            base_url = QVAC_BASE_URL
            if not model:
                model = QVAC_DEFAULT_MODEL
            logger.info("QVAC server detected at %s, model=%s", base_url, model)

    if not model:
        model = QVAC_DEFAULT_MODEL

    return base_url, api_key, model


def get_qvac_status():
    """Get QVAC server status for the UI."""
    status = {
        'configured': False,
        'server_running': False,
        'model': None,
        'base_url': None,
        'type': None,
    }

    # Check env vars
    if os.environ.get('AI_API_BASE'):
        status['configured'] = True
        status['base_url'] = os.environ.get('AI_API_BASE')
        status['model'] = os.environ.get('AI_MODEL', 'unknown')
        status['type'] = 'env'

    # Check QVAC server on dedicated port
    try:
        resp = requests.get(f"http://localhost:{QVAC_PORT}/v1/models", timeout=2)
        if resp.status_code == 200:
            status['server_running'] = True
            if not status['configured']:
                status['configured'] = True
                status['base_url'] = QVAC_BASE_URL
                status['model'] = os.environ.get('AI_MODEL', QVAC_DEFAULT_MODEL)
                status['type'] = 'qvac'
            data = resp.json()
            loaded = data.get('data', [])
            if loaded:
                status['loaded_models'] = [m.get('id', 'unknown') for m in loaded]
    except Exception:
        pass

    return status


def start_qvac_server():
    """Return the command to start QVAC server (for reference in UI)."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'qvac.config.json')
    return f"npx qvac serve openai --config {config_path} --model qwen2.5 --cors --port {QVAC_PORT}"


def get_project_context():
    """Build a snapshot of current project data for AI context."""
    from app.models import Member, Milestone, Task, BudgetCategory, Contribution
    from datetime import date

    ctx = {}

    members = Member.query.all()
    ctx['members'] = [{
        'name': m.name, 'role': m.role or 'N/A',
        'tasks_total': m.task_count, 'tasks_done': m.completed_task_count,
        'hours_logged': sum(c.hours for c in m.contributions)
    } for m in members]

    milestones = Milestone.query.order_by(Milestone.deadline).all()
    ctx['milestones'] = [{
        'name': m.name, 'status': m.status, 'progress': m.progress,
        'start': m.start_date.isoformat() if m.start_date else None,
        'deadline': m.deadline.isoformat(),
        'tasks': [{'title': t.title, 'status': t.status, 'assignee': t.assignee.name if t.assignee else None} for t in m.tasks]
    } for m in milestones]

    tasks = Task.query.all()
    ctx['tasks'] = [{
        'title': t.title, 'status': t.status, 'priority': t.priority,
        'assignee': t.assignee.name if t.assignee else None,
        'milestone': t.milestone.name if t.milestone else None,
        'due': t.due_date.isoformat() if t.due_date else None
    } for t in tasks]

    categories = BudgetCategory.query.all()
    ctx['budget'] = {
        'total_allocated': sum(c.allocated for c in categories),
        'total_spent': sum(c.spent for c in categories),
        'categories': [{
            'name': c.name, 'allocated': c.allocated, 'spent': c.spent,
            'expenses': [{'desc': e.description, 'amount': e.amount, 'paid_by': e.paid_by} for e in c.expenses]
        } for c in categories]
    }

    contribs = Contribution.query.order_by(Contribution.date.desc()).limit(10).all()
    ctx['recent_contributions'] = [{
        'member': c.member.name, 'hours': c.hours, 'description': c.description, 'date': c.date.isoformat()
    } for c in contribs]

    ctx['today'] = date.today().isoformat()
    return ctx


SYSTEM_PROMPT = """You are a project management assistant powered by QVAC (local AI). You help manage a school project by:
- Viewing and understanding the current project state
- Adding tasks, milestones, members, budget categories, and expenses
- Assigning tasks to team members
- Suggesting who should work on what based on workload
- Logging contribution hours
- Updating task/milestone statuses
- Removing/deleting items

When the user asks you to do something, respond naturally and confirm what you did.
If you need to perform an action (add, remove, update, assign, log), output an action block like:

<<<ACTION>>>
action_type: add_task
params:
  title: Build the API
  priority: high
  due_date: 2026-06-15
<<<END_ACTION>>>

Supported action types and their params:
- add_member: name, role (optional), email (optional)
- add_task: title, priority (optional, default medium), due_date (optional, YYYY-MM-DD), milestone_name (optional), assignee_name (optional)
- add_milestone: name, deadline (YYYY-MM-DD), start_date (optional, YYYY-MM-DD)
- add_category: name, allocated (number)
- add_expense: description, amount (number), category_name, paid_by (optional)
- log_hours: member_name, hours (number), description (optional)
- assign_task: task_title, member_name
- update_task_status: task_title, status (todo/in_progress/done)
- update_milestone_status: milestone_name, status (upcoming/in_progress/done/overdue)
- remove_member: name
- remove_task: title
- remove_milestone: name
- remove_category: name

You can include multiple actions in one response if needed. Always explain what you're doing in plain text alongside the action blocks.
If the user just asks a question, answer it from the project data — no action block needed.

Keep responses concise and practical.
"""


def chat_with_ai(user_message, conversation_history=None):
    """Send message to AI and return (text_response, actions_list)."""
    base_url, api_key, model = get_ai_config()

    if not base_url:
        return "AI is not configured. Start the QVAC server or set AI_API_BASE environment variable.", []

    client = OpenAI(base_url=base_url, api_key=api_key)

    # Build context
    project_data = get_project_context()
    context_msg = f"Current project data:\n{json.dumps(project_data, indent=2, default=str)}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_msg},
    ]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
    except Exception as e:
        logger.error("AI chat error: %s", e)
        return f"AI error: {str(e)}", []

    reply = response.choices[0].message.content

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
