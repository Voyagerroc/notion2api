import contextlib
import errno
import logging
import os
import random
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import URLError


logger = logging.getLogger(__name__)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "tasks.db",
)

# Tüm zaman damgaları Unix zamanı, saniye cinsindedir.
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
SQLITE_TIMEOUT_SECONDS = 30

DEFAULT_MAX_RETRIES = 3
MAX_CONFIGURABLE_RETRIES = 100
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300

MAX_RESULT_BYTES = 256 * 1024
MAX_ERROR_BYTES = 8 * 1024
TRUNCATION_MARKER = "\n...[çıktı boyut sınırı nedeniyle kesildi]"


def _now() -> int:
    return int(time.time())


def _bounded_text(value: Any, max_bytes: int) -> Optional[str]:
    """Metni UTF-8 byte sınırına indir; çok büyük ara kopyalardan kaçın."""
    if value is None:
        return None

    text = value if isinstance(value, str) else str(value)

    prefix = text[: max_bytes + 1]
    encoded = prefix.encode("utf-8", errors="replace")

    if len(text) <= max_bytes and len(encoded) <= max_bytes:
        return encoded.decode("utf-8")

    marker = TRUNCATION_MARKER.encode("utf-8")
    if len(marker) >= max_bytes:
        return marker[:max_bytes].decode("utf-8", errors="ignore")

    content_limit = max_bytes - len(marker)
    content = encoded[:content_limit].decode("utf-8", errors="ignore")
    return content + TRUNCATION_MARKER


@contextlib.contextmanager
def _get_conn() -> Iterator[sqlite3.Connection]:
    """
    Bağlantıyı her kullanım sonunda kapat.
    isolation_level=None: açıkça BEGIN yapılmadığında SQLite autocommit.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = %d" % (SQLITE_TIMEOUT_SECONDS * 1000))

    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def _immediate_transaction(
    conn: sqlite3.Connection,
) -> Iterator[sqlite3.Connection]:
    """
    Yazma hakkını SELECT öncesinde alarak yarış durumunu önle.
    SQLite aynı veritabanında aynı anda tek yazara izin verir.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def init_task_db() -> None:
    """Tabloyu oluştur ve eski kurulumları veri kaybetmeden yükselt."""
    with _get_conn() as conn:
        with _immediate_transaction(conn):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    priority TEXT DEFAULT 'normal',
                    result TEXT,
                    error TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
                """
            )

            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }

            migrations = {
                "retry_count": "INTEGER NOT NULL DEFAULT 0",
                "max_retries": (
                    "INTEGER NOT NULL DEFAULT %d" % DEFAULT_MAX_RETRIES
                ),
                "next_attempt_at": "INTEGER",
                "started_at": "INTEGER",
                "finished_at": "INTEGER",
                "lease_token": "TEXT",
                "lease_until": "INTEGER",
                "phase": "TEXT NOT NULL DEFAULT 'execute'",
            }

            for name, definition in migrations.items():
                if name not in existing:
                    conn.execute(
                        "ALTER TABLE tasks ADD COLUMN %s %s" % (name, definition)
                    )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_pending
                ON tasks(status, next_attempt_at, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_lease
                ON tasks(status, lease_until)
                """
            )


def create_task(
    title: str,
    description: str,
    priority: str = "normal",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """
    max_retries, ilk denemeden SONRA yapılabilecek tekrar sayısıdır.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title boş olmayan bir metin olmalıdır.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description boş olmayan bir metin olmalıdır.")
    if priority not in ("high", "normal", "low"):
        raise ValueError("priority: high, normal veya low olmalıdır.")
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= MAX_CONFIGURABLE_RETRIES
    ):
        raise ValueError(
            "max_retries 0 ile %d arasında bir tam sayı olmalıdır."
            % MAX_CONFIGURABLE_RETRIES
        )

    task_id = str(uuid.uuid4())[:8]
    now = _now()

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, title, description, status, priority,
                created_at, updated_at, next_attempt_at,
                retry_count, max_retries, phase
            )
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, 0, ?, 'execute')
            """,
            (task_id, title, description, priority, now, now, now, max_retries),
        )

    return task_id


def list_tasks(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        if status is not None:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()

    return [dict(row) for row in rows]


def get_next_pending_task() -> Optional[Dict[str, Any]]:
    """Gözlem amaçlıdır."""
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'pending'
              AND COALESCE(next_attempt_at, 0) <= ?
            ORDER BY
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    ELSE 3
                END,
                created_at ASC,
                id ASC
            LIMIT 1
            """,
            (_now(),),
        ).fetchone()

    return dict(row) if row else None


def update_task_status(
    task_id: str,
    status: str,
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if status not in ("pending", "completed", "failed"):
        raise ValueError(
            "status pending, completed veya failed olmalıdır; "
            "running yalnızca atomik lease ile ayarlanabilir."
        )

    now = _now()
    safe_result = _bounded_text(result, MAX_RESULT_BYTES)
    safe_error = _bounded_text(error, MAX_ERROR_BYTES)

    with _get_conn() as conn:
        with _immediate_transaction(conn):
            row = conn.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()

            if row is None:
                raise ValueError("Görev bulunamadı: %s" % task_id)
            if row["status"] == "running":
                raise RuntimeError(
                    "Çalışan görev lease dışından değiştirilemez."
                )

            if status == "pending":
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'pending',
                        phase = 'execute',
                        retry_count = 0,
                        next_attempt_at = ?,
                        started_at = NULL,
                        finished_at = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        result = ?,
                        error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, safe_result, safe_error, now, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?,
                        result = COALESCE(?, result),
                        error = COALESCE(?, error),
                        finished_at = ?,
                        lease_token = NULL,
                        lease_until = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status, safe_result, safe_error, now, now, task_id),
                )


def _retry_delay(retry_count: int) -> int:
    """Üst sınırı olan exponential backoff ve rastgele jitter."""
    exponent = min(max(retry_count - 1, 0), 16)
    base = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** exponent))
    return min(RETRY_MAX_SECONDS, base + random.randint(0, max(1, base // 4)))


def _recover_expired_leases(conn: sqlite3.Connection, now: int) -> None:
    """Çöken worker'ların görevlerini kurtar."""
    expired = conn.execute(
        """
        SELECT id, retry_count, max_retries
        FROM tasks
        WHERE status = 'running'
          AND (lease_until IS NULL OR lease_until <= ?)
        """,
        (now,),
    ).fetchall()

    for row in expired:
        retries = int(row["retry_count"] or 0) + 1
        max_retries = int(
            row["max_retries"]
            if row["max_retries"] is not None
            else DEFAULT_MAX_RETRIES
        )

        if retries <= max_retries:
            status = "pending"
            next_attempt_at = now + _retry_delay(retries)
            finished_at = None
        else:
            status = "failed"
            next_attempt_at = None
            finished_at = now

        conn.execute(
            """
            UPDATE tasks
            SET status = ?,
                retry_count = ?,
                next_attempt_at = ?,
                finished_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                error = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND (lease_until IS NULL OR lease_until <= ?)
            """,
            (
                status,
                retries,
                next_attempt_at,
                finished_at,
                "Worker lease süresi doldu; önceki denemenin sonucu belirsiz.",
                now,
                row["id"],
                now,
            ),
        )


def _claim_next_task() -> Optional[Dict[str, Any]]:
    """Görevi seç ve lease'i atomik transaction ile al."""
    now = _now()
    token = uuid.uuid4().hex

    with _get_conn() as conn:
        with _immediate_transaction(conn):
            _recover_expired_leases(conn, now)

            row = conn.execute(
                """
                SELECT id
                FROM tasks
                WHERE status = 'pending'
                  AND COALESCE(next_attempt_at, 0) <= ?
                ORDER BY
                    CASE priority
                        WHEN 'high' THEN 1
                        WHEN 'normal' THEN 2
                        ELSE 3
                    END,
                    created_at ASC,
                    id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()

            if row is None:
                return None

            task_id = row["id"]
            changed = conn.execute(
                """
                UPDATE tasks
                SET status = 'running',
                    lease_token = ?,
                    lease_until = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (token, now + LEASE_SECONDS, now, now, task_id),
            ).rowcount

            if changed != 1:
                return None

            claimed = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()

            return dict(claimed)


def _renew_lease(task_id: str, token: str) -> bool:
    now = _now()
    with _get_conn() as conn:
        changed = conn.execute(
            """
            UPDATE tasks
            SET lease_until = ?, updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (now + LEASE_SECONDS, now, task_id, token, now),
        ).rowcount
    return changed == 1


def _owns_lease(task_id: str, token: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM tasks
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (task_id, token, _now()),
        ).fetchone()
    return row is not None


def _heartbeat(
    task_id: str,
    token: str,
    stop_event: threading.Event,
    lost_event: threading.Event,
) -> None:
    while not stop_event.wait(HEARTBEAT_SECONDS):
        try:
            if not _renew_lease(task_id, token):
                lost_event.set()
                logger.warning("Görev lease'i kaybedildi: %s", task_id)
                return
        except sqlite3.Error:
            logger.exception("Lease heartbeat hatası: %s", task_id)


def _status_code(exc: BaseException) -> Optional[int]:
    candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
    return None


def _is_retryable(exc: BaseException) -> bool:
    seen = set()
    current: Optional[BaseException] = exc

    transient_errno = {
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.EPIPE,
        errno.ETIMEDOUT,
    }

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        code = _status_code(current)
        if code is not None:
            if code in (408, 409, 425, 429) or 500 <= code <= 599:
                return True
            if 400 <= code <= 499:
                return False

        if isinstance(current, (TimeoutError, ConnectionError)):
            return True

        if isinstance(current, URLError):
            return True

        if isinstance(current, OSError) and current.errno in transient_errno:
            return True

        if type(current).__name__ in {
            "APITimeoutError",
            "APIConnectionError",
            "RateLimitError",
            "ServiceUnavailableError",
            "ConnectTimeout",
            "ReadTimeout",
            "ConnectionError",
            "NotionUpstreamError",
        }:
            return True

        current = current.__cause__ or current.__context__

    return False


def _mark_failure(task: Dict[str, Any], exc: Exception) -> bool:
    now = _now()
    retry_count = int(task["retry_count"] or 0) + 1
    max_retries = int(task["max_retries"])
    retry = _is_retryable(exc) and retry_count <= max_retries

    status = "pending" if retry else "failed"
    next_attempt_at = now + _retry_delay(retry_count) if retry else None
    finished_at = None if retry else now
    error = _bounded_text(
        "%s: %s" % (type(exc).__name__, exc),
        MAX_ERROR_BYTES,
    )

    with _get_conn() as conn:
        changed = conn.execute(
            """
            UPDATE tasks
            SET status = ?,
                retry_count = ?,
                next_attempt_at = ?,
                finished_at = ?,
                error = ?,
                lease_token = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (
                status,
                retry_count,
                next_attempt_at,
                finished_at,
                error,
                now,
                task["id"],
                task["lease_token"],
                now,
            ),
        ).rowcount

    return changed == 1


def _complete_task(
    task_id: str,
    token: str,
    result: Optional[str] = None,
) -> bool:
    now = _now()
    safe_result = _bounded_text(result, MAX_RESULT_BYTES)

    with _get_conn() as conn:
        changed = conn.execute(
            """
            UPDATE tasks
            SET status = 'completed',
                result = COALESCE(?, result),
                error = NULL,
                finished_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (safe_result, now, now, task_id, token, now),
        ).rowcount

    return changed == 1


def _queue_notion_save(task_id: str, token: str, result: str) -> bool:
    now = _now()
    safe_result = _bounded_text(result, MAX_RESULT_BYTES)

    with _get_conn() as conn:
        changed = conn.execute(
            """
            UPDATE tasks
            SET status = 'pending',
                phase = 'notion_save',
                result = ?,
                error = NULL,
                retry_count = 0,
                next_attempt_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND lease_token = ?
              AND lease_until > ?
            """,
            (safe_result, now, now, task_id, token, now),
        ).rowcount

    return changed == 1


def run_worker_cycle(
    client: Any,
    manager: Any,
    auto_save_notion: bool = False,
) -> bool:
    """
    Uygun bir görevin tek aşamasını işler.
    """
    task = _claim_next_task()
    if task is None:
        return False

    task_id = task["id"]
    token = task["lease_token"]
    stop_event = threading.Event()
    lost_event = threading.Event()

    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(task_id, token, stop_event, lost_event),
        name="task-heartbeat-%s" % task_id,
        daemon=True,
    )
    heartbeat.start()

    print(f"\n\033[1;35m[Kuyruk Worker]\033[0m Görev devralındı: #{task_id} (Faz: {task['phase']}) - '{task['title']}'")

    try:
        if task["phase"] == "execute":
            from app.agent_loop import run_agent_loop

            conv_id = manager.new_conversation()
            output = run_agent_loop(
                client=client,
                manager=manager,
                conv_id=conv_id,
                user_goal=task["description"],
                max_steps=8,
            )

            if not isinstance(output, str):
                raise TypeError(
                    "run_agent_loop metin döndürmelidir; alınan tür: %s"
                    % type(output).__name__
                )

            if lost_event.is_set() or not _owns_lease(task_id, token):
                print(f"[Uyarı] Lease kaybedildi; sonuç uygulanamadı: #{task_id}")
                return True

            if auto_save_notion:
                changed = _queue_notion_save(task_id, token, output)
                if changed:
                    print(f"\033[1;32m[Kuyruk Worker]\033[0m ✓ Kod döngüsü tamamlandı, Notion kayıt fazına aktarıldı: #{task_id}")
            else:
                changed = _complete_task(task_id, token, output)
                if changed:
                    print(f"\033[1;32m[Kuyruk Worker]\033[0m ✓ Görev tamamlandı: #{task_id}")

        elif task["phase"] == "notion_save":
            from ask_notion import save_to_notion

            if lost_event.is_set() or not _owns_lease(task_id, token):
                print(f"[Uyarı] Lease kaybedildi; Notion kaydı başlatılmadı: #{task_id}")
                return True

            saved = save_to_notion(
                "Görev Sonucu: %s" % task["title"],
                task["result"] if task["result"] is not None else "",
            )
            if not saved:
                raise RuntimeError("save_to_notion başarısız oldu.")

            if not _complete_task(task_id, token):
                print(f"[Uyarı] Notion kaydedildi fakat lease kaybedildi: #{task_id}")
            else:
                print(f"\033[1;32m[Kuyruk Worker]\033[0m ✓ Görev ve Notion kaydı başarıyla tamamlandı: #{task_id}")

        else:
            raise ValueError("Bilinmeyen görev aşaması: %s" % task["phase"])

    except Exception as exc:
        print(f"\033[1;31m[Kuyruk Hatası]\033[0m Görev hata verdi: #{task_id}: {exc}")
        try:
            _mark_failure(task, exc)
        except sqlite3.Error:
            pass

    finally:
        stop_event.set()
        heartbeat.join(timeout=SQLITE_TIMEOUT_SECONDS + 1)

    return True


# Tabloyu otomatik başlat
init_task_db()
