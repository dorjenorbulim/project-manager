from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Member, Milestone, Task, BudgetCategory, Expense, Contribution
from datetime import datetime, date, timedelta
import re

bp = Blueprint('main', __name__)


# ─── Dashboard ───────────────────────────────────────────────

@bp.route('/')
def dashboard():
    members = Member.query.all()
    milestones = Milestone.query.order_by(Milestone.deadline).all()
    categories = BudgetCategory.query.all()
    tasks = Task.query.all()

    total_budget = sum(c.allocated for c in categories)
    total_spent = sum(c.spent for c in categories)
    total_tasks = len(tasks)
    done_tasks = len([t for t in tasks if t.status == 'done'])
    overdue_milestones = len([m for m in milestones if m.deadline < date.today() and m.status != 'done'])

    return render_template('dashboard.html',
        members=members, milestones=milestones, categories=categories,
        total_budget=total_budget, total_spent=total_spent,
        total_tasks=total_tasks, done_tasks=done_tasks,
        overdue_milestones=overdue_milestones)


# ─── Members ─────────────────────────────────────────────────

@bp.route('/members')
def members():
    members = Member.query.all()
    return render_template('members.html', members=members)


@bp.route('/members/add', methods=['POST'])
def add_member():
    name = request.form['name']
    email = request.form.get('email', '')
    role = request.form.get('role', '')
    db.session.add(Member(name=name, email=email, role=role))
    db.session.commit()
    flash(f'Member "{name}" added.')
    return redirect(url_for('main.members'))


@bp.route('/members/<int:id>/delete', methods=['POST'])
def delete_member(id):
    member = Member.query.get_or_404(id)
    # Nullify task references before deleting
    Task.query.filter_by(assignee_id=id).update({'assignee_id': None})
    db.session.delete(member)
    db.session.commit()
    flash(f'Member "{member.name}" removed.')
    return redirect(url_for('main.members'))


# ─── Milestones ──────────────────────────────────────────────

@bp.route('/schedule')
def schedule():
    milestones = Milestone.query.order_by(Milestone.deadline).all()
    today = date.today()

    # Calculate Gantt chart date range
    all_dates = [m.start_date for m in milestones if m.start_date] + [m.deadline for m in milestones]
    if all_dates:
        gantt_start = min(min(all_dates), today)
        gantt_end = max(all_dates)
    else:
        gantt_start = today
        gantt_end = today
    # Add a day buffer
    gantt_end = gantt_end + timedelta(days=1)
    gantt_days = max((gantt_end - gantt_start).days, 1)

    return render_template('schedule.html', milestones=milestones, today=today,
        gantt_start=gantt_start, gantt_end=gantt_end, gantt_days=gantt_days)


@bp.route('/milestones/add', methods=['POST'])
def add_milestone():
    name = request.form['name']
    description = request.form.get('description', '')
    deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%d').date()
    start_date_str = request.form.get('start_date')
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    db.session.add(Milestone(name=name, description=description, start_date=start_date, deadline=deadline))
    db.session.commit()
    flash(f'Milestone "{name}" created.')
    return redirect(url_for('main.schedule'))


@bp.route('/milestones/<int:id>/status', methods=['POST'])
def update_milestone_status(id):
    milestone = Milestone.query.get_or_404(id)
    milestone.status = request.form['status']
    db.session.commit()
    flash(f'Milestone "{milestone.name}" updated to {milestone.status}.')
    return redirect(url_for('main.schedule'))


@bp.route('/milestones/<int:id>/delete', methods=['POST'])
def delete_milestone(id):
    milestone = Milestone.query.get_or_404(id)
    # Nullify task references before deleting
    Task.query.filter_by(milestone_id=id).update({'milestone_id': None})
    db.session.delete(milestone)
    db.session.commit()
    flash(f'Milestone "{milestone.name}" deleted.')
    return redirect(url_for('main.schedule'))


# ─── Tasks ────────────────────────────────────────────────────

@bp.route('/tasks')
def tasks():
    tasks = Task.query.all()
    milestones = Milestone.query.all()
    members = Member.query.all()
    return render_template('tasks.html', tasks=tasks, milestones=milestones, members=members)


@bp.route('/tasks/add', methods=['POST'])
def add_task():
    title = request.form['title']
    description = request.form.get('description', '')
    priority = request.form.get('priority', 'medium')
    milestone_id = request.form.get('milestone_id') or None
    assignee_id = request.form.get('assignee_id') or None
    due_date = request.form.get('due_date')
    due = datetime.strptime(due_date, '%Y-%m-%d').date() if due_date else None

    db.session.add(Task(
        title=title, description=description, priority=priority,
        milestone_id=milestone_id, assignee_id=assignee_id, due_date=due
    ))
    db.session.commit()
    flash(f'Task "{title}" added.')
    return redirect(url_for('main.tasks'))


@bp.route('/tasks/<int:id>/status', methods=['POST'])
def update_task_status(id):
    task = Task.query.get_or_404(id)
    task.status = request.form['status']
    db.session.commit()
    flash(f'Task "{task.title}" updated to {task.status}.')
    return redirect(url_for('main.tasks'))


@bp.route('/tasks/<int:id>/delete', methods=['POST'])
def delete_task(id):
    task = Task.query.get_or_404(id)
    db.session.delete(task)
    db.session.commit()
    flash(f'Task "{task.title}" deleted.')
    return redirect(url_for('main.tasks'))


# ─── Budget ───────────────────────────────────────────────────

@bp.route('/budget')
def budget():
    categories = BudgetCategory.query.all()
    total_budget = sum(c.allocated for c in categories)
    total_spent = sum(c.spent for c in categories)
    return render_template('budget.html', categories=categories,
        total_budget=total_budget, total_spent=total_spent)


@bp.route('/budget/categories/add', methods=['POST'])
def add_category():
    name = request.form['name']
    allocated = float(request.form.get('allocated', 0))
    db.session.add(BudgetCategory(name=name, allocated=allocated))
    db.session.commit()
    flash(f'Category "{name}" added.')
    return redirect(url_for('main.budget'))


@bp.route('/budget/categories/<int:id>/delete', methods=['POST'])
def delete_category(id):
    cat = BudgetCategory.query.get_or_404(id)
    db.session.delete(cat)
    db.session.commit()
    flash(f'Category "{cat.name}" deleted.')
    return redirect(url_for('main.budget'))


@bp.route('/budget/expenses/add', methods=['POST'])
def add_expense():
    description = request.form['description']
    amount = float(request.form['amount'])
    category_id = int(request.form['category_id'])
    paid_by = request.form.get('paid_by', '')
    date_str = request.form.get('date')
    exp_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    db.session.add(Expense(
        description=description, amount=amount,
        category_id=category_id, paid_by=paid_by, date=exp_date
    ))
    db.session.commit()
    flash(f'Expense "{description}" (${amount:.2f}) added.')
    return redirect(url_for('main.budget'))


@bp.route('/budget/expenses/<int:id>/delete', methods=['POST'])
def delete_expense(id):
    exp = Expense.query.get_or_404(id)
    db.session.delete(exp)
    db.session.commit()
    flash(f'Expense "{exp.description}" deleted.')
    return redirect(url_for('main.budget'))


# ─── Contributions ────────────────────────────────────────────

@bp.route('/contributions')
def contributions():
    members = Member.query.all()
    all_contributions = Contribution.query.order_by(Contribution.date.desc()).all()
    return render_template('contributions.html', members=members, contributions=all_contributions)


@bp.route('/contributions/add', methods=['POST'])
def add_contribution():
    member_id = int(request.form['member_id'])
    hours = float(request.form['hours'])
    description = request.form.get('description', '')
    date_str = request.form.get('date')
    c_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    db.session.add(Contribution(
        member_id=member_id, hours=hours,
        description=description, date=c_date
    ))
    db.session.commit()
    flash('Contribution logged.')
    return redirect(url_for('main.contributions'))


# ─── Chatbot API ──────────────────────────────────────────────

def parse_date(text):
    """Try to parse a date from natural language or YYYY-MM-DD."""
    text = text.strip().lower()
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y', '%B %d %Y', '%b %d %Y']
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Relative dates
    today = date.today()
    if text in ('today',): return today
    if text in ('tomorrow',): return today + timedelta(days=1)
    if text in ('next week',): return today + timedelta(weeks=1)
    m = re.match(r'(\d+)\s+days?\s+(from\s+now|later|ahead)', text)
    if m: return today + timedelta(days=int(m.group(1)))
    return None


def smart_allocate(task_name=None):
    """Suggest who to assign a task to based on current workloads."""
    members = Member.query.all()
    if not members:
        return None, "No team members yet. Add some first!"

    member_loads = []
    for m in members:
        total = m.task_count
        done = m.completed_task_count
        active = total - done
        hours = sum(c.hours for c in m.contributions)
        member_loads.append({'member': m, 'active': active, 'hours': hours, 'score': active * 2 + hours})

    if not task_name:
        # General allocation overview
        lines = ["**Team Workload:**\n"]
        for ml in sorted(member_loads, key=lambda x: x['score']):
            m = ml['member']
            lines.append(f"- **{m.name}** ({m.role or 'No role'}): {ml['active']} active tasks, {ml['hours']:.1f}h logged")
        suggested = min(member_loads, key=lambda x: x['score'])
        lines.append(f"\nLeast busy: **{suggested['member'].name}** with a workload score of {suggested['score']}")
        return suggested['member'], '\n'.join(lines)

    # For a specific task, suggest least busy member
    suggested = min(member_loads, key=lambda x: x['score'])
    return suggested['member'], f"I'd suggest assigning **{suggested['member'].name}** to \"{task_name}\" — they have the lightest workload ({suggested['active']} active tasks, {suggested['hours']:.1f}h logged)."


@bp.route('/api/chat', methods=['POST'])
def chat():
    msg = request.json.get('message', '').strip()
    if not msg:
        return jsonify({'response': 'Please type a message.'})

    # Preserve original for display, work with lowercase
    msg_lower = msg.lower().strip().rstrip('.')

    # ─── HELP ───

    if any(kw in msg_lower for kw in ['help', 'commands', 'what can you do', 'what can you', 'how do i']):
        return jsonify({'response': """**I can help you manage your project! Here's what I can do:**

**Add:**
- `add member Alice role Developer`
- `add milestone Sprint 1 deadline 2026-06-30`
- `add task Build API priority high due 2026-06-01`
- `add category Software $5000`
- `add expense Hosting $50 for Software`
- `log 5 hours for Alice doing API work`

**View:**
- `show tasks` / `show members` / `show milestones` / `show budget` / `show contributions`

**Update:**
- `mark Build API as done`
- `mark Sprint 1 as in progress`

**Assign:**
- `assign Build API to Alice`
- `who should do Build API?`

**Delete/Remove:**
- `remove Alice` / `delete task Build API` / `remove milestone Sprint 1`
"""})

    # ─── GREETINGS ───

    if any(kw in msg_lower for kw in ['hello', 'hi ', 'hey', 'good morning', 'good afternoon', 'good evening']):
        return jsonify({'response': 'Hey! How can I help with your project? Type **help** to see what I can do.'})

    # ─── SMART ALLOCATION (check before generic keywords) ───

    m = re.match(r'(?:who\s+should\s+(?:i\s+)?)?(?:assign|give|allocate)\s+(?:the\s+)?(?:task\s+)?(.+?)\s+to\s+(.+)$', msg_lower)
    if m:
        task_name = m.group(1).strip().title()
        member_name = m.group(2).strip().title()
        task = Task.query.filter(Task.title.ilike(f'%{task_name}%')).first()
        member = Member.query.filter(Member.name.ilike(f'%{member_name}%')).first()
        if not task:
            return jsonify({'response': f'Task not found. Check the title or try `show tasks`.'})
        if not member:
            members = Member.query.all()
            names = ', '.join(m.name for m in members)
            return jsonify({'response': f'Member not found. Available: {names}'})
        task.assignee_id = member.id
        db.session.commit()
        return jsonify({'response': f'Assigned **{task.title}** to **{member.name}**!'})

    # Suggest with specific task
    m = re.match(r'(?:suggest|recommend|allocate)\s+(?:for\s+)?(.+)', msg_lower)
    if m:
        task_name = m.group(1).strip().rstrip('?').title()
        _, suggestion = smart_allocate(task_name)
        return jsonify({'response': suggestion})

    m = re.match(r'who\s+should\s+(?:i\s+)?(?:assign|give|put)\s+(.+?)\s*(?:to)?\s*\??$', msg_lower)
    if m:
        task_name = m.group(1).strip().rstrip('?').title()
        _, suggestion = smart_allocate(task_name)
        return jsonify({'response': suggestion})

    if any(kw in msg_lower for kw in ['who should', 'suggest', 'recommend', 'allocate', 'who is least busy', 'workload']):
        _, suggestion = smart_allocate()
        return jsonify({'response': suggestion})

    # ─── DELETE / REMOVE (check early — "remove member alice" should not match "add member") ───

    m = re.match(r'(?:delete|remove)\s+(.+)$', msg_lower)
    if m:
        name = m.group(1).strip()
        # Strip type prefix if they said "remove the member Alice" etc
        for prefix in ['member ', 'task ', 'milestone ', 'category ', 'expense ', 'the ']:
            if name.startswith(prefix):
                name = name[len(prefix):]
        member = Member.query.filter(Member.name.ilike(f'%{name}%')).first()
        if member:
            Task.query.filter_by(assignee_id=member.id).update({'assignee_id': None})
            db.session.delete(member)
            db.session.commit()
            return jsonify({'response': f'Removed member **{member.name}**!'})
        task = Task.query.filter(Task.title.ilike(f'%{name}%')).first()
        if task:
            db.session.delete(task)
            db.session.commit()
            return jsonify({'response': f'Deleted task **{task.title}**!'})
        ms = Milestone.query.filter(Milestone.name.ilike(f'%{name}%')).first()
        if ms:
            Task.query.filter_by(milestone_id=ms.id).update({'milestone_id': None})
            db.session.delete(ms)
            db.session.commit()
            return jsonify({'response': f'Deleted milestone **{ms.name}**!'})
        cat = BudgetCategory.query.filter(BudgetCategory.name.ilike(f'%{name}%')).first()
        if cat:
            db.session.delete(cat)
            db.session.commit()
            return jsonify({'response': f'Deleted category **{cat.name}**!'})
        return jsonify({'response': f'Could not find anything named "{name}" to delete. Try `show tasks` or `show members` to see what exists.'})

    # ─── ADD operations ───

    # Add member — requires "member" keyword: "add member Alice", "add member Alice role Developer"
    m = re.match(r'(?:add|create|new)\s+member\s+(.+?)(?:\s+(?:email\s+|as\s+|role\s+)(.+))?$', msg_lower)
    if m:
        name = m.group(1).strip().title()
        extra = m.group(2) or ''
        email = ''
        role = ''
        email_match = re.search(r'(\S+@\S+)', extra)
        if email_match:
            email = email_match.group(1)
            extra = extra.replace(email, '').strip()
        if extra:
            role = extra.strip()
        existing = Member.query.filter(Member.name.ilike(f'%{name}%')).first()
        if existing:
            return jsonify({'response': f'A member named **{existing.name}** already exists.'})
        member = Member(name=name, email=email, role=role)
        db.session.add(member)
        db.session.commit()
        return jsonify({'response': f'Added member **{name}**!' + (f' (Role: {role})' if role else '')})

    # Add milestone
    m = re.match(r'(?:add|create|new)\s+milestone\s+(.+?)(?:\s+deadline\s+(\S+))?(?:\s+start\s+(\S+))?$', msg_lower)
    if m:
        name = m.group(1).strip().title()
        deadline = parse_date(m.group(2)) if m.group(2) else None
        start_date = parse_date(m.group(3)) if m.group(3) else None
        if not deadline:
            return jsonify({'response': 'Please provide a deadline. Example: `add milestone Sprint 1 deadline 2026-06-30`'})
        ms = Milestone(name=name, start_date=start_date, deadline=deadline)
        db.session.add(ms)
        db.session.commit()
        return jsonify({'response': f'Added milestone **{name}** (deadline: {deadline.strftime("%b %d, %Y")})!'})

    # Add task — flexible: "add task Build API", "create task Build API priority high"
    m = re.match(r'(?:add|create|new)\s+task\s+(.+?)(?:\s+(?:priority\s+|p=)(\w+))?(?:\s+(?:due\s+|due:)\s*(\S+))?$', msg_lower)
    if m:
        title = m.group(1).strip().title()
        priority = m.group(2) or 'medium'
        due = parse_date(m.group(3)) if m.group(3) else None
        task = Task(title=title, priority=priority, due_date=due)
        db.session.add(task)
        db.session.commit()
        return jsonify({'response': f'Added task **{title}** (Priority: {priority})!' + (f' Due: {due.strftime("%b %d, %Y")}' if due else '')})

    # Add budget category
    m = re.match(r'(?:add|create|new)\s+(?:budget\s+)?category\s+(.+?)\s+\$?([\d.]+)$', msg_lower)
    if m:
        name = m.group(1).strip().title()
        allocated = float(m.group(2))
        cat = BudgetCategory(name=name, allocated=allocated)
        db.session.add(cat)
        db.session.commit()
        return jsonify({'response': f'Added budget category **{name}** with ${allocated:.2f} allocated!'})

    # Add expense — supports "expense", "spending", "cost"
    # Format: add expense <description> $<amount> [for <category>]
    # Or: add spending $<amount> [for <category>]
    m = re.match(r'(?:add|create|new|log)\s+(?:expense|spending|cost)\s+(?:(.+?)\s+)?\$?([\d.]+)(?:\s+(?:for|in|to)\s+(.+))?$', msg_lower)
    if m:
        description = (m.group(1) or 'Expense').strip().title()
        amount = float(m.group(2))
        cat_name = m.group(3).strip().title() if m.group(3) else None
        cat = None
        if cat_name:
            cat = BudgetCategory.query.filter(BudgetCategory.name.ilike(f'%{cat_name}%')).first()
        if not cat:
            cats = BudgetCategory.query.all()
            if not cats:
                return jsonify({'response': 'No budget categories yet. Add one first: `add category Software $5000`'})
            cat_list = ', '.join(c.name for c in cats)
            return jsonify({'response': f'Category not found. Available: {cat_list}'})
        exp = Expense(description=description, amount=amount, category_id=cat.id, date=date.today())
        db.session.add(exp)
        db.session.commit()
        return jsonify({'response': f'Added expense **{description}** (${amount:.2f}) to **{cat.name}**!'})

    # Log hours — flexible: "log 5 hours for Alice", "track 5 hours Alice doing API"
    m = re.match(r'(?:log|track|record)\s+(\d+\.?\d*)\s+hours?\s+(?:for\s+)?(.+?)(?:\s+(?:doing|on|for|working\s+on)\s+(.+))?$', msg_lower)
    if m:
        hours = float(m.group(1))
        member_name = m.group(2).strip().title()
        description = m.group(3).strip() if m.group(3) else ''
        member = Member.query.filter(Member.name.ilike(f'%{member_name}%')).first()
        if not member:
            members = Member.query.all()
            names = ', '.join(m.name for m in members) if members else 'none'
            return jsonify({'response': f'Member not found. Available: {names}'})
        contrib = Contribution(member_id=member.id, hours=hours, description=description, date=date.today())
        db.session.add(contrib)
        db.session.commit()
        return jsonify({'response': f'Logged **{hours}h** for **{member.name}**!' + (f' ({description})' if description else '')})

    # ─── UPDATE operations ───

    # Mark task status — flexible: "mark Build API as done", "complete task Build API", "finish Build API"
    m = re.match(r'(?:mark|set|update|change|complete|finish)\s+(?:task\s+)?(.+?)\s+(?:to\s+|as\s+)?(?:a\s+)?(todo|in.?progress|in_progress|done|complete|finished)$', msg_lower)
    if m:
        task_name = m.group(1).strip().title()
        status = m.group(2).replace('in.progress', 'in_progress').replace('complete', 'done').replace('finished', 'done')
        task = Task.query.filter(Task.title.ilike(f'%{task_name}%')).first()
        if not task:
            return jsonify({'response': f'Task not found. Try `show tasks` to see available tasks.'})
        task.status = status
        db.session.commit()
        return jsonify({'response': f'Marked **{task.title}** as **{status}**!'})

    # Mark milestone status
    m = re.match(r'(?:mark|set|update|change)\s+milestone\s+(.+?)\s+(?:to\s+|as\s+)?(?:a\s+)?(upcoming|in.?progress|in_progress|done|overdue)$', msg_lower)
    if m:
        ms_name = m.group(1).strip().title()
        status = m.group(2).replace('in.progress', 'in_progress')
        ms = Milestone.query.filter(Milestone.name.ilike(f'%{ms_name}%')).first()
        if not ms:
            return jsonify({'response': f'Milestone not found. Try `show milestones` to see available milestones.'})
        ms.status = status
        db.session.commit()
        return jsonify({'response': f'Marked milestone **{ms.name}** as **{status}**!'})

    # ─── LIST / SHOW operations ───

    if any(kw in msg_lower for kw in ['list tasks', 'show tasks', 'view tasks', 'what tasks', 'all tasks', 'task list', 'tasks?']):
        tasks = Task.query.all()
        if not tasks:
            return jsonify({'response': 'No tasks yet. Add one: `add task Build API priority high due 2026-06-01`'})
        lines = ['**Tasks:**\n']
        for t in tasks:
            assignee = t.assignee.name if t.assignee else 'Unassigned'
            lines.append(f"- {t.title} | {t.status} | Priority: {t.priority} | Assignee: {assignee}")
        return jsonify({'response': '\n'.join(lines)})

    if any(kw in msg_lower for kw in ['list members', 'show members', 'view members', 'who are the', 'team', 'all members', 'member list', 'members?']):
        members = Member.query.all()
        if not members:
            return jsonify({'response': 'No members yet. Add one: `add member Alice role Developer`'})
        lines = ['**Team Members:**\n']
        for m in members:
            lines.append(f"- **{m.name}** ({m.role or 'No role'}) — {m.task_count} tasks, {m.completed_task_count} done")
        return jsonify({'response': '\n'.join(lines)})

    if any(kw in msg_lower for kw in ['list milestone', 'show milestone', 'view milestone', 'all milestone', 'milestone list', 'milestones?', 'schedule']):
        milestones = Milestone.query.order_by(Milestone.deadline).all()
        if not milestones:
            return jsonify({'response': 'No milestones yet. Add one: `add milestone Sprint 1 deadline 2026-06-30`'})
        lines = ['**Milestones:**\n']
        for ms in milestones:
            start = ms.start_date.strftime('%b %d') if ms.start_date else 'TBD'
            lines.append(f"- **{ms.name}** | {start} - {ms.deadline.strftime('%b %d, %Y')} | Status: {ms.status} | {ms.progress}% complete")
        return jsonify({'response': '\n'.join(lines)})

    if any(kw in msg_lower for kw in ['list budget', 'show budget', 'view budget', 'budget overview', 'how much', 'budget?', 'expenses']):
        categories = BudgetCategory.query.all()
        if not categories:
            return jsonify({'response': 'No budget categories yet. Add one: `add category Software $5000`'})
        total_budget = sum(c.allocated for c in categories)
        total_spent = sum(c.spent for c in categories)
        lines = [f'**Budget: ${total_budget:.2f} total, ${total_spent:.2f} spent, ${total_budget - total_spent:.2f} remaining**\n']
        for c in categories:
            pct = (c.spent / c.allocated * 100) if c.allocated > 0 else 0
            lines.append(f"- **{c.name}**: ${c.spent:.2f} / ${c.allocated:.2f} ({pct:.0f}%)")
        return jsonify({'response': '\n'.join(lines)})

    if any(kw in msg_lower for kw in ['list contribution', 'show contribution', 'hours logged', 'who worked', 'contributions', 'time logged', 'hours?']):
        contribs = Contribution.query.order_by(Contribution.date.desc()).limit(10).all()
        if not contribs:
            return jsonify({'response': 'No contributions logged yet. Log hours: `log 5 hours for Alice doing API development`'})
        lines = ['**Recent Contributions:**\n']
        for c in contribs:
            lines.append(f"- **{c.member.name}**: {c.hours:.1f}h — {c.description or 'No description'} ({c.date.strftime('%b %d')})")
        return jsonify({'response': '\n'.join(lines)})

    # ─── FALLBACK ───
    return jsonify({'response': 'I didn\'t quite understand that. Try **help** to see what I can do, or use commands like:\n- `show tasks`\n- `add member Alice role Developer`\n- `remove Bob`\n- `mark Build API as done`'})
