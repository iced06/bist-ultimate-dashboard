"""Kayıtlı portföyler (sabit portföy) - Neon Postgres `bist.saved_portfolios` tablosu.

Streamlit Cloud'da kalıcı dosya sistemi olmadığı için sepet ve ayarlar veritabanında tutulur.
Tablo ilk kullanımda kendini oluşturur. Tüm fonksiyonlar (ok, sonuç/hata_mesajı) döner;
arayüz hatayı gösterir, uygulama bağlantı yoksa bile çalışmaya devam eder.
"""

try:
    import psycopg2.extras as _pgx
except ImportError:                                     # pragma: no cover
    _pgx = None

NAME_MAX = 80

_DDL = """
CREATE TABLE IF NOT EXISTS saved_portfolios (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(80) NOT NULL UNIQUE,
    tickers    JSONB NOT NULL,
    settings   JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_portfolios_default
    ON saved_portfolios (is_default) WHERE is_default;
"""
_ready_conns: set = set()


def _conn():
    from sirket_raporlari import _get_live_connection
    conn = _get_live_connection()
    if conn is None:
        return None
    if id(conn) not in _ready_conns:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO bist, public;")
            cur.execute(_DDL)
        _ready_conns.add(id(conn))
    return conn


def _clean(name) -> str:
    return " ".join(str(name or "").split())[:NAME_MAX]


def _run(fn):
    try:
        conn = _conn()
        if conn is None:
            return False, "Veritabanı bağlantısı yok."
        return True, fn(conn)
    except Exception as e:                              # bağlantı/kota hatası arayüzde gösterilir
        return False, f"{type(e).__name__}: {e}"


def list_portfolios():
    """[{name, tickers, settings, is_default, updated_at}] - en son güncellenen önce."""
    def go(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT name, tickers, settings, is_default, updated_at "
                        "FROM saved_portfolios ORDER BY updated_at DESC")
            return [dict(name=r[0], tickers=list(r[1] or []), settings=dict(r[2] or {}),
                         is_default=bool(r[3]), updated_at=r[4]) for r in cur.fetchall()]
    return _run(go)


def save_portfolio(name, tickers, settings, overwrite=True):
    """Upsert. overwrite=False ise aynı isim varsa kaydetmez (False, mesaj)."""
    name = _clean(name)
    if not name:
        return False, "Portföy adı boş olamaz."
    tickers = [str(t) for t in dict.fromkeys(tickers)]
    if not tickers:
        return False, "Boş sepet kaydedilemez."

    def go(conn):
        with conn.cursor() as cur:
            if not overwrite:
                cur.execute("SELECT 1 FROM saved_portfolios WHERE name = %s", (name,))
                if cur.fetchone():
                    raise ValueError(f"'{name}' adında bir portföy zaten var; onu seçip Güncelle'yi kullan.")
            cur.execute("""
                INSERT INTO saved_portfolios (name, tickers, settings, is_default)
                VALUES (%s, %s, %s, NOT EXISTS (SELECT 1 FROM saved_portfolios))
                ON CONFLICT (name) DO UPDATE SET tickers = EXCLUDED.tickers,
                    settings = EXCLUDED.settings, updated_at = now()
            """, (name, _pgx.Json(tickers), _pgx.Json(settings or {})))
        return name
    return _run(go)


def delete_portfolio(name):
    def go(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_portfolios WHERE name = %s RETURNING is_default", (_clean(name),))
            row = cur.fetchone()
            if row and row[0]:                          # silinen varsayılandıysa en yeniyi varsayılan yap
                cur.execute("UPDATE saved_portfolios SET is_default = TRUE WHERE id = "
                            "(SELECT id FROM saved_portfolios ORDER BY updated_at DESC LIMIT 1)")
        return bool(row)
    return _run(go)


def set_default(name):
    """name=None → varsayılanı kaldırır."""
    def go(conn):
        with conn.cursor() as cur:
            cur.execute("UPDATE saved_portfolios SET is_default = FALSE WHERE is_default")
            if name:
                cur.execute("UPDATE saved_portfolios SET is_default = TRUE WHERE name = %s", (_clean(name),))
        return True
    return _run(go)
