from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Member, Milestone, Task, BudgetCategory, Expense, Contribution
from datetime import datetime, date, timedelta

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
