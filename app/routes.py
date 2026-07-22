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
    cfg = ScoringConfig.get_or_create()
    selected = None
    conclusion = None
    if cfg and cfg.selected_proposal_id:
        selected = ProjectProposal.query.get(cfg.selected_proposal_id)
        conclusion = cfg.selection_conclusion or ''
    existing_charter = ProjectCharter.query.first()
    return render_template('proposals.html', proposals=proposals, scored=scored,
                           unscored=unscored, weights=weights,
                           criteria=ProjectProposal.CRITERIA,
                           criteria_labels=ProjectProposal.CRITERIA_LABELS,
                           selected=selected, conclusion=conclusion,
                           existing_charter=existing_charter)


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
    """Convert a proposal into a full project charter.
    Only one charter can exist at a time - if one already exists it must be
    deleted first (the UI enforces this)."""
    from app.ai_agent import generate_charter_outline
    p = ProjectProposal.query.get_or_404(id)

    # Enforce single charter
    existing = ProjectCharter.query.first()
    if existing:
        flash('A project charter already exists. Delete it first before creating a new one.')
        return redirect(url_for('main.charter_view', id=existing.id))

    outline = generate_charter_outline(p.title, p.description)
    charter = ProjectCharter(name=p.title, description=p.description)
    charter.outline = outline
    db.session.add(charter)
    db.session.commit()

    p.charter_id = charter.id
    db.session.commit()

    flash(f'Proposal "{p.title}" converted to a charter.')
    return redirect(url_for('main.charter_view', id=charter.id))


@bp.route('/proposals/<int:id>/select', methods=['POST'])
def proposal_select(id):
    """Select the winning proposal and generate a conclusion."""
    from app.ai_agent import generate_selection_conclusion

    p = ProjectProposal.query.get_or_404(id)
    if not p.is_scored:
        flash('Score this proposal first before selecting it.')
        return redirect(url_for('main.proposal_list') + '#proposals')

    all_proposals = ProjectProposal.query.all()
    conclusion = generate_selection_conclusion(p, all_proposals)

    cfg = ScoringConfig.get_or_create()
    cfg.selected_proposal_id = p.id
    cfg.selection_conclusion = conclusion
    db.session.commit()

    flash(f'Selected "{p.title}" as the winning proposal. Conclusion generated.')
    return redirect(url_for('main.proposal_list') + '#selection')


@bp.route('/proposals/reset', methods=['POST'])
def proposal_reset():
    """Clear ALL proposals, scores, selection, and reset weights to defaults.
    This does NOT delete existing project charters."""
    ProjectProposal.query.delete()
    cfg = ScoringConfig.get_or_create()
    cfg.selected_proposal_id = None
    cfg.selection_conclusion = None
    cfg.weights_json = json.dumps(ProjectProposal.DEFAULT_WEIGHTS)
    db.session.commit()
    flash('All proposals cleared. Weights reset to defaults.')
    return redirect(url_for('main.proposal_list'))


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


# ─── Quick-Add Assistant API ────────────────────────────────
# JSON endpoints for the floating bottom-right assistant widget.
# Each returns {success, message, item} so the UI can show inline
# confirmation without a full page reload, enabling rapid multi-add.

@bp.route('/api/quick/members', methods=['POST'])
def quick_add_member():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Name is required.'})
    m = Member(name=name, email=(data.get('email') or '').strip(), role=(data.get('role') or '').strip())
    db.session.add(m)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Added member "{name}".', 'item': {'id': m.id, 'name': m.name, 'role': m.role}})


@bp.route('/api/quick/milestones', methods=['POST'])
def quick_add_milestone():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Name is required.'})
    deadline_str = (data.get('deadline') or '').strip()
    if not deadline_str:
        return jsonify({'success': False, 'message': 'Deadline is required.'})
    try:
        deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid deadline date.'})
    start_str = (data.get('start_date') or '').strip()
    start_date = None
    if start_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid start date.'})
    ms = Milestone(name=name, description=(data.get('description') or '').strip(), start_date=start_date, deadline=deadline)
    db.session.add(ms)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Added milestone "{name}" (due {deadline.strftime("%b %d, %Y")}).', 'item': {'id': ms.id, 'name': ms.name, 'deadline': deadline_str}})


@bp.route('/api/quick/categories', methods=['POST'])
def quick_add_category():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Category name is required.'})
    try:
        allocated = float(data.get('allocated', 0))
    except (ValueError, TypeError):
        allocated = 0
    cat = BudgetCategory(name=name, allocated=allocated)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Added category "{name}" (${allocated:.2f}).', 'item': {'id': cat.id, 'name': cat.name, 'allocated': allocated}})


@bp.route('/api/quick/expenses', methods=['POST'])
def quick_add_expense():
    data = request.get_json(silent=True) or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'success': False, 'message': 'Description is required.'})
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid amount.'})
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Amount must be greater than 0.'})
    try:
        category_id = int(data.get('category_id', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid category.'})
    cat = BudgetCategory.query.get(category_id)
    if not cat:
        return jsonify({'success': False, 'message': 'Category not found.'})
    paid_by = (data.get('paid_by') or '').strip()
    date_str = (data.get('date') or '').strip()
    exp_date = None
    if date_str:
        try:
            exp_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid date.'})
    if not exp_date:
        exp_date = date.today()
    exp = Expense(description=description, amount=amount, category_id=category_id, paid_by=paid_by, date=exp_date)
    db.session.add(exp)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Added expense "{description}" (${amount:.2f}).', 'item': {'id': exp.id, 'description': exp.description, 'amount': amount, 'category': cat.name}})


@bp.route('/api/quick/tasks', methods=['POST'])
def quick_add_task():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'message': 'Title is required.'})
    priority = (data.get('priority') or 'medium').strip()
    if priority not in ('low', 'medium', 'high'):
        priority = 'medium'
    due_str = (data.get('due_date') or '').strip()
    due = None
    if due_str:
        try:
            due = datetime.strptime(due_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid due date.'})
    milestone_id = None
    assignee_id = None
    try:
        milestone_id = int(data['milestone_id']) if data.get('milestone_id') else None
    except (ValueError, TypeError):
        pass
    try:
        assignee_id = int(data['assignee_id']) if data.get('assignee_id') else None
    except (ValueError, TypeError):
        pass
    t = Task(title=title, priority=priority, due_date=due, milestone_id=milestone_id, assignee_id=assignee_id)
    db.session.add(t)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Added task "{title}".', 'item': {'id': t.id, 'title': t.title, 'priority': t.priority}})


@bp.route('/api/quick/options', methods=['GET'])
def quick_options():
    """Return dropdown options (members, milestones, categories) for the assistant forms."""
    return jsonify({
        'members': [{'id': m.id, 'name': m.name, 'role': m.role} for m in Member.query.all()],
        'milestones': [{'id': m.id, 'name': m.name} for m in Milestone.query.order_by(Milestone.deadline).all()],
        'categories': [{'id': c.id, 'name': c.name, 'allocated': c.allocated} for c in BudgetCategory.query.all()],
    })


# ─── Bulk multi-add + contribution logging ─────────────────

@bp.route('/api/quick/members/bulk', methods=['POST'])
def quick_bulk_members():
    """Add multiple members from line-separated text.
    Each line: 'Name' or 'Name, Role' or 'Name, Role, email@...'"""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        name = parts[0] if parts else ''
        role = parts[1] if len(parts) > 1 else ''
        email = parts[2] if len(parts) > 2 else ''
        if not name:
            errors.append(f'Line {i}: missing name')
            continue
        m = Member(name=name[:100], role=role[:100], email=email[:120])
        db.session.add(m)
        added.append(name)
    if added:
        db.session.commit()
    msg = f'Added {len(added)} member(s).' if added else 'No members added.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})


@bp.route('/api/quick/milestones/bulk', methods=['POST'])
def quick_bulk_milestones():
    """Add multiple milestones. Each line: 'Name, YYYY-MM-DD' or 'Name, YYYY-MM-DD, YYYY-MM-DD(start)'"""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        name = parts[0] if parts else ''
        if not name:
            errors.append(f'Line {i}: missing name')
            continue
        deadline_str = parts[1] if len(parts) > 1 else ''
        if not deadline_str:
            errors.append(f'Line {i}: {name} - missing deadline')
            continue
        try:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append(f'Line {i}: {name} - invalid deadline')
            continue
        start_date = None
        if len(parts) > 2 and parts[2]:
            try:
                start_date = datetime.strptime(parts[2], '%Y-%m-%d').date()
            except ValueError:
                pass  # optional, ignore bad start date
        ms = Milestone(name=name[:200], deadline=deadline, start_date=start_date)
        db.session.add(ms)
        added.append(name)
    if added:
        db.session.commit()
    msg = f'Added {len(added)} milestone(s).' if added else 'No milestones added.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})


@bp.route('/api/quick/tasks/bulk', methods=['POST'])
def quick_bulk_tasks():
    """Add multiple tasks. Each line: 'Title' or 'Title, priority' or 'Title, priority, YYYY-MM-DD'"""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    default_priority = (data.get('default_priority') or 'medium').strip()
    default_milestone = data.get('default_milestone_id')
    default_assignee = data.get('default_assignee_id')
    if default_priority not in ('low', 'medium', 'high'):
        default_priority = 'medium'
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        title = parts[0] if parts else ''
        if not title:
            errors.append(f'Line {i}: missing title')
            continue
        priority = parts[1] if len(parts) > 1 and parts[1] in ('low', 'medium', 'high') else default_priority
        due = None
        if len(parts) > 2 and parts[2]:
            try:
                due = datetime.strptime(parts[2], '%Y-%m-%d').date()
            except ValueError:
                pass
        milestone_id = int(default_milestone) if default_milestone else None
        assignee_id = int(default_assignee) if default_assignee else None
        t = Task(title=title[:200], priority=priority, due_date=due, milestone_id=milestone_id, assignee_id=assignee_id)
        db.session.add(t)
        added.append(title)
    if added:
        db.session.commit()
    msg = f'Added {len(added)} task(s).' if added else 'No tasks added.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})


@bp.route('/api/quick/categories/bulk', methods=['POST'])
def quick_bulk_categories():
    """Add multiple budget categories. Each line: 'Name' or 'Name, amount'"""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        name = parts[0] if parts else ''
        if not name:
            errors.append(f'Line {i}: missing name')
            continue
        allocated = 0
        if len(parts) > 1 and parts[1]:
            try:
                allocated = float(parts[1].replace('$', ''))
            except ValueError:
                errors.append(f'Line {i}: {name} - invalid amount')
                continue
        cat = BudgetCategory(name=name[:100], allocated=allocated)
        db.session.add(cat)
        added.append(name)
    if added:
        db.session.commit()
    msg = f'Added {len(added)} categor(ies).' if added else 'No categories added.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})


@bp.route('/api/quick/expenses/bulk', methods=['POST'])
def quick_bulk_expenses():
    """Add multiple expenses. Each line: 'Description, amount' or 'Description, amount, category_name'
    If category_name not given, uses default_category_id."""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    default_cat_id = data.get('default_category_id')
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        desc = parts[0] if parts else ''
        if not desc:
            errors.append(f'Line {i}: missing description')
            continue
        amount = 0
        if len(parts) > 1 and parts[1]:
            try:
                amount = float(parts[1].replace('$', ''))
            except ValueError:
                errors.append(f'Line {i}: {desc} - invalid amount')
                continue
        if amount <= 0:
            errors.append(f'Line {i}: {desc} - amount must be > 0')
            continue
        # Category: per-line name or default
        cat = None
        if len(parts) > 2 and parts[2]:
            cat = BudgetCategory.query.filter(BudgetCategory.name.ilike(f'%{parts[2]}%')).first()
        if not cat and default_cat_id:
            try:
                cat = BudgetCategory.query.get(int(default_cat_id))
            except (ValueError, TypeError):
                pass
        if not cat:
            errors.append(f'Line {i}: {desc} - no category found')
            continue
        exp = Expense(description=desc[:200], amount=amount, category_id=cat.id, date=date.today())
        db.session.add(exp)
        added.append(desc)
    if added:
        db.session.commit()
    msg = f'Added {len(added)} expense(s).' if added else 'No expenses added.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})


@bp.route('/api/quick/contributions', methods=['POST'])
def quick_add_contribution():
    """Log a single contribution (hours for a member)."""
    data = request.get_json(silent=True) or {}
    try:
        member_id = int(data.get('member_id', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid member.'})
    member = Member.query.get(member_id)
    if not member:
        return jsonify({'success': False, 'message': 'Member not found.'})
    try:
        hours = float(data.get('hours', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid hours.'})
    if hours <= 0:
        return jsonify({'success': False, 'message': 'Hours must be greater than 0.'})
    description = (data.get('description') or '').strip()
    date_str = (data.get('date') or '').strip()
    c_date = date.today()
    if date_str:
        try:
            c_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid date.'})
    c = Contribution(member_id=member_id, hours=hours, description=description, date=c_date)
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Logged {hours}h for "{member.name}".', 'item': {'id': c.id, 'member': member.name, 'hours': hours}})


@bp.route('/api/quick/contributions/bulk', methods=['POST'])
def quick_bulk_contributions():
    """Add multiple contributions. Each line: 'Member name, hours' or 'Member name, hours, description'
    Member name is matched case-insensitively (partial match)."""
    data = request.get_json(silent=True) or {}
    lines = (data.get('lines') or '').strip().split('\n')
    default_date = (data.get('default_date') or '').strip()
    c_date = date.today()
    if default_date:
        try:
            c_date = datetime.strptime(default_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    added, errors = [], []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        member_name = parts[0] if parts else ''
        if not member_name:
            errors.append(f'Line {i}: missing member name')
            continue
        member = Member.query.filter(Member.name.ilike(f'%{member_name}%')).first()
        if not member:
            errors.append(f'Line {i}: "{member_name}" - member not found')
            continue
        hours = 0
        if len(parts) > 1 and parts[1]:
            try:
                hours = float(parts[1])
            except ValueError:
                errors.append(f'Line {i}: {member_name} - invalid hours')
                continue
        if hours <= 0:
            errors.append(f'Line {i}: {member_name} - hours must be > 0')
            continue
        description = parts[2] if len(parts) > 2 else ''
        c = Contribution(member_id=member.id, hours=hours, description=description, date=c_date)
        db.session.add(c)
        added.append(f'{member.name} ({hours}h)')
    if added:
        db.session.commit()
    msg = f'Logged {len(added)} contribution(s).' if added else 'No contributions logged.'
    if errors:
        msg += f' {len(errors)} error(s): ' + '; '.join(errors[:3])
    return jsonify({'success': len(added) > 0, 'message': msg, 'count': len(added)})
