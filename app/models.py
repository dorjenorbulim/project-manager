from app import db
from datetime import date, datetime, timezone


class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    role = db.Column(db.String(100))
    tasks = db.relationship('Task', backref='assignee', lazy=True, cascade='all, delete-orphan')
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
