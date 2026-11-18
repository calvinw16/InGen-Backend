"""Measure indexed query plans on an isolated, migrated SQLite database."""

import argparse
import base64
import itertools
import json
from datetime import datetime, timedelta
from statistics import median
from time import perf_counter

from app.services.telemetry_query import (
    DetectionQuery,
    detection_statement,
    timeline_statement,
)
from app.services.telemetry_store import engine


def explain(conn, stmt) -> list[str]:
    sql = str(stmt.compile(conn, compile_kwargs={"literal_binds": True}))
    return [row[-1] for row in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robot_id")
    parser.add_argument("anchor", type=datetime.fromisoformat)
    args = parser.parse_args()
    start = args.anchor - timedelta(days=2)
    end = args.anchor - timedelta(hours=1)
    options = {
        "robot_id": args.robot_id,
        "class_label": "person",
        "min_confidence": 0.7,
        "start": start,
        "end": end,
    }
    with engine().connect() as conn:
        if conn.dialect.name != "sqlite":
            parser.error("This report runner uses SQLite EXPLAIN QUERY PLAN.")
        conn.exec_driver_sql("ANALYZE")
        for sort in ("asc", "desc"):
            for mask in itertools.product((False, True), repeat=len(options)):
                filters = {
                    key: value
                    for (key, value), include in zip(options.items(), mask, strict=True)
                    if include
                }
                query = DetectionQuery(**filters, sort=sort)
                stmt = detection_statement(query)
                plan = explain(conn, stmt)
                started = perf_counter()
                rows = conn.execute(stmt).all()
                print(
                    json.dumps(
                        {
                            "filters": list(filters),
                            "sort": sort,
                            "plan": plan,
                            "rows": len(rows),
                            "elapsed_ms": (perf_counter() - started) * 1000,
                        }
                    )
                )
                if rows:
                    last = rows[min(len(rows), query.limit) - 1]
                    cursor = base64.urlsafe_b64encode(
                        json.dumps(
                            {
                                "at": last.captured_at.isoformat(),
                                "id": last.id,
                                "scope": query.scope(),
                            }
                        ).encode()
                    ).decode()
                    next_page = query.model_copy(update={"cursor": cursor})
                    print(
                        json.dumps(
                            {
                                "filters": list(filters),
                                "sort": sort,
                                "cursor": True,
                                "plan": explain(conn, detection_statement(next_page)),
                            }
                        )
                    )
        measured = detection_statement(DetectionQuery(**options))
        sql = str(measured.compile(conn, compile_kwargs={"literal_binds": True}))
        scan = sql.replace("FROM detections", "FROM detections NOT INDEXED")
        assert conn.exec_driver_sql(sql).all() == conn.exec_driver_sql(scan).all()

        def sample(statement):
            conn.exec_driver_sql(statement).all()
            values = []
            for _ in range(40):
                started = perf_counter()
                conn.exec_driver_sql(statement).all()
                values.append((perf_counter() - started) * 1000)
            return median(values)

        print(
            json.dumps(
                {
                    "comparison": "all filters descending, limit 20 plus lookahead",
                    "index_ms_median": sample(sql),
                    "forced_scan_ms_median": sample(scan),
                    "forced_scan_plan": [
                        r[-1]
                        for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + scan)
                    ],
                }
            )
        )
        stmt = timeline_statement(args.robot_id, start, end, 3600, "sqlite")
        plan = explain(conn, stmt)
        started = perf_counter()
        rows = conn.execute(stmt).all()
        print(
            json.dumps(
                {
                    "timeline": True,
                    "plan": plan,
                    "rows": len(rows),
                    "elapsed_ms": (perf_counter() - started) * 1000,
                }
            )
        )


if __name__ == "__main__":
    main()
