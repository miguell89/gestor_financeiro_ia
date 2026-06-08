from datetime import date

from app.database import db
from app.services.finance_service import generate_monthly_fixed_bill_occurrences, generate_recurring_revenues
from app.services.log_service import create_log


def run_daily_tasks():
    today = date.today()
    with db() as conn:
        users = conn.execute("select id from users where status = 'ativo'").fetchall()

    for user in users:
        generate_monthly_fixed_bill_occurrences(user["id"], today.month, today.year)
        generate_recurring_revenues(user["id"], today)

    with db() as conn:
        conn.execute(
            """
            update fixed_bill_occurrences
            set status = 'overdue',
                updated_at = current_timestamp
            where status = 'pending'
              and due_date < date('now')
            """
        )

    create_log(
        "info",
        "scheduler",
        "daily_tasks",
        "Ocorrencias mensais, receitas recorrentes e contas vencidas atualizadas",
        details={"date": today.isoformat()},
    )


if __name__ == "__main__":
    run_daily_tasks()
