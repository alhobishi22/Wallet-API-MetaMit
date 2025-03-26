from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

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
    
    # خصائص افتراضية للأعمدة الجديدة
    @property
    def transaction_id(self):
        """Get a unique transaction ID."""
        # إذا لم يكن هناك عمود transaction_id في قاعدة البيانات، استخدم معرف فريد مبني على معرف المعاملة
        return f"TX{self.id:06d}"
    
    @property
    def is_confirmed(self):
        """Check if transaction is confirmed."""
        # استخدم القيمة المحسوبة في الذاكرة إذا كانت موجودة
        return getattr(self, 'is_confirmed_value', False)
    
    def to_dict(self):
        """Convert transaction to dictionary."""
        return {
            'id': self.id,
            'transaction_id': self.transaction_id,
            'wallet': self.wallet,
            'type': self.type,
            'amount': self.amount,
            'currency': self.currency,
            'details': self.details,
            'counterparty': self.counterparty,
            'balance': self.balance,
            'balance_currency': self.balance_currency,
            'raw_message': self.raw_message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_confirmed': self.is_confirmed
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create transaction from dictionary."""
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
        timestamp = data.get('timestamp')
        if timestamp:
            try:
                if isinstance(timestamp, str):
                    transaction.timestamp = datetime.fromisoformat(timestamp)
                else:
                    transaction.timestamp = timestamp
            except (ValueError, TypeError):
                # If timestamp format is invalid, use current time
                transaction.timestamp = datetime.now()
        
        return transaction
