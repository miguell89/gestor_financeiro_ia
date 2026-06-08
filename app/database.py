import sqlite3
import re
from contextlib import contextmanager
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from config.settings import settings


try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


def using_postgres():
    return bool(settings.DATABASE_URL)


def _pg_sql(sql):
    sql = sql.strip()
    was_insert_ignore = bool(re.match(r"insert\s+or\s+ignore\s+into", sql, re.IGNORECASE))
    sql = re.sub(r"integer primary key autoincrement", "serial primary key", sql, flags=re.IGNORECASE)
    sql = re.sub(r",\s*foreign key\s*\([^)]+\)\s*references\s+\w+\([^)]+\)", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"text default current_timestamp", "text default current_timestamp::text", sql, flags=re.IGNORECASE)
    sql = re.sub(r"datetime\('now'\)", "current_timestamp::text", sql, flags=re.IGNORECASE)
    sql = re.sub(r"date\('now'\)", "current_date::text", sql, flags=re.IGNORECASE)
    sql = re.sub(r"date\('now',\s*\?\)", "(current_date + (%s)::interval)::text", sql, flags=re.IGNORECASE)
    sql = re.sub(r"insert\s+or\s+ignore\s+into", "insert into", sql, flags=re.IGNORECASE)
    sql = re.sub(r"cast\(strftime\('%d',\s*([^)]+)\)\s+as\s+integer\)", r"extract(day from (\1)::timestamp)::integer", sql, flags=re.IGNORECASE)
    sql = re.sub(r"cast\(strftime\('%m',\s*([^)]+)\)\s+as\s+integer\)", r"extract(month from (\1)::timestamp)::integer", sql, flags=re.IGNORECASE)
    sql = re.sub(r"cast\(strftime\('%Y',\s*([^)]+)\)\s+as\s+integer\)", r"extract(year from (\1)::timestamp)::integer", sql, flags=re.IGNORECASE)
    if was_insert_ignore and "on conflict" not in sql.lower():
        sql += " on conflict do nothing"
    if sql.lower().startswith("insert into") and "on conflict" not in sql.lower() and "returning" not in sql.lower():
        sql += " returning id"
    return sql.replace("?", "%s")


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


class PostgresConnection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        sql_clean = sql.strip()
        pragma = re.match(r"pragma\s+table_info\((\w+)\)", sql_clean, re.IGNORECASE)
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if pragma:
            cursor.execute(
                """
                select column_name as name
                from information_schema.columns
                where table_schema = 'public' and table_name = %s
                order by ordinal_position
                """,
                (pragma.group(1),),
            )
            return PostgresCursor(cursor)
        cursor.execute(_pg_sql(sql), params)
        wrapped = PostgresCursor(cursor)
        if sql_clean.lower().startswith("insert into") and "on conflict" not in sql_clean.lower():
            row = cursor.fetchone()
            wrapped.lastrowid = row["id"] if row and "id" in row else None
        return wrapped

    def executemany(self, sql, seq_of_params):
        last_cursor = None
        for params in seq_of_params:
            last_cursor = self.execute(sql, params)
        return last_cursor

    def executescript(self, script):
        for statement in [item.strip() for item in script.split(";") if item.strip()]:
            self.execute(statement)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_connection():
    if using_postgres():
        if psycopg2 is None:
            raise RuntimeError("psycopg2-binary nao esta instalado. Rode pip install -r requirements.txt.")
        return PostgresConnection(psycopg2.connect(settings.DATABASE_URL))
    settings.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
      yield conn
      conn.commit()
    finally:
      conn.close()


def init_db():
    with db() as conn:
        conn.executescript(
            """
            create table if not exists users (
              id integer primary key autoincrement,
              name text not null,
              email text,
              password_hash text,
              telegram_id text unique,
              telegram_username text,
              telegram_first_name text,
              role text not null default 'user',
              status text not null default 'ativo',
              last_login_at text,
              last_interaction_at text,
              assistant_tone text default 'divertido',
              created_at text default current_timestamp
            );

            create table if not exists categories (
              id integer primary key autoincrement,
              name text not null unique,
              color text not null,
              monthly_limit real default 0,
              icon text default '$',
              type text not null default 'geral',
              active integer not null default 1
            );

            create table if not exists accounts (
              id integer primary key autoincrement,
              name text not null,
              type text not null,
              balance real default 0
            );

            create table if not exists cards (
              id integer primary key autoincrement,
              name text not null,
              limit_value real default 0,
              closing_day integer,
              due_day integer
            );

            create table if not exists transactions (
              id integer primary key autoincrement,
              user_id integer,
              type text not null,
              date text not null,
              amount real not null,
              category_id integer,
              description text,
              payment_method text,
              status text not null default 'pago',
              origin text not null default 'manual',
              fixed_bill_id integer,
              revenue_id integer,
              project_center text,
              notes text,
              is_recurring integer not null default 0,
              recurrence_frequency text,
              recurrence_day integer,
              recurrence_end_date text,
              reminder_enabled integer not null default 0,
              split_enabled integer not null default 0,
              receipt_path text,
              created_at text default current_timestamp,
              foreign key (user_id) references users(id),
              foreign key (category_id) references categories(id),
              foreign key (fixed_bill_id) references fixed_bills(id)
            );

            create table if not exists revenues (
              id integer primary key autoincrement,
              user_id integer,
              name text not null,
              category text not null default 'Outros',
              expected_amount real not null,
              expected_date text not null,
              received_date text,
              type text not null default 'pontual',
              status text not null default 'prevista',
              recurrence text not null default 'mensal',
              is_recurring integer not null default 0,
              recurrence_interval text default 'mensal',
              recurrence_day integer,
              recurrence_start_date text,
              ask_value_before_generate integer not null default 0,
              auto_update_default_value integer not null default 0,
              default_amount real,
              next_expected_date text,
              last_generated_date text,
              notify_day_before integer not null default 1,
              notify_due_day integer not null default 1,
              notify_overdue integer not null default 1,
              notify_registered integer not null default 1,
              notes text,
              created_at text default current_timestamp,
              foreign key (user_id) references users(id)
            );

            create table if not exists fixed_bills (
              id integer primary key autoincrement,
              user_id integer,
              name text not null,
              expected_amount real not null,
              default_amount real,
              due_day integer not null,
              category_id integer,
              status text not null default 'pendente',
              recurrence text not null default 'mensal',
              recurrence_type text default 'mensal',
              recurrence_interval text default 'mensal',
              start_date text,
              payment_method text,
              alert_days_before integer default 1,
              ask_value_before_generate integer not null default 0,
              auto_update_default_value integer not null default 0,
              is_installment integer not null default 0,
              total_installments integer,
              installment_amount real,
              paid_installments integer not null default 0,
              installment_start_date text,
              installment_total_amount real,
              notes text,
              active integer not null default 1,
              postponed_to text,
              created_at text default current_timestamp,
              updated_at text default current_timestamp,
              foreign key (user_id) references users(id),
              foreign key (category_id) references categories(id)
            );

            create table if not exists fixed_bill_occurrences (
              id integer primary key autoincrement,
              fixed_bill_id integer not null,
              user_id integer,
              reference_month integer not null,
              reference_year integer not null,
              due_date text not null,
              amount real not null,
              status text not null default 'pending',
              paid_at text,
              postponed_to_month integer,
              postponed_to_year integer,
              transaction_id integer,
              notes text,
              installment_number integer,
              total_installments integer,
              is_installment_occurrence integer not null default 0,
              was_value_confirmed integer not null default 0,
              original_default_amount real,
              created_at text default current_timestamp,
              updated_at text default current_timestamp,
              unique(fixed_bill_id, reference_month, reference_year),
              foreign key (fixed_bill_id) references fixed_bills(id),
              foreign key (user_id) references users(id),
              foreign key (transaction_id) references transactions(id)
            );

            create table if not exists receipts (
              id integer primary key autoincrement,
              user_id integer,
              file_path text,
              extracted_amount real,
              extracted_date text,
              merchant text,
              payment_type text,
              suggested_category text,
              status text default 'pendente',
              reference_month integer,
              reference_year integer,
              created_at text default current_timestamp
            );

            create table if not exists financial_attachments (
              id integer primary key autoincrement,
              user_id integer not null,
              linked_type text not null,
              linked_id integer not null,
              original_file_name text not null,
              stored_file_name text not null,
              file_path text not null,
              file_type text,
              file_size integer default 0,
              source text not null default 'manual_upload',
              gemini_extracted_json text,
              created_at text default current_timestamp,
              updated_at text default current_timestamp,
              foreign key (user_id) references users(id)
            );

            create table if not exists system_logs (
              id integer primary key autoincrement,
              created_at text default current_timestamp,
              level text not null,
              source text not null,
              user_id integer,
              telegram_id text,
              action text not null,
              message text,
              details_json text,
              foreign key (user_id) references users(id)
            );

            create table if not exists alerts (
              id integer primary key autoincrement,
              user_id integer,
              type text not null,
              message text not null,
              status text default 'pendente',
              scheduled_for text,
              reference_month integer,
              reference_year integer,
              created_at text default current_timestamp
            );

            create table if not exists budgets (
              id integer primary key autoincrement,
              category_id integer not null,
              month text not null,
              limit_value real not null,
              foreign key (category_id) references categories(id)
            );

            create table if not exists assistant_messages (
              id integer primary key autoincrement,
              user_id integer,
              role text not null,
              message text not null,
              reference_month integer,
              reference_year integer,
              created_at text default current_timestamp
            );

            create table if not exists telegram_users (
              id integer primary key autoincrement,
              telegram_id text not null unique,
              user_id integer,
              first_name text,
              created_at text default current_timestamp,
              foreign key (user_id) references users(id)
            );

            create table if not exists telegram_link_codes (
              id integer primary key autoincrement,
              user_id integer not null,
              code text not null unique,
              expires_at text not null,
              used_at text,
              created_at text default current_timestamp,
              foreign key (user_id) references users(id)
            );

            create table if not exists goals (
              id integer primary key autoincrement,
              user_id integer not null,
              name text not null,
              description text,
              type text not null default 'Outros',
              target_amount real not null default 0,
              current_amount real not null default 0,
              monthly_target_amount real not null default 0,
              start_date text,
              deadline_date text,
              icon text default 'G',
              color text default '#8b5cf6',
              status text not null default 'no_ritmo',
              created_at text default current_timestamp,
              updated_at text default current_timestamp,
              foreign key (user_id) references users(id)
            );

            create table if not exists goal_contributions (
              id integer primary key autoincrement,
              goal_id integer not null,
              user_id integer not null,
              amount real not null,
              contribution_date text not null,
              source text not null default 'manual',
              source_id integer,
              notes text,
              created_at text default current_timestamp,
              foreign key (goal_id) references goals(id),
              foreign key (user_id) references users(id)
            );
            """
        )

        columns = [row["name"] for row in conn.execute("pragma table_info(users)").fetchall()]
        user_migrations = {
            "password_hash": "alter table users add column password_hash text",
            "telegram_id": "alter table users add column telegram_id text",
            "telegram_username": "alter table users add column telegram_username text",
            "telegram_first_name": "alter table users add column telegram_first_name text",
            "role": "alter table users add column role text not null default 'user'",
            "status": "alter table users add column status text not null default 'ativo'",
            "last_login_at": "alter table users add column last_login_at text",
            "last_interaction_at": "alter table users add column last_interaction_at text",
        }
        for column, sql in user_migrations.items():
            if column not in columns:
                conn.execute(sql)

        for table in ("transactions", "fixed_bills", "receipts", "alerts", "assistant_messages"):
            table_columns = [row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()]
            if "user_id" not in table_columns:
                conn.execute(f"alter table {table} add column user_id integer")

        category_columns = [row["name"] for row in conn.execute("pragma table_info(categories)").fetchall()]
        category_migrations = {
            "icon": "alter table categories add column icon text default '$'",
            "type": "alter table categories add column type text not null default 'geral'",
            "active": "alter table categories add column active integer not null default 1",
        }
        for column, sql in category_migrations.items():
            if column not in category_columns:
                conn.execute(sql)
        conn.execute("update categories set icon = coalesce(nullif(icon, ''), '$')")
        conn.execute("update categories set type = coalesce(nullif(type, ''), 'geral')")
        conn.execute("update categories set active = 1 where active is null")
        ensure_default_categories(conn)

        reference_date_columns = {
            "receipts": "coalesce(extracted_date, created_at, date('now'))",
            "alerts": "coalesce(scheduled_for, created_at, date('now'))",
            "assistant_messages": "coalesce(created_at, date('now'))",
        }
        for table, date_expr in reference_date_columns.items():
            table_columns = [row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()]
            if "reference_month" not in table_columns:
                conn.execute(f"alter table {table} add column reference_month integer")
            if "reference_year" not in table_columns:
                conn.execute(f"alter table {table} add column reference_year integer")
            conn.execute(
                f"""
                update {table}
                set reference_month = cast(strftime('%m', {date_expr}) as integer),
                    reference_year = cast(strftime('%Y', {date_expr}) as integer)
                where reference_month is null or reference_year is null
                """
            )

        conn.execute(
            """
            create table if not exists financial_attachments (
              id integer primary key autoincrement,
              user_id integer not null,
              linked_type text not null,
              linked_id integer not null,
              original_file_name text not null,
              stored_file_name text not null,
              file_path text not null,
              file_type text,
              file_size integer default 0,
              source text not null default 'manual_upload',
              gemini_extracted_json text,
              created_at text default current_timestamp,
              updated_at text default current_timestamp,
              foreign key (user_id) references users(id)
            )
            """
        )
        attachment_columns = [row["name"] for row in conn.execute("pragma table_info(financial_attachments)").fetchall()]
        attachment_migrations = {
            "source": "alter table financial_attachments add column source text not null default 'manual_upload'",
            "gemini_extracted_json": "alter table financial_attachments add column gemini_extracted_json text",
            "updated_at": "alter table financial_attachments add column updated_at text",
        }
        for column, sql in attachment_migrations.items():
            if column not in attachment_columns:
                conn.execute(sql)

        fixed_bill_columns = [row["name"] for row in conn.execute("pragma table_info(fixed_bills)").fetchall()]
        fixed_bill_migrations = {
            "active": "alter table fixed_bills add column active integer not null default 1",
            "created_at": "alter table fixed_bills add column created_at text",
            "updated_at": "alter table fixed_bills add column updated_at text",
            "default_amount": "alter table fixed_bills add column default_amount real",
            "payment_method": "alter table fixed_bills add column payment_method text",
            "notes": "alter table fixed_bills add column notes text",
            "ask_value_before_generate": "alter table fixed_bills add column ask_value_before_generate integer not null default 0",
            "auto_update_default_value": "alter table fixed_bills add column auto_update_default_value integer not null default 0",
            "recurrence_type": "alter table fixed_bills add column recurrence_type text default 'mensal'",
            "recurrence_interval": "alter table fixed_bills add column recurrence_interval text default 'mensal'",
            "start_date": "alter table fixed_bills add column start_date text",
            "is_installment": "alter table fixed_bills add column is_installment integer not null default 0",
            "total_installments": "alter table fixed_bills add column total_installments integer",
            "installment_amount": "alter table fixed_bills add column installment_amount real",
            "paid_installments": "alter table fixed_bills add column paid_installments integer not null default 0",
            "installment_start_date": "alter table fixed_bills add column installment_start_date text",
            "installment_total_amount": "alter table fixed_bills add column installment_total_amount real",
        }
        for column, sql in fixed_bill_migrations.items():
            if column not in fixed_bill_columns:
                conn.execute(sql)
        conn.execute("update fixed_bills set default_amount = expected_amount where default_amount is null")
        conn.execute("update fixed_bills set recurrence_type = coalesce(nullif(recurrence, ''), 'mensal') where recurrence_type is null or recurrence_type = ''")
        conn.execute("update fixed_bills set recurrence_interval = coalesce(nullif(recurrence, ''), 'mensal') where recurrence_interval is null or recurrence_interval = ''")
        conn.execute("update fixed_bills set start_date = substr(coalesce(created_at, current_timestamp), 1, 10) where start_date is null or start_date = ''")
        conn.execute("update fixed_bills set payment_method = 'boleto' where payment_method is null or payment_method = ''")
        conn.execute("update fixed_bills set installment_amount = expected_amount where is_installment = 1 and installment_amount is null")
        conn.execute("update fixed_bills set installment_total_amount = coalesce(total_installments, 0) * coalesce(installment_amount, expected_amount) where is_installment = 1 and installment_total_amount is null")

        occurrence_columns = [row["name"] for row in conn.execute("pragma table_info(fixed_bill_occurrences)").fetchall()]
        occurrence_migrations = {
            "installment_number": "alter table fixed_bill_occurrences add column installment_number integer",
            "total_installments": "alter table fixed_bill_occurrences add column total_installments integer",
            "is_installment_occurrence": "alter table fixed_bill_occurrences add column is_installment_occurrence integer not null default 0",
            "was_value_confirmed": "alter table fixed_bill_occurrences add column was_value_confirmed integer not null default 0",
            "original_default_amount": "alter table fixed_bill_occurrences add column original_default_amount real",
        }
        for column, sql in occurrence_migrations.items():
            if column not in occurrence_columns:
                conn.execute(sql)
        conn.execute("update fixed_bill_occurrences set original_default_amount = amount where original_default_amount is null")

        transaction_columns = [row["name"] for row in conn.execute("pragma table_info(transactions)").fetchall()]
        if "fixed_bill_id" not in transaction_columns:
            conn.execute("alter table transactions add column fixed_bill_id integer")
        if "revenue_id" not in transaction_columns:
            conn.execute("alter table transactions add column revenue_id integer")
        transaction_migrations = {
            "project_center": "alter table transactions add column project_center text",
            "notes": "alter table transactions add column notes text",
            "is_recurring": "alter table transactions add column is_recurring integer not null default 0",
            "recurrence_frequency": "alter table transactions add column recurrence_frequency text",
            "recurrence_day": "alter table transactions add column recurrence_day integer",
            "recurrence_end_date": "alter table transactions add column recurrence_end_date text",
            "reminder_enabled": "alter table transactions add column reminder_enabled integer not null default 0",
            "split_enabled": "alter table transactions add column split_enabled integer not null default 0",
            "receipt_path": "alter table transactions add column receipt_path text",
        }
        for column, sql in transaction_migrations.items():
            if column not in transaction_columns:
                conn.execute(sql)

        revenue_columns = [row["name"] for row in conn.execute("pragma table_info(revenues)").fetchall()]
        revenue_migrations = {
            "is_recurring": "alter table revenues add column is_recurring integer not null default 0",
            "recurrence_interval": "alter table revenues add column recurrence_interval text default 'mensal'",
            "recurrence_day": "alter table revenues add column recurrence_day integer",
            "recurrence_start_date": "alter table revenues add column recurrence_start_date text",
            "ask_value_before_generate": "alter table revenues add column ask_value_before_generate integer not null default 0",
            "auto_update_default_value": "alter table revenues add column auto_update_default_value integer not null default 0",
            "default_amount": "alter table revenues add column default_amount real",
            "next_expected_date": "alter table revenues add column next_expected_date text",
            "last_generated_date": "alter table revenues add column last_generated_date text",
            "notify_day_before": "alter table revenues add column notify_day_before integer not null default 1",
            "notify_due_day": "alter table revenues add column notify_due_day integer not null default 1",
            "notify_overdue": "alter table revenues add column notify_overdue integer not null default 1",
            "notify_registered": "alter table revenues add column notify_registered integer not null default 1",
        }
        for column, sql in revenue_migrations.items():
            if column not in revenue_columns:
                conn.execute(sql)
        conn.execute("update revenues set default_amount = expected_amount where default_amount is null")
        conn.execute("update revenues set recurrence_interval = coalesce(nullif(recurrence, ''), 'mensal') where recurrence_interval is null or recurrence_interval = ''")
        conn.execute("update revenues set recurrence_day = cast(strftime('%d', expected_date) as integer) where recurrence_day is null and expected_date is not null")
        conn.execute("update revenues set recurrence_start_date = expected_date where recurrence_start_date is null and expected_date is not null")

        conn.execute(
            "update users set password_hash = ? where email = ? and (password_hash is null or password_hash = '')",
            (generate_password_hash("123456"), "miguel@email.com"),
        )
        conn.execute("update users set role = 'user' where role is null or role = ''")
        conn.execute("update users set status = 'ativo' where status is null or status = ''")

        default_user = conn.execute("select id from users where email = ?", ("miguel@email.com",)).fetchone()
        if default_user:
            for table in ("transactions", "fixed_bills", "receipts", "alerts", "assistant_messages"):
                conn.execute(f"update {table} set user_id = ? where user_id is null", (default_user["id"],))

        conn.execute("update transactions set origin = 'telegram' where lower(origin) = 'telegram'")
        conn.execute(
            """
            update transactions
            set date = substr(created_at, 1, 10)
            where lower(origin) = 'telegram'
              and created_at is not null
              and substr(date, 1, 4) != substr(created_at, 1, 4)
            """
        )
        income_transactions = conn.execute(
            """
            select id, user_id, date, amount, description, origin
            from transactions
            where type = 'receita'
              and revenue_id is null
              and user_id is not null
            """
        ).fetchall()
        for item in income_transactions:
            cursor = conn.execute(
                """
                insert into revenues
                  (user_id, name, category, expected_amount, expected_date, received_date, type, status, recurrence, notes)
                values (?, ?, ?, ?, ?, ?, 'pontual', 'recebida', 'pontual', ?)
                """,
                (
                    item["user_id"],
                    item["description"] or "Receita",
                    "Salario" if "sal" in (item["description"] or "").lower() else "Pix recebido",
                    item["amount"],
                    item["date"],
                    item["date"],
                    f"Migrada de lancamento {item['origin']}",
                ),
            )
            conn.execute("update transactions set revenue_id = ? where id = ?", (cursor.lastrowid, item["id"]))
        migrate_fixed_bill_occurrences(conn)
        ensure_admin(conn)
        merge_telegram_duplicates(conn)


def normalize_bill_status(status):
    return {
        "pago": "paid",
        "pendente": "pending",
        "atrasado": "overdue",
        "adiado": "postponed",
        "cancelado": "canceled",
        "paid": "paid",
        "pending": "pending",
        "overdue": "overdue",
        "postponed": "postponed",
        "canceled": "canceled",
    }.get(status or "pending", "pending")


def migrate_fixed_bill_occurrences(conn):
    today = date.today()
    rows = conn.execute("select * from fixed_bills where user_id is not null").fetchall()
    fixed_columns = [row["name"] for row in conn.execute("pragma table_info(fixed_bills)").fetchall()]
    for bill in rows:
        legacy_status = bill["status"] if "status" in fixed_columns else "pendente"
        due_day = min(int(bill["due_day"] or today.day), 28)
        due_date = today.replace(day=due_day).isoformat()
        conn.execute(
            """
            insert or ignore into fixed_bill_occurrences
              (fixed_bill_id, user_id, reference_month, reference_year, due_date, amount, status)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill["id"],
                bill["user_id"],
                today.month,
                today.year,
                due_date,
                bill["expected_amount"],
                normalize_bill_status(legacy_status),
            ),
        )


def ensure_admin(conn):
    admin = conn.execute("select id from users where role = 'admin' limit 1").fetchone()
    if admin:
        return

    conn.execute(
        """
        insert into users
          (name, email, password_hash, telegram_id, role, status, assistant_tone)
        values (?, ?, ?, ?, 'admin', 'ativo', ?)
        """,
        (
            settings.ADMIN_NAME,
            settings.ADMIN_EMAIL,
            generate_password_hash(settings.ADMIN_PASSWORD),
            settings.ADMIN_TELEGRAM_ID or None,
            settings.ASSISTANT_TONE,
        ),
    )


def merge_telegram_duplicates(conn):
    duplicates = conn.execute(
        """
        select auto.id as auto_id, auto.telegram_id, auto.last_interaction_at, web.id as web_id
        from users auto
        join users web on lower(web.name) = lower(auto.name)
        where auto.email is null
          and auto.telegram_id is not null
          and web.email is not null
          and web.id != auto.id
          and web.role = 'user'
        """
    ).fetchall()

    for item in duplicates:
        for table in ("transactions", "fixed_bills", "receipts", "system_logs"):
            conn.execute(f"update {table} set user_id = ? where user_id = ?", (item["web_id"], item["auto_id"]))

        conn.execute(
            """
            update users
            set telegram_id = coalesce(telegram_id, ?),
                last_interaction_at = coalesce(last_interaction_at, ?)
            where id = ?
            """,
            (item["telegram_id"], item["last_interaction_at"], item["web_id"]),
        )
        conn.execute("delete from users where id = ?", (item["auto_id"],))


def seed_db():
    today = date.today()
    with db() as conn:
        user = conn.execute("select id from users where email = ?", ("miguel@email.com",)).fetchone()
        if user:
            user_id = user["id"]
        else:
            user_cursor = conn.execute(
                "insert into users (name, email, password_hash, role, status, assistant_tone) values (?, ?, ?, 'user', 'ativo', ?)",
                ("Miguel", "miguel@email.com", generate_password_hash("123456"), "divertido"),
            )
            user_id = user_cursor.lastrowid

        ensure_default_categories(conn)

        account_count = conn.execute("select count(*) as total from accounts where name = 'Carteira Principal'").fetchone()["total"]
        if not account_count:
            conn.execute("insert into accounts (name, type, balance) values ('Carteira Principal', 'corrente', 8420.50)")

        transaction_count = conn.execute("select count(*) as total from transactions where user_id = ?", (user_id,)).fetchone()["total"]
        if transaction_count:
            ensure_admin(conn)
            return

        transactions = [
            ("receita", today.replace(day=5).isoformat(), 6331.00, 1, "Salario mensal", "Pix", "pago", "manual"),
            ("despesa", today.isoformat(), 87.50, 2, "Mercado", "Debito", "pago", "Telegram"),
            ("despesa", (today - timedelta(days=1)).isoformat(), 99.90, 5, "Vivo Fibra", "Pix", "pago", "comprovante"),
            ("despesa", (today - timedelta(days=2)).isoformat(), 42.00, 6, "Cinema", "Cartao", "pago", "manual"),
            ("despesa", today.isoformat(), 18.90, 2, "Lanche", "Pix", "pago", "IA"),
        ]
        conn.executemany(
            """
            insert into transactions
              (type, date, amount, category_id, description, payment_method, status, origin, user_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(*item, user_id) for item in transactions],
        )

        fixed_bills = [
            ("Internet", 99.90, min(today.day + 1, 28), 5, "pendente", "mensal", 1, None),
            ("Energia", 210.40, min(today.day + 3, 28), 3, "pendente", "mensal", 2, None),
            ("Netflix", 55.90, min(today.day + 5, 28), 6, "pago", "mensal", 1, None),
            ("Financiamento", 1850.00, max(today.day - 1, 1), 3, "atrasado", "mensal", 3, None),
        ]
        conn.executemany(
            """
            insert into fixed_bills
              (name, expected_amount, due_day, category_id, status, recurrence, alert_days_before, postponed_to, user_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(*item, user_id) for item in fixed_bills],
        )
        ensure_admin(conn)


def ensure_default_categories(conn):
    defaults = [
        ("Salario", "#38f2a8", "$", "receita", 0),
        ("Beneficios", "#22d3ee", "+", "receita", 0),
        ("Aluguel", "#38bdf8", "C", "receita", 0),
        ("Investimentos", "#14d98b", "%", "receita", 0),
        ("Freelance", "#8b5cf6", "F", "receita", 0),
        ("Alimentacao", "#8b5cf6", "A", "despesa", 1800),
        ("Moradia", "#38bdf8", "M", "despesa", 2200),
        ("Transporte", "#f59e0b", "T", "despesa", 900),
        ("Saude", "#14d98b", "S", "despesa", 0),
        ("Educacao", "#3478f6", "E", "despesa", 0),
        ("Lazer", "#22d3ee", "L", "despesa", 800),
        ("Energia", "#f8c96a", "E", "conta_fixa", 0),
        ("Agua", "#38bdf8", "A", "conta_fixa", 0),
        ("Internet", "#3478f6", "I", "conta_fixa", 0),
        ("Telefone", "#f97388", "T", "conta_fixa", 250),
        ("Streaming", "#8b5cf6", "S", "conta_fixa", 0),
        ("Financiamento", "#f59e0b", "F", "conta_fixa", 0),
        ("Condominio", "#38f2a8", "C", "conta_fixa", 0),
        ("Outros", "#a9b7d3", "O", "geral", 0),
    ]
    for name, color, icon, category_type, limit in defaults:
        conn.execute(
            """
            insert into categories (name, color, icon, type, monthly_limit, active)
            values (?, ?, ?, ?, ?, 1)
            on conflict(name) do update set
              color = coalesce(nullif(categories.color, ''), excluded.color),
              icon = coalesce(nullif(categories.icon, ''), excluded.icon),
              type = case when categories.type is null or categories.type = '' or categories.type = 'geral' then excluded.type else categories.type end,
              monthly_limit = case when coalesce(categories.monthly_limit, 0) = 0 then excluded.monthly_limit else categories.monthly_limit end,
              active = coalesce(categories.active, 1)
            """,
            (name, color, icon, category_type, limit),
        )
