import os 
import re 
import pandas as pd
from pathlib import Path 
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# resolve gets the full path
#paernts[] makes the path start from the parent chosen. So for load_raw, the parent[0] is loader, and the parent[1] is Sourcing-Pilot-PPD
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic"

#standardisation of name of columns early
def quick_std_column(name:str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")

def read_file(path:Path) ->[dict[str, pd.DataFrame]]:
    if path.suffix == ".csv":
        return {path.stem: pd.read_csv(path, dtype=str, keep_default_na = False)}
    if path.suffix == ".xlsx":
        return {path.stem: pd.read_excel(path, dtype=str, keep_default_na = False).fillna("")}
    return {}

def main() -> None:
    load_dotenv()

    url = (f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
           f"@localhost:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}")
    engine = create_engine(url)


    for layer, schema in [("raw", "raw"),("ground_truth", "ground_truth")]:
        tables: dict[str, list[pd.DataFrame]] = {}

        # goes through all the folders in data/synthetic deu to path earlier. in this case it is the Q3 and Q4 2026
        for qdir in sorted(p for p in DATA_DIR.iterdir() if p.is_dir()): 

            # goes to the respectiv elayer , i.e. raw or ground_truth. .glob(*) takes ALL the files there is in it. 
            for f in sorted((qdir / layer).glob("*")):
                for name, df in read_file(f).items():
                    #quick smart standardisation
                    df.columns = [quick_std_column(c) for c in df.columns]
                    df.insert(0, "snapshot_quarter", qdir.name)
                    tables.setdefault(name, []).append(df)

        with engine.begin() as conn:
            conn.execute(text(f"create schema if not exists {schema}")) # schema is like a folder with multipe table sin it
        for name, dfs in tables.items():
            df = pd.concat(dfs, ignore_index=True)
            df.to_sql(name, engine, schema=schema, if_exists="replace", index=False)
            print(f"{schema}.{name}: {len(df)} rows")


if __name__ == "__main__":
    main()


# python3 "loader/load_raw.py"