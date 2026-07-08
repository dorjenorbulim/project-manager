from app import db
from datetime import date, datetime, timezone
import json


class ProjectCharter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    budget = db.Column(db.Float, default=0)

    # JSON-encoded structured outline (objectives, scope_in, scope_out,
    # deliverables, milestones, success_criteria, risks, assumptions)
    _outline_json = db.Column('outline_json', db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    stakeholders = db.relationship('Stakeholder', backref='charter', lazy=True, cascade='all, delete-orphan')

    @property
    def outline(self):
        if not self._outline_json:
            return {}
        try:
            return json.loads(self._outline_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @outline.setter
    def outline(self, value):
        self._outline_json = json.dumps(value) if value else None

    def outline_items(self, key):
        """Return a list for a given outline key (defaults to [] if missing)."""
        return self.outline.get(key, [])


class Stakeholder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    charter_id = db.Column(db.Integer, db.ForeignKey('project_charter.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120))
    organization = db.Column(db.String(120))
    email = db.Column(db.String(120))
    # 1-5 scale for interest and influence (low -> high)
    interest = db.Column(db.Integer, default=3)
    influence = db.Column(db.Integer, default=3)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def category(self):
        """Mendelow power/interest grid categorisation."""
        high_influence = self.influence >= 3
        high_interest = self.interest >= 3
        if high_influence and high_interest:
            return 'manage_closely'      # Manage Closely — most important, engage regularly
        if high_influence and not high_interest:
            return 'keep_satisfied'      # Keep Satisfied — consulted regularly
        if not high_influence and high_interest:
            return 'keep_informed'       # Keep Informed — informed
        return 'monitor'                 # Monitor — minimal effort

    @property
    def category_label(self):
        return {
            'manage_closely': 'Manage Closely',
            'keep_satisfied': 'Keep Satisfied',
            'keep_informed': 'Keep Informed',
            'monitor': 'Monitor',
        }[self.category]

    @property
    def priority_rank(self):
        """Lower number = higher priority."""
        return {
            'manage_closely': 0,
            'keep_satisfied': 1,
            'keep_informed': 2,
            'monitor': 3,
        }[self.category]


class ProjectProposal(db.Model):
    """A vague project proposal submitted for comparative evaluation and selection."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(120))  # who submitted it / where it came from

    # Scores 1-5 across the evaluation matrix (0 = not yet scored)
    alignment = db.Column(db.Integer, default=0)       # strategic alignment
    feasibility = db.Column(db.Integer, default=0)     # can we actually do it
    impact = db.Column(db.Integer, default=0)          # value / benefit
    risk = db.Column(db.Integer, default=0)            # risk level (5 = low risk, 1 = high risk)
    cost = db.Column(db.Integer, default=0)            # cost efficiency (5 = low cost, 1 = high cost)

    # AI-generated rationale for each score
    _rationale_json = db.Column('rationale_json', db.Text)
    recommendation = db.Column(db.Text)  # overall recommendation text

    # Optional link to a charter created from this proposal
    charter_id = db.Column(db.Integer, db.ForeignKey('project_charter.id', ondelete='SET NULL'))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def rationale(self):
        if not self._rationale_json:
            return {}
        try:
            return json.loads(self._rationale_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @rationale.setter
    def rationale(self, value):
        self._rationale_json = json.dumps(value) if value else None

    @property
    def total_score(self):
        """Weighted total: alignment 25%, feasibility 20%, impact 25%, risk 15%, cost 15%."""
        if not any([self.alignment, self.feasibility, self.impact, self.risk, self.cost]):
            return 0
        weights = {'alignment': 0.25, 'feasibility': 0.20, 'impact': 0.25, 'risk': 0.15, 'cost': 0.15}
        scores = {'alignment': self.alignment, 'feasibility': self.feasibility,
                  'impact': self.impact, 'risk': self.risk, 'cost': self.cost}
        return round(sum(scores[k] * weights[k] for k in weights), 2)

    @property
    def is_scored(self):
        return any([self.alignment, self.feasibility, self.impact, self.risk, self.cost])


class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    role = db.Column(db.String(100))
    tasks = db.relationship('Task', backref='assignee', lazy=True, passive_deletes=True)
    contributions = db.relationship('Contribution', backref='member', lazy=True, cascade='all, delete-orphan')

    @property
    def task_count(self):
        return len(self.tasks)

    @property
    def completed_task_count(self):
        return len([t for t in self.tasks if t.status == 'done'])

    @property
    def completion_rate(self):
        total = self.task_count
        if total == 0:
            return 0
        return round((self.completed_task_count / total) * 100)


class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    deadline = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='upcoming')  # upcoming, in_progress, done, overdue
    tasks = db.relationship('Task', backref='milestone', lazy=True, passive_deletes=True)

    @property
    def progress(self):
        total = len(self.tasks)
        if total == 0:
            return 0
        done = len([t for t in self.tasks if t.status == 'done'])
        return round((done / total) * 100)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='todo')  # todo, in_progress, done
    priority = db.Column(db.String(10), default='medium')  # low, medium, high
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestone.id', ondelete='SET NULL'))
    assignee_id = db.Column(db.Integer, db.ForeignKey('member.id', ondelete='SET NULL'))
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class BudgetCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    allocated = db.Column(db.Float, default=0)
    expenses = db.relationship('Expense', backref='category', lazy=True, cascade='all, delete-orphan')

    @property
    def spent(self):
        return sum(e.amount for e in self.expenses)

    @property
    def remaining(self):
        return self.allocated - self.spent


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    receipt = db.Column(db.String(300))
    category_id = db.Column(db.Integer, db.ForeignKey('budget_category.id', ondelete='CASCADE'), nullable=False)
    paid_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, default=date.today)
    hours = db.Column(db.Float, default=0)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
