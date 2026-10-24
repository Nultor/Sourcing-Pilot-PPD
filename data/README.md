# Data & Database

How the data is organised, and how to run and look inside the Postgres database.

---

## 1. Folder structure

```
data/synthetic/
├── 2026Q3/
│   ├── raw/            ← messy source files (what the pipeline receives)
│   └── ground_truth/   ← clean "correct answers" (used to check the pipeline)
├── 2026Q4/
│   ├── raw/
│   └── ground_truth/
└── changes_2026Q3_to_2026Q4.csv
```

- **raw/** is what gets loaded into the database and cleaned.
- **ground_truth/** is never loaded into the pipeline. It is only used to test the results.

---

## 2. Start and stop the database

Postgres runs in Docker. The settings (user, password, database name, port) are in `.env` in the project root.

Run these from the project root:

| What | Command |
|---|---|
| Start | `docker compose up -d` |
| Check it's running (should say `healthy`) | `docker compose ps` |
| See logs | `docker compose logs postgres` |
| Stop (data is kept) | `docker compose down` |
| Stop **and delete all data** | `docker compose down -v` |

> **Volumes:** the database files live in a Docker volume (`pgdata`), not inside the container. That is why data survives `docker compose down`. Only `down -v` deletes it.

### How `.env` creates the database

`env_file: .env` in `docker-compose.yml` passes every variable in `.env` into the container. The official Postgres image then reads these exact names on **first start only** (when the volume is empty):

| Variable | Effect |
|---|---|
| `POSTGRES_USER` | Creates this user |
| `POSTGRES_PASSWORD` | Sets its password |
| `POSTGRES_DB` | Creates this database |

`POSTGRES_PORT` is only used by Compose for the `ports:` mapping.

- Names must be spelled exactly, or they are silently ignored.
- Write `KEY=value` with no spaces around `=`.
- Changing them later does nothing, because the volume already exists. To re-create: `docker compose down -v && docker compose up -d` (**deletes all data**).

Check what the container received:
```bash
docker compose exec postgres env | grep POSTGRES
```

---

## 3. Connect to the database

**From your terminal:**
```bash
psql -h localhost -p 5433 -U sourcing sourcing_pilot
#     host        port     user       database (last word, no flag)
```

**Or through the container (no password needed):**
```bash
docker compose exec postgres psql -U sourcing sourcing_pilot
```

> **Two Postgres servers on this Mac:** a plain `psql` or `psql -l` connects to the Homebrew Postgres 14 on port **5432**, not this project. Always pass `-h localhost -p 5433` for the project database.

**Useful psql commands:**

| Command | Shows / does |
|---|---|
| `\conninfo` | Which database, user and port you are connected to |
| `\l` | All databases |
| `\dn` | Schemas |
| `\du` | Users / roles |
| `\dt` | Tables in the `public` schema |
| `\dt+` | Tables with their sizes |
| `\dt raw.*` | Tables in the `raw` schema |
| `\d table_name` | Columns, types and indexes of a table (e.g. `\d raw.erp_pir`) |
| `\x` | Toggle expanded view (handy for wide rows) |
| `\?` | All psql commands |
| `\q` | Quit (`Ctrl+C` does **not** quit; it only clears the line) |

The prompt `sourcing_pilot=#` means you are inside the database and typing SQL. End SQL statements with `;`.

**Run a SQL file:**
```bash
psql -h localhost -p 5433 -U sourcing sourcing_pilot -f sql/my_file.sql
```

---

## 4. Visualise the database

Use a free GUI tool to browse schemas and tables by clicking:

- **TablePlus** – simple and fast (macOS)
- **DBeaver** – free, more features, also shows ER diagrams

Connection settings:

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5433` |
| User | `sourcing` |
| Password | see `.env` |
| Database | `sourcing_pilot` |

> **Tip:** In DBeaver, right-click a schema → **View Diagram** to see the tables and how they relate.

Docker Desktop shows the container and its logs, but **not** what is inside the database.

---

## 5. How data flows through the database

```
CSV files (data/synthetic/.../raw)
        │  load as-is
        ▼
raw.*        ← exact copy of the files, all columns TEXT
        │  clean with SQL
        ▼
staging.*    ← typed, trimmed, deduplicated
```

Raw data is never edited. All cleaning happens in SQL on top of it, so it can always be re-run.

### Load the files and check the result

```bash
uv pip install -r requirements.txt   # once; plain `pip` is NOT the venv's pip (uv venv has none)
python3 loader/load_raw.py           # loads raw/ and ground_truth/ into schemas raw.* and ground_truth.*
```

Check in psql:

```sql
\dt raw.*                                   -- 11 tables
\dt ground_truth.*                          -- 15 tables
SELECT snapshot_quarter, count(*) FROM raw.erp_pir GROUP BY 1;   -- rows per quarter
SELECT * FROM raw.component_master LIMIT 5;                     -- look at the data
```

---

## 6. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `password authentication failed for user "sourcing_pilot"` | `-U` is the **user** (`sourcing`), not the database. Use `-U sourcing sourcing_pilot`. |
| `psql -l` doesn't show `sourcing_pilot` | You're on the Homebrew server (5432). Add `-h localhost -p 5433 -U sourcing`. |
| `WARNING: psql major version 14, server major version 16` | Old client. Use the native Postgres 16 client (below), or connect through `docker compose exec`. |
| `brew install` compiles for ages | The Intel Homebrew in `/usr/local` is being used. Install with `/opt/homebrew/bin/brew install ...` instead. |
| Container not `healthy` | `docker compose logs postgres` |

**psql 16 client setup (one-time, Apple Silicon):**
```bash
/opt/homebrew/bin/brew install postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
psql --version   # should say 16.x
```
