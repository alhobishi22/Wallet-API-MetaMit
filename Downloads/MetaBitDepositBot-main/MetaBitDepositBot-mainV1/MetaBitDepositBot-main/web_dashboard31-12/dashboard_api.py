from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import ssl
from typing import List, Dict
from datetime import datetime
import json
from pydantic import BaseModel

app = FastAPI(title="Dashboard API")

# تكوين CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # في بيئة الإنتاج، حدد النطاقات المسموح بها
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تكوين قاعدة البيانات
DATABASE_URL = "postgres://alhubaishi:jAtNbIdExraRUo1ZosQ1f0EEGz3fMZWt@dpg-csserj9u0jms73ea9gmg-a.singapore-postgres.render.com:5432/meta_bit_database"

async def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات مع دعم SSL"""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        conn = await asyncpg.connect(DATABASE_URL, ssl=ssl_context)
        return conn
    except Exception as e:
        print(f"خطأ في الاتصال بقاعدة البيانات: {str(e)}")
        raise HTTPException(status_code=500, detail="خطأ في الاتصال بقاعدة البيانات")

class DashboardStats(BaseModel):
    failed_count: int
    pending_count: int
    completed_count: int
    total_count: int
    pending_amount: float
    completed_amount: float

class Transaction(BaseModel):
    withdrawal_id: str
    user_id: int
    currency: str
    amount: float
    status: str
    created_at: datetime

@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """جلب إحصائيات لوحة التحكم"""
    try:
        conn = await get_db_connection()
        query = """
            SELECT 
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_count,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
                COUNT(*) as total_count,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN crypto_amount ELSE 0 END), 0) as pending_amount,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END), 0) as completed_amount
            FROM withdrawal_requests
        """
        
        result = await conn.fetchrow(query)
        await conn.close()
        
        return {
            "failed_count": result['failed_count'],
            "pending_count": result['pending_count'],
            "completed_count": result['completed_count'],
            "total_count": result['total_count'],
            "pending_amount": float(result['pending_amount']),
            "completed_amount": float(result['completed_amount'])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard/recent-transactions", response_model=List[Transaction])
async def get_recent_transactions():
    """جلب آخر العمليات"""
    try:
        conn = await get_db_connection()
        query = """
            SELECT 
                withdrawal_id,
                user_id,
                crypto_currency as currency,
                crypto_amount as amount,
                status,
                created_at
            FROM withdrawal_requests 
            ORDER BY created_at DESC 
            LIMIT 10
        """
        
        transactions = await conn.fetch(query)
        await conn.close()
        
        return [{
            "withdrawal_id": tx['withdrawal_id'],
            "user_id": tx['user_id'],
            "currency": tx['currency'],
            "amount": float(tx['amount']),
            "status": tx['status'],
            "created_at": tx['created_at']
        } for tx in transactions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def start():
    """دالة لتشغيل التطبيق"""
    import uvicorn
    uvicorn.run("dashboard_api:app", host="127.0.0.1", port=8080, reload=True)

if __name__ == "__main__":
    start()