from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Transaction(db.Model):
    """Model for wallet transactions."""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    wallet = db.Column(db.String(50), nullable=False)  # Jaib, Jawali, Cash
    type = db.Column(db.String(10), nullable=False)    # credit, debit
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False)  # YER, SAR, USD
    details = db.Column(db.Text, nullable=True)
    counterparty = db.Column(db.String(255), nullable=True)
    balance = db.Column(db.Float, nullable=True)
    balance_currency = db.Column(db.String(10), nullable=True)
    raw_message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        """Convert transaction to dictionary."""
        return {
            'id': self.id,
            'wallet': self.wallet,
            'type': self.type,
            'amount': self.amount,
            'currency': self.currency,
            'details': self.details,
            'counterparty': self.counterparty,
            'balance': self.balance,
            'balance_currency': self.balance_currency,
            'raw_message': self.raw_message,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create a transaction from dictionary data."""
        transaction = cls(
            wallet=data.get('wallet'),
            type=data.get('type'),
            amount=data.get('amount'),
            currency=data.get('currency'),
            details=data.get('details'),
            counterparty=data.get('counterparty'),
            balance=data.get('balance'),
            balance_currency=data.get('balance_currency'),
            raw_message=data.get('raw_message')
        )
        
        # Handle timestamp if provided
        timestamp_str = data.get('timestamp')
        if timestamp_str:
            try:
                transaction.timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                # If timestamp format is invalid, use current time
                transaction.timestamp = datetime.now()
        
        return transaction
