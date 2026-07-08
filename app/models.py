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

    # Scores 1-10 across the evaluation matrix (0 = not yet scored)
    strategic_fit = db.Column(db.Integer, default=0)       # alignment with org strategy
    feasibility = db.Column(db.Integer, default=0)         # can we actually deliver it
    business_value = db.Column(db.Integer, default=0)      # ROI / revenue / efficiency
    risk_level = db.Column(db.Integer, default=0)          # INVERTED: 10 = very low risk, 1 = very high risk
    cost_efficiency = db.Column(db.Integer, default=0)     # INVERTED: 10 = very low cost, 1 = very high cost
    urgency = db.Column(db.Integer, default=0)             # time pressure / window of opportunity

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

    # Weighted scoring model - criteria and default weights (must sum to 1.0)
    CRITERIA = ['strategic_fit', 'feasibility', 'business_value', 'risk_level', 'cost_efficiency', 'urgency']
    CRITERIA_LABELS = {
        'strategic_fit': 'Strategic Fit',
        'feasibility': 'Feasibility',
        'business_value': 'Business Value',
        'risk_level': 'Risk Level',
        'cost_efficiency': 'Cost Efficiency',
        'urgency': 'Urgency',
    }
    CRITERIA_INVERTED = {'risk_level', 'cost_efficiency'}  # higher = better (lower risk / lower cost)
    DEFAULT_WEIGHTS = {
        'strategic_fit': 0.25,
        'feasibility': 0.15,
        'business_value': 0.25,
        'risk_level': 0.15,
        'cost_efficiency': 0.10,
        'urgency': 0.10,
    }

    @classmethod
    def get_weights(cls):
        """Load weights from DB-backed config, falling back to defaults."""
        cfg = ScoringConfig.get_config()
        weights = dict(cls.DEFAULT_WEIGHTS)
        if cfg and cfg.weights_json:
            try:
                stored = json.loads(cfg.weights_json)
                for k in cls.CRITERIA:
                    if k in stored:
                        weights[k] = float(stored[k])
            except (json.JSONDecodeError, TypeError):
                pass
        return weights

    @property
    def scores_dict(self):
        return {k: getattr(self, k) for k in self.CRITERIA}

    @property
    def is_scored(self):
        return any(getattr(self, k) > 0 for k in self.CRITERIA)

    @property
    def weighted_total(self):
        """Weighted total on the 1-10 scale."""
        if not self.is_scored:
            return 0
        weights = self.get_weights()
        scores = self.scores_dict
        return round(sum(scores[k] * weights[k] for k in self.CRITERIA), 2)

    @property
    def total_score(self):
        """Alias for weighted_total for template compatibility."""
        return self.weighted_total

    @property
    def total_percentage(self):
        """Weighted total as a percentage of the maximum possible score (10.0)."""
        if not self.is_scored:
            return 0
        return round(self.weighted_total / 10.0 * 100, 1)

    @property
    def weighted_breakdown(self):
        """Return list of (criterion, label, score, weight, contribution) for display."""
        if not self.is_scored:
            return []
        weights = self.get_weights()
        scores = self.scores_dict
        result = []
        for k in self.CRITERIA:
            s = scores[k]
            w = weights[k]
            result.append({
                'key': k,
                'label': self.CRITERIA_LABELS[k],
                'score': s,
                'weight': w,
                'weight_pct': round(w * 100),
                'contribution': round(s * w, 2),
                'inverted': k in self.CRITERIA_INVERTED,
            })
        return result

    @property
    def recommendation_tier(self):
        """Categorise the proposal by its weighted percentage."""
        pct = self.total_percentage
        if not self.is_scored:
            return 'unscored'
        if pct >= 75:
            return 'strongly_recommended'
        if pct >= 60:
            return 'recommended'
        if pct >= 45:
            return 'conditional'
        return 'not_recommended'


class ScoringConfig(db.Model):
    """Singleton config for the weighted scoring model weights."""
    id = db.Column(db.Integer, primary_key=True)
    weights_json = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @staticmethod
    def get_config():
        return ScoringConfig.query.first()

    @staticmethod
    def get_or_create():
        cfg = ScoringConfig.query.first()
        if not cfg:
            cfg = ScoringConfig()
            cfg.weights_json = json.dumps(ProjectProposal.DEFAULT_WEIGHTS)
            db.session.add(cfg)
            db.session.commit()
        return cfg


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
