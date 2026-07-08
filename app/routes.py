from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Member, Milestone, Task, BudgetCategory, Expense, Contribution, ProjectCharter, Stakeholder, ProjectProposal, ScoringConfig
from datetime import datetime, date, timedelta
import json

bp = Blueprint('main', __name__)


# ─── Dashboard ───────────────────────────────────────────────

@bp.route('/')
def dashboard():
    members = Member.query.all()
    milestones = Milestone.query.order_by(Milestone.deadline).all()
    categories = BudgetCategory.query.all()
    tasks = Task.query.all()
    charters = ProjectCharter.query.order_by(ProjectCharter.created_at.desc()).all()

    total_budget = sum(c.allocated for c in categories)
    total_spent = sum(c.spent for c in categories)
    total_tasks = len(tasks)
    done_tasks = len([t for t in tasks if t.status == 'done'])
    overdue_milestones = len([m for m in milestones if m.deadline < date.today() and m.status != 'done'])

    return render_template('dashboard.html',
        members=members, milestones=milestones, categories=categories,
        total_budget=total_budget, total_spent=total_spent,
        total_tasks=total_tasks, done_tasks=done_tasks,
        overdue_milestones=overdue_milestones, charters=charters)


# ─── Project Charters ──────────────────────────────────────

@bp.route('/charters')
def charter_list():
    charters = ProjectCharter.query.order_by(ProjectCharter.created_at.desc()).all()
    return render_template('charter_list.html', charters=charters)


@bp.route('/charters/new', methods=['GET', 'POST'])
def charter_new():
    from app.ai_agent import generate_charter_outline, is_ai_configured, get_ai_status

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        budget_str = request.form.get('budget')

        if not name:
            flash('Please give the project a name.')
            return redirect(url_for('main.charter_new'))

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        budget = float(budget_str) if budget_str else 0

        # Smartly suggest the outline from minimal input
        outline = generate_charter_outline(name, description, start_date, end_date, budget)

        charter = ProjectCharter(
            name=name, description=description,
            start_date=start_date, end_date=end_date, budget=budget,
        )
        charter.outline = outline
        db.session.add(charter)
        db.session.commit()

        flash(f'Charter "{name}" created with a suggested outline.')
        return redirect(url_for('main.charter_view', id=charter.id))

    return render_template('charter_new.html', ai_status=get_ai_status())


@bp.route('/charters/<int:id>')
def charter_view(id):
    charter = ProjectCharter.query.get_or_404(id)
    stakeholders = sorted(charter.stakeholders, key=lambda s: s.priority_rank)
    return render_template('charter_view.html', charter=charter, stakeholders=stakeholders)


@bp.route('/charters/<int:id>/regenerate-outline', methods=['POST'])
def charter_regenerate_outline(id):
    from app.ai_agent import generate_charter_outline

    charter = ProjectCharter.query.get_or_404(id)
    charter.outline = generate_charter_outline(
        charter.name, charter.description, charter.start_date, charter.end_date, charter.budget
    )
    db.session.commit()
    flash('Outline regenerated.')
    return redirect(url_for('main.charter_view', id=charter.id))


@bp.route('/charters/<int:id>/outline', methods=['POST'])
def charter_update_outline(id):
    """Manual edit of the outline sections."""
    charter = ProjectCharter.query.get_or_404(id)
    outline = charter.outline

    text_keys = ['objectives', 'scope_in', 'scope_out', 'deliverables', 'success_criteria', 'assumptions']
    for key in text_keys:
        raw = request.form.get(key, '')
        outline[key] = [line.strip() for line in raw.split('\n') if line.strip()]

    # Milestones: name + weeks pairs
    ms_names = request.form.getlist('milestone_name')
    ms_weeks = request.form.getlist('milestone_weeks')
    outline['milestones'] = []
    for i, mname in enumerate(ms_names):
        mname = mname.strip()
        if not mname:
            continue
        try:
            weeks = int(ms_weeks[i]) if i < len(ms_weeks) else 0
        except (ValueError, IndexError):
            weeks = 0
        outline['milestones'].append({'name': mname, 'weeks': weeks})

    # Risks: name + mitigation pairs
    risk_names = request.form.getlist('risk_name')
    risk_mits = request.form.getlist('risk_mitigation')
    outline['risks'] = []
    for i, rname in enumerate(risk_names):
        rname = rname.strip()
        if not rname:
            continue
        mit = risk_mits[i].strip() if i < len(risk_mits) else ''
        outline['risks'].append({'name': rname, 'mitigation': mit})

    charter.outline = outline
    db.session.commit()
    flash('Outline updated.')
    return redirect(url_for('main.charter_view', id=charter.id))


@bp.route('/charters/<int:id>/delete', methods=['POST'])
def charter_delete(id):
    charter = ProjectCharter.query.get_or_404(id)
    db.session.delete(charter)
    db.session.commit()
    flash(f'Charter "{charter.name}" deleted.')
    return redirect(url_for('main.charter_list'))


# ─── Stakeholders ────────────────────────────────────────────

@bp.route('/charters/<int:id>/stakeholders/add', methods=['POST'])
def stakeholder_add(id):
    charter = ProjectCharter.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Stakeholder name is required.')
        return redirect(url_for('main.charter_view', id=id))

    def _safe_int(val, default=3):
        try:
            v = int(val)
            return max(1, min(5, v))
        except (ValueError, TypeError):
            return default

    s = Stakeholder(
        charter_id=id,
        name=name,
        role=request.form.get('role', '').strip() or None,
        organization=request.form.get('organization', '').strip() or None,
        email=request.form.get('email', '').strip() or None,
        interest=_safe_int(request.form.get('interest', 3)),
        influence=_safe_int(request.form.get('influence', 3)),
        notes=request.form.get('notes', '').strip() or None,
    )
    db.session.add(s)
    db.session.commit()
    flash(f'Stakeholder "{name}" added.')
    return redirect(url_for('main.charter_view', id=id) + '#stakeholders')


@bp.route('/charters/<int:id>/stakeholders/suggest', methods=['POST'])
def stakeholder_suggest(id):
    """Use AI (or template) to suggest an initial set of stakeholders and add them."""
    from app.ai_agent import suggest_stakeholders

    charter = ProjectCharter.query.get_or_404(id)
    suggested = suggest_stakeholders(charter.name, charter.description, charter.outline)
    added = 0
    for s in suggested:
        if not isinstance(s, dict) or not s.get('name'):
            continue
        try:
            interest = max(1, min(5, int(s.get('interest', 3))))
        except (ValueError, TypeError):
            interest = 3
        try:
            influence = max(1, min(5, int(s.get('influence', 3))))
        except (ValueError, TypeError):
            influence = 3
        st = Stakeholder(
            charter_id=id,
            name=str(s.get('name'))[:120],
            role=(str(s.get('role', '')).strip() or None)[:120] if s.get('role') else None,
            organization=(str(s.get('organization', '')).strip() or None)[:120] if s.get('organization') else None,
            interest=interest,
            influence=influence,
            notes=(str(s.get('notes', '')).strip() or None) if s.get('notes') else None,
        )
        db.session.add(st)
        added += 1
    db.session.commit()
    flash(f'{added} stakeholder(s) suggested and added. Tune their interest/influence to re-categorise.')
    return redirect(url_for('main.charter_view', id=id) + '#stakeholders')


@bp.route('/charters/<int:id>/stakeholders/<int:sid>/update', methods=['POST'])
def stakeholder_update(id, sid):
    s = Stakeholder.query.get_or_404(sid)
    if s.charter_id != id:
        flash('Stakeholder does not belong to this charter.')
        return redirect(url_for('main.charter_view', id=id))
    s.name = request.form.get('name', s.name).strip()
    s.role = (request.form.get('role', '') or '').strip() or None
    s.organization = (request.form.get('organization', '') or '').strip() or None
    s.email = (request.form.get('email', '') or '').strip() or None
    def _safe_int(val, default):
        try:
            return max(1, min(5, int(val)))
        except (ValueError, TypeError):
            return default
    s.interest = _safe_int(request.form.get('interest', s.interest), s.interest)
    s.influence = _safe_int(request.form.get('influence', s.influence), s.influence)
    s.notes = (request.form.get('notes', '') or '').strip() or None
    db.session.commit()
    flash(f'Stakeholder "{s.name}" updated.')
    return redirect(url_for('main.charter_view', id=id) + '#stakeholders')


@bp.route('/charters/<int:id>/stakeholders/<int:sid>/delete', methods=['POST'])
def stakeholder_delete(id, sid):
    s = Stakeholder.query.get_or_404(sid)
    if s.charter_id != id:
        flash('Stakeholder does not belong to this charter.')
        return redirect(url_for('main.charter_view', id=id))
    name = s.name
    db.session.delete(s)
    db.session.commit()
    flash(f'Stakeholder "{name}" removed.')
    return redirect(url_for('main.charter_view', id=id) + '#stakeholders')


# ─── Project Selection / Proposals ──────────────────────────

@bp.route('/proposals')
def proposal_list():
    proposals = ProjectProposal.query.order_by(ProjectProposal.created_at.desc()).all()
    scored = sorted([p for p in proposals if p.is_scored], key=lambda p: p.weighted_total, reverse=True)
    unscored = [p for p in proposals if not p.is_scored]
    weights = ProjectProposal.get_weights()
    return render_template('proposals.html', proposals=proposals, scored=scored,
                           unscored=unscored, weights=weights,
                           criteria=ProjectProposal.CRITERIA,
                           criteria_labels=ProjectProposal.CRITERIA_LABELS)


@bp.route('/proposals/add', methods=['POST'])
def proposal_add():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    source = request.form.get('source', '').strip() or None

    if not title:
        flash('Proposal title is required.')
        return redirect(url_for('main.proposal_list'))
    if not description:
        flash('Proposal description is required.')
        return redirect(url_for('main.proposal_list'))

    p = ProjectProposal(title=title, description=description, source=source)
    db.session.add(p)
    db.session.commit()
    flash(f'Proposal "{title}" added.')
    return redirect(url_for('main.proposal_list') + '#proposals')


@bp.route('/proposals/weights', methods=['POST'])
def proposal_update_weights():
    """Update the weighted scoring model criteria weights."""
    cfg = ScoringConfig.get_or_create()
    weights = {}
    total = 0
    for k in ProjectProposal.CRITERIA:
        try:
            w = float(request.form.get(k, ProjectProposal.DEFAULT_WEIGHTS[k]))
            w = max(0, min(1, w))
        except (ValueError, TypeError):
            w = ProjectProposal.DEFAULT_WEIGHTS[k]
        weights[k] = w
        total += w
    # Normalise so weights sum to 1.0
    if total > 0:
        weights = {k: round(v / total, 4) for k, v in weights.items()}
    else:
        weights = dict(ProjectProposal.DEFAULT_WEIGHTS)
    cfg.weights_json = json.dumps(weights)
    db.session.commit()
    flash('Scoring weights updated and normalised.')
    return redirect(url_for('main.proposal_list') + '#weights')


@bp.route('/proposals/<int:id>/score', methods=['POST'])
def proposal_score(id):
    from app.ai_agent import score_proposal
    p = ProjectProposal.query.get_or_404(id)

    result = score_proposal(p.title, p.description)
    p.strategic_fit = result['strategic_fit']
    p.feasibility = result['feasibility']
    p.business_value = result['business_value']
    p.risk_level = result['risk_level']
    p.cost_efficiency = result['cost_efficiency']
    p.urgency = result['urgency']
    p.rationale = result.get('rationale', {})
    p.recommendation = result.get('recommendation', '')
    db.session.commit()
    flash(f'Proposal "{p.title}" scored: {p.weighted_total}/10 ({p.total_percentage}%)')
    return redirect(url_for('main.proposal_list') + '#proposals')


@bp.route('/proposals/score-all', methods=['POST'])
def proposal_score_all():
    from app.ai_agent import score_proposal
    proposals = ProjectProposal.query.filter_by(strategic_fit=0).all()
    count = 0
    for p in proposals:
        try:
            result = score_proposal(p.title, p.description)
            p.strategic_fit = result['strategic_fit']
            p.feasibility = result['feasibility']
            p.business_value = result['business_value']
            p.risk_level = result['risk_level']
            p.cost_efficiency = result['cost_efficiency']
            p.urgency = result['urgency']
            p.rationale = result.get('rationale', {})
            p.recommendation = result.get('recommendation', '')
            count += 1
        except Exception:
            continue
    db.session.commit()
    flash(f'{count} proposal(s) scored.')
    return redirect(url_for('main.proposal_list') + '#proposals')


@bp.route('/proposals/<int:id>/update-scores', methods=['POST'])
def proposal_update_scores(id):
    p = ProjectProposal.query.get_or_404(id)

    def _safe_int(val, default=0):
        try:
            return max(0, min(10, int(val)))
        except (ValueError, TypeError):
            return default

    p.strategic_fit = _safe_int(request.form.get('strategic_fit', 0))
    p.feasibility = _safe_int(request.form.get('feasibility', 0))
    p.business_value = _safe_int(request.form.get('business_value', 0))
    p.risk_level = _safe_int(request.form.get('risk_level', 0))
    p.cost_efficiency = _safe_int(request.form.get('cost_efficiency', 0))
    p.urgency = _safe_int(request.form.get('urgency', 0))
    db.session.commit()
    flash(f'Scores updated for "{p.title}": {p.weighted_total}/10 ({p.total_percentage}%)')
    return redirect(url_for('main.proposal_list') + '#proposals')


@bp.route('/proposals/<int:id>/convert', methods=['POST'])
def proposal_convert(id):
    """Convert a proposal into a full project charter."""
    from app.ai_agent import generate_charter_outline
    p = ProjectProposal.query.get_or_404(id)

    outline = generate_charter_outline(p.title, p.description)
    charter = ProjectCharter(name=p.title, description=p.description)
    charter.outline = outline
    db.session.add(charter)
    db.session.commit()

    p.charter_id = charter.id
    db.session.commit()

    flash(f'Proposal "{p.title}" converted to a charter.')
    return redirect(url_for('main.charter_view', id=charter.id))


@bp.route('/proposals/<int:id>/delete', methods=['POST'])
def proposal_delete(id):
    p = ProjectProposal.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash(f'Proposal "{p.title}" deleted.')
    return redirect(url_for('main.proposal_list') + '#proposals')


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

    all_dates = [m.start_date for m in milestones if m.start_date] + [m.deadline for m in milestones]
    if all_dates:
        gantt_start = min(min(all_dates), today)
        gantt_end = max(all_dates)
    else:
        gantt_start = today
        gantt_end = today
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
