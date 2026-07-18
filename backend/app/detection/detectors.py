"""Six config-driven category detectors. General patterns only — no dossier IDs."""

from __future__ import annotations

from typing import Any

import duckdb

from app.detection.types import (
    DetectorHit,
    cfg_tables,
    first_table,
    has_columns,
    qident,
)
from app.schemas import Citation


def run_all_detectors(conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> list[DetectorHit]:
    hits: list[DetectorHit] = []
    hits.extend(detect_segregation_of_duties(conn, cfg))
    hits.extend(detect_misclassification(conn, cfg))
    hits.extend(detect_cutoff_timing(conn, cfg))
    hits.extend(detect_threshold_structuring(conn, cfg))
    hits.extend(detect_near_duplicate_entities(conn, cfg))
    hits.extend(detect_unsupported_transaction(conn, cfg))
    return hits


def detect_segregation_of_duties(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    sod = cfg.get("segregation_of_duties") or {}
    base = float(sod.get("base", 55))
    sensitive = [str(x).lower() for x in (sod.get("sensitive_fields") or [])]
    sensitive_boost = float(sod.get("sensitive_field_boost", 15))
    hits: list[DetectorHit] = []

    for role, label in (
        ("freigabe", "journal approval"),
        ("stammdaten", "master-data change"),
    ):
        table = first_table(conn, cfg_tables(cfg, role))
        if not table or not has_columns(conn, table, {"creator", "approver"}):
            continue
        cols = {c.lower(): c for c in _cols(conn, table)}
        extra_select = ""
        if "feld" in cols:
            extra_select += f", {qident(cols['feld'])} AS feld"
        if "konto" in cols:
            extra_select += f", {qident(cols['konto'])} AS konto"
        if "name" in cols:
            extra_select += f", {qident(cols['name'])} AS name"
        if "erfassungsnummer" in cols:
            extra_select += f", {qident(cols['erfassungsnummer'])} AS ref"
        elif "journalname" in cols:
            extra_select += f", {qident(cols['journalname'])} AS ref"

        sql = f"""
            SELECT creator, approver {extra_select}
            FROM {qident(table)}
            WHERE creator IS NOT NULL AND approver IS NOT NULL
              AND CAST(creator AS VARCHAR) = CAST(approver AS VARCHAR)
        """
        rows = conn.execute(sql).fetchdf()
        for _, row in rows.iterrows():
            user = str(row["creator"])
            feld = str(row["feld"]) if "feld" in row.index and row["feld"] is not None else ""
            strength = 10.0
            if feld and any(s in feld.lower() for s in sensitive):
                strength += sensitive_boost
            konto = str(row["konto"]) if "konto" in row.index and row.get("konto") is not None else ""
            name = str(row["name"]) if "name" in row.index and row.get("name") is not None else ""
            ref = str(row["ref"]) if "ref" in row.index and row.get("ref") is not None else ""
            cite_bits = [f"creator={user}", f"approver={user}"]
            if feld:
                cite_bits.append(f"field={feld}")
            if konto:
                cite_bits.append(f"account={konto}")
            hits.append(
                DetectorHit(
                    category="segregation_of_duties",
                    title=f"Same user created and approved {label}",
                    summary=(
                        f"User '{user}' appears as both creator and approver on a {label}"
                        + (f" (field '{feld}')" if feld else "")
                        + (f" for account {konto}" if konto else "")
                        + ". Four-eyes segregation of duties may be breached."
                    ),
                    base=base,
                    statistical_strength=strength,
                    citations=[
                        Citation(
                            n=1,
                            file=f"duckdb:{table}",
                            locator=f"creator={user}" + (f";konto={konto}" if konto else ""),
                            quote="; ".join(cite_bits),
                        )
                    ],
                    search_tokens=[user, konto, name, ref, feld],
                    entity_keys=[f"user:{user}"] + ([f"account:{konto}"] if konto else []),
                    expects_document=False,
                )
            )
    return hits


def detect_misclassification(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    mc = cfg.get("misclassification") or {}
    base = float(mc.get("base", 50))
    repair_kw = [str(x).lower() for x in (mc.get("repair_keywords") or [])]
    asset_types = [str(x).lower() for x in (mc.get("asset_booking_types") or ["acquisition"])]
    hits: list[DetectorHit] = []

    assets = first_table(conn, cfg_tables(cfg, "asset_postings"))
    vendors = first_table(conn, cfg_tables(cfg, "vendor_postings"))
    if assets and vendors and has_columns(conn, assets, {"document_number", "amount"}):
        a_cols = {c.lower(): c for c in _cols(conn, assets)}
        v_cols = {c.lower(): c for c in _cols(conn, vendors)}
        if "buchungsart" in a_cols and "booking_text" in v_cols and "buchungsnummer" in v_cols:
            type_list = ", ".join(f"'{t}'" for t in asset_types)
            # Match acquisition docs whose vendor booking text looks like repair/maintenance
            kw_clause = " OR ".join(
                f"lower(CAST(k.{qident(v_cols['booking_text'])} AS VARCHAR)) LIKE '%{kw}%'"
                for kw in repair_kw
            )
            if kw_clause:
                sql = f"""
                    SELECT
                      a.{qident(a_cols['anlagennummer']) if 'anlagennummer' in a_cols else a_cols['document_number']} AS asset_ref,
                      CAST(a.{qident(a_cols['document_number'])} AS VARCHAR) AS doc,
                      a.{qident(a_cols['amount'])} AS asset_amount,
                      CAST(a.{qident(a_cols['buchungsart'])} AS VARCHAR) AS booking_type,
                      k.{qident(v_cols['booking_text'])} AS booking_text,
                      k.{qident(v_cols['vendor_id'])} AS vendor_id,
                      abs(k.{qident(v_cols['amount'])}) AS vendor_amount
                    FROM {qident(assets)} a
                    JOIN {qident(vendors)} k
                      ON CAST(a.{qident(a_cols['document_number'])} AS VARCHAR)
                       = CAST(k.{qident(v_cols['buchungsnummer'])} AS VARCHAR)
                    WHERE lower(CAST(a.{qident(a_cols['buchungsart'])} AS VARCHAR)) IN ({type_list})
                      AND ({kw_clause})
                """
                try:
                    rows = conn.execute(sql).fetchdf()
                except duckdb.Error:
                    rows = None
                if rows is not None:
                    for _, row in rows.iterrows():
                        text = str(row["booking_text"] or "")
                        doc = str(row["doc"] or "")
                        vendor = str(row["vendor_id"] or "")
                        hits.append(
                            DetectorHit(
                                category="misclassification",
                                title="Repair-like cost capitalized as asset acquisition",
                                summary=(
                                    f"Document {doc} is booked as asset {row['booking_type']} "
                                    f"({row['asset_ref']}, amount {row['asset_amount']}), "
                                    f"but the vendor posting text reads as maintenance/repair: "
                                    f"'{text}'. Expense may be misclassified as CapEx."
                                ),
                                base=base,
                                statistical_strength=18.0,
                                citations=[
                                    Citation(
                                        n=1,
                                        file=f"duckdb:{assets}",
                                        locator=f"document_number={doc}",
                                        quote=(
                                            f"type={row['booking_type']}; "
                                            f"asset={row['asset_ref']}; amount={row['asset_amount']}"
                                        ),
                                    ),
                                    Citation(
                                        n=2,
                                        file=f"duckdb:{vendors}",
                                        locator=f"BUCHUNGSNUMMER={doc};vendor={vendor}",
                                        quote=text[:160],
                                    ),
                                ],
                                search_tokens=[doc, vendor, text],
                                entity_keys=[f"doc:{doc}", f"vendor:{vendor}"],
                            )
                        )

    # Optional: GL text vs account-name mismatch (generic keyword rules)
    gl = first_table(conn, cfg_tables(cfg, "gl_postings"))
    coa = first_table(conn, cfg_tables(cfg, "chart_of_accounts"))
    rules = mc.get("text_account_rules") or []
    if gl and coa and rules and has_columns(conn, gl, {"gl_account", "booking_text"}):
        coa_cols = {c.lower(): c for c in _cols(conn, coa)}
        name_col = coa_cols.get("sachkontoname")
        if name_col and has_columns(conn, coa, {"gl_account"}):
            for rule in rules:
                keywords = [str(k).lower() for k in (rule.get("keywords") or [])]
                expect = [str(e).lower() for e in (rule.get("expect_account_name") or [])]
                if not keywords or not expect:
                    continue
                kw_sql = " OR ".join(
                    f"lower(CAST(g.booking_text AS VARCHAR)) LIKE '%{k}%'" for k in keywords
                )
                expect_sql = " OR ".join(
                    f"lower(CAST(c.{qident(name_col)} AS VARCHAR)) LIKE '%{e}%'" for e in expect
                )
                # Skip balance-sheet clearing / VAT / payable noise accounts
                skip_name = (
                    "lower(CAST(c."
                    + qident(name_col)
                    + " AS VARCHAR)) LIKE '%vorsteuer%' OR "
                    "lower(CAST(c."
                    + qident(name_col)
                    + " AS VARCHAR)) LIKE '%verbindlich%' OR "
                    "lower(CAST(c."
                    + qident(name_col)
                    + " AS VARCHAR)) LIKE '%forderung%'"
                )
                sql = f"""
                    SELECT g.gl_account, g.booking_text, c.{qident(name_col)} AS account_name,
                           COUNT(*) AS n, SUM(g.amount) AS total
                    FROM {qident(gl)} g
                    JOIN {qident(coa)} c ON CAST(g.gl_account AS VARCHAR)=CAST(c.gl_account AS VARCHAR)
                    WHERE ({kw_sql})
                      AND NOT ({expect_sql})
                      AND NOT ({skip_name})
                      AND CAST(g.gl_account AS VARCHAR) NOT LIKE '330%%'
                    GROUP BY 1,2,3
                    HAVING COUNT(*) >= 1 AND abs(SUM(g.amount)) >= 1000
                    ORDER BY abs(SUM(g.amount)) DESC
                    LIMIT 5
                """
                try:
                    rows = conn.execute(sql).fetchdf()
                except duckdb.Error:
                    continue
                for _, row in rows.iterrows():
                    # Avoid flooding: only emit when account looks like inventory/asset vs expense keyword
                    acct = str(row["account_name"] or "").lower()
                    if not any(
                        frag in acct
                        for frag in ("anlage", "roh", "ware", "maschine", "Gebäude", "gebäude", "grund")
                    ):
                        continue
                    hits.append(
                        DetectorHit(
                            category="misclassification",
                            title="Booking text does not match GL account class",
                            summary=(
                                f"Postings with text '{row['booking_text']}' land on account "
                                f"{row['gl_account']} ({row['account_name']}), which does not match "
                                f"the expected account-name keywords {expect}."
                            ),
                            base=base - 5,
                            statistical_strength=min(20.0, 5.0 + float(row["n"])),
                            citations=[
                                Citation(
                                    n=1,
                                    file=f"duckdb:{gl}",
                                    locator=f"gl_account={row['gl_account']}",
                                    quote=(
                                        f"text={row['booking_text']}; "
                                        f"account={row['account_name']}; n={row['n']}"
                                    ),
                                )
                            ],
                            search_tokens=[str(row["gl_account"]), str(row["booking_text"])],
                            entity_keys=[f"gl:{row['gl_account']}"],
                        )
                    )
    return hits


def detect_cutoff_timing(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    from app.detection.types import tables_matching

    ct = cfg.get("cutoff_timing") or {}
    base = float(ct.get("base", 48))
    end_month = int(ct.get("fiscal_year_end_month", 12))
    end_day = int(ct.get("fiscal_year_end_day", 31))
    window = int(ct.get("post_period_window_days", 45))
    hits: list[DetectorHit] = []

    tables = tables_matching(conn, cfg_tables(cfg, "invoice_journal"))
    seen_docs: set[str] = set()
    for table in tables:
        cols = {c.lower(): c for c in _cols(conn, table)}
        if "invoice_date" not in cols or "service_date" not in cols:
            continue
        inv = qident(cols["invoice_date"])
        svc = qident(cols["service_date"])
        amt = qident(cols["amount"]) if "amount" in cols else "NULL"
        inv_no = qident(cols["invoice_number"]) if "invoice_number" in cols else "NULL"
        vendor = qident(cols["vendor_id"]) if "vendor_id" in cols else (
            qident(cols["customer_id"]) if "customer_id" in cols else "NULL"
        )
        name_col = None
        for cand in ("kreditorname", "debitorname", "remark"):
            if cand in cols:
                name_col = qident(cols[cand])
                break
        name_sel = f", {name_col} AS party_name" if name_col else ", NULL AS party_name"
        remark_sel = (
            f", {qident(cols['remark'])} AS remark" if "remark" in cols else ", NULL AS remark"
        )
        sql = f"""
            SELECT
              CAST({inv_no} AS VARCHAR) AS invoice_number,
              CAST({vendor} AS VARCHAR) AS party_id,
              CAST({inv} AS DATE) AS invoice_date,
              CAST({svc} AS DATE) AS service_date,
              {amt} AS amount
              {name_sel}
              {remark_sel}
            FROM {qident(table)}
            WHERE {inv} IS NOT NULL AND {svc} IS NOT NULL
              AND year(CAST({svc} AS DATE)) < year(CAST({inv} AS DATE))
              AND CAST({inv} AS DATE) <= CAST(
                    make_date(year(CAST({inv} AS DATE)), {end_month}, {end_day})
                    + INTERVAL {window} DAY AS DATE
                  )
              AND CAST({svc} AS DATE) >= CAST(
                    make_date(year(CAST({svc} AS DATE)), {end_month}, {end_day})
                    - INTERVAL {window} DAY AS DATE
                  )
        """
        try:
            rows = conn.execute(sql).fetchdf()
        except duckdb.Error:
            continue
        for _, row in rows.iterrows():
            doc = str(row["invoice_number"] or "")
            if doc and doc in seen_docs:
                continue
            if doc:
                seen_docs.add(doc)
            gap = (row["invoice_date"] - row["service_date"]).days
            strength = min(25.0, 8.0 + gap / 5.0)
            party = str(row["party_id"] or "")
            hits.append(
                DetectorHit(
                    category="cutoff_timing",
                    title="Post-period invoice for prior-period service",
                    summary=(
                        f"Invoice {doc or '(no number)'} dated {row['invoice_date'].date()} "
                        f"relates to service date {row['service_date'].date()} "
                        f"(prior fiscal period). Amount={row['amount']}. "
                        "Classic cutoff / period-end shifting risk."
                    ),
                    base=base,
                    statistical_strength=strength,
                    citations=[
                        Citation(
                            n=1,
                            file=f"duckdb:{table}",
                            locator=f"invoice_number={doc}",
                            quote=(
                                f"invoice_date={row['invoice_date'].date()}; "
                                f"service_date={row['service_date'].date()}; "
                                f"amount={row['amount']}"
                                + (f"; remark={row['remark']}" if row.get("remark") else "")
                            ),
                        )
                    ],
                    search_tokens=[doc, party, str(row.get("party_name") or ""), str(row.get("remark") or "")],
                    entity_keys=[f"doc:{doc}"] if doc else [],
                )
            )
    return hits


def detect_threshold_structuring(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    th = cfg.get("threshold_structuring") or {}
    base = float(th.get("base", 40))
    thresholds = [float(x) for x in (th.get("thresholds_eur") or [])]
    proximity = float(th.get("proximity_pct", 0.05))
    min_amt = float(th.get("min_amount_eur", 1000))
    max_hits = int(th.get("max_hits", 15))
    min_cluster = int(th.get("min_cluster_size", 3))
    cluster_boost = float(th.get("cluster_base_boost", 18))
    hits: list[DetectorHit] = []

    table = first_table(conn, cfg_tables(cfg, "vendor_postings"))
    if not table or not thresholds or not has_columns(conn, table, {"amount", "vendor_id"}):
        return hits
    cols = {c.lower(): c for c in _cols(conn, table)}
    text_col = cols.get("booking_text")
    doc_col = cols.get("buchungsnummer")
    date_col = cols.get("booking_date")

    text_filter = ""
    if text_col:
        text_filter = (
            "AND ("
            + " OR ".join(
                [
                    f"lower(CAST({qident(text_col)} AS VARCHAR)) LIKE '%eingangsrechnung%'",
                    f"lower(CAST({qident(text_col)} AS VARCHAR)) LIKE '%beratung%'",
                    f"lower(CAST({qident(text_col)} AS VARCHAR)) LIKE '%zahlung%'",
                ]
            )
            + ")"
        )

    # Prefer split-payment clusters: same vendor + same day, N amounts just under a threshold
    if date_col and min_cluster >= 2:
        for thr in thresholds:
            lo = thr * (1.0 - proximity)
            sql = f"""
                WITH near AS (
                  SELECT
                    CAST(vendor_id AS VARCHAR) AS vendor_id,
                    CAST({qident(date_col)} AS DATE) AS d,
                    abs(amount) AS amt,
                    CAST({qident(doc_col) if doc_col else 'NULL'} AS VARCHAR) AS doc,
                    {qident(text_col) if text_col else 'NULL'} AS booking_text
                  FROM {qident(table)}
                  WHERE amount IS NOT NULL
                    AND abs(amount) >= {min_amt}
                    AND abs(amount) >= {lo} AND abs(amount) < {thr}
                    {text_filter}
                ),
                clusters AS (
                  SELECT vendor_id, d, count(*) AS n, sum(amt) AS total,
                         list(amt ORDER BY amt DESC) AS amts,
                         any_value(doc) AS doc
                  FROM near
                  GROUP BY vendor_id, d
                  HAVING count(*) >= {min_cluster}
                )
                SELECT * FROM clusters
                ORDER BY n DESC, total DESC
                LIMIT 10
            """
            try:
                for _, row in conn.execute(sql).fetchdf().iterrows():
                    vendor = str(row["vendor_id"])
                    n = int(row["n"])
                    total = float(row["total"])
                    amts = row["amts"]
                    amt_list = (
                        ", ".join(f"{float(a):,.2f}" for a in list(amts)[:8])
                        if amts is not None
                        else ""
                    )
                    hits.append(
                        DetectorHit(
                            category="threshold_structuring",
                            title=(
                                f"{n} near-threshold payments same day "
                                f"(under {thr:,.0f} EUR)"
                            ),
                            summary=(
                                f"Vendor {vendor} has {n} postings on {row['d']} "
                                f"each just below {thr:,.0f} EUR "
                                f"(amounts {amt_list}; total {total:,.2f} EUR). "
                                "Possible split to avoid approval threshold."
                            ),
                            base=base + cluster_boost,
                            statistical_strength=min(25.0, 8.0 + n * 4.0),
                            citations=[
                                Citation(
                                    n=1,
                                    file=f"duckdb:{table}",
                                    locator=f"vendor_id={vendor};date={row['d']}",
                                    quote=(
                                        f"n={n}; threshold={thr}; total={total}; "
                                        f"amounts=[{amt_list}]"
                                        + (f"; doc={row['doc']}" if row.get("doc") else "")
                                    ),
                                )
                            ],
                            search_tokens=[vendor, str(row["doc"] or ""), f"{thr:.0f}"],
                            entity_keys=[f"vendor:{vendor}"],
                        )
                    )
            except duckdb.Error:
                pass

    # Build UNION of near-threshold windows (single-amount proximity)
    parts: list[str] = []
    for thr in thresholds:
        lo = thr * (1.0 - proximity)
        parts.append(
            f"""
            SELECT vendor_id, abs(amount) AS amt, {thr} AS threshold,
                   ( {thr} - abs(amount) ) / {thr} AS gap_pct
                   {', ' + qident(text_col) + ' AS booking_text' if text_col else ', NULL AS booking_text'}
                   {', CAST(' + qident(doc_col) + ' AS VARCHAR) AS doc' if doc_col else ', NULL AS doc'}
                   {', ' + qident(date_col) + ' AS booking_date' if date_col else ', NULL AS booking_date'}
            FROM {qident(table)}
            WHERE amount IS NOT NULL
              AND abs(amount) >= {min_amt}
              AND abs(amount) >= {lo} AND abs(amount) < {thr}
              {text_filter}
            """
        )
    sql = " UNION ALL ".join(parts) + " ORDER BY gap_pct ASC LIMIT 200"
    try:
        rows = conn.execute(sql).fetchdf()
    except duckdb.Error:
        return hits[:max_hits]

    # Prefer tighter gaps; collapse invoice+payment duplicates by vendor+amount+threshold
    seen: set[tuple[str, float, float]] = set()
    ranked: list[tuple[float, DetectorHit]] = []
    clustered_vendors = {k.removeprefix("vendor:") for h in hits for k in h.entity_keys}
    for _, row in rows.iterrows():
        vendor = str(row["vendor_id"])
        if vendor in clustered_vendors:
            continue  # cluster finding already covers this vendor
        amt = float(row["amt"])
        thr_v = float(row["threshold"])
        key = (vendor, round(amt, 2), thr_v)
        if key in seen:
            continue
        seen.add(key)
        gap_pct = float(row["gap_pct"])
        strength = max(0.0, 20.0 * (1.0 - gap_pct / proximity))
        doc = str(row["doc"] or "")
        text = str(row["booking_text"] or "")
        ranked.append(
            (
                gap_pct,
                DetectorHit(
                    category="threshold_structuring",
                    title=f"Amount just below {thr_v:,.0f} EUR threshold",
                    summary=(
                        f"Vendor {vendor} posting of {amt:,.2f} EUR sits "
                        f"{gap_pct * 100:.1f}% below configured threshold {thr_v:,.0f} EUR"
                        + (f" ({text})" if text else "")
                        + ". Possible threshold avoidance / structuring."
                    ),
                    base=base,
                    statistical_strength=strength,
                    citations=[
                        Citation(
                            n=1,
                            file=f"duckdb:{table}",
                            locator=f"vendor_id={vendor};amount={amt}",
                            quote=(
                                f"amount={amt}; threshold={thr_v}; gap_pct={gap_pct:.4f}"
                                + (f"; doc={doc}" if doc else "")
                                + (f"; text={text}" if text else "")
                            ),
                        )
                    ],
                    search_tokens=[vendor, doc, f"{amt:.2f}", f"{thr_v:.0f}"],
                    entity_keys=[f"vendor:{vendor}"],
                ),
            )
        )
    ranked.sort(key=lambda x: x[0])
    remaining = max(0, max_hits - len(hits))
    hits.extend(h for _, h in ranked[:remaining])
    return hits


def detect_near_duplicate_entities(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    from app.detection.types import tables_matching

    nd = cfg.get("near_duplicate_entities") or {}
    base = float(nd.get("base", 45))
    sim_min = float(nd.get("name_similarity_min", 0.94))
    legal_re = str(
        nd.get(
            "legal_form_regex",
            r"\s*(gmbh\s*&\s*co\.\s*kg|gmbh|ag|se|e\.k\.|kg|ohg|ug)\s*$",
        )
    )
    max_hits = int(nd.get("max_hits", 20))
    hits: list[DetectorHit] = []

    # Prefer master table (has name), not postings
    masters = [
        t
        for t in tables_matching(conn, cfg_tables(cfg, "vendor_master"))
        if "buchung" not in t.lower()
    ]
    table = masters[0] if masters else first_table(conn, cfg_tables(cfg, "vendor_master"))
    if not table or not has_columns(conn, table, {"vendor_id"}):
        return hits
    cols = {c.lower(): c for c in _cols(conn, table)}
    name_col = cols.get("lieferantenname")
    if not name_col:
        return hits
    street = cols.get("lieferantenstrasse")
    plz = cols.get("lieferantenplz")
    ort = cols.get("lieferantenort")

    # 1) Exact same street + PLZ, different vendor_id
    if street and plz:
        sql = f"""
            SELECT
              a.vendor_id AS id1, b.vendor_id AS id2,
              a.{qident(name_col)} AS n1, b.{qident(name_col)} AS n2,
              a.{qident(street)} AS street, a.{qident(plz)} AS plz
              {', a.' + qident(ort) + ' AS city' if ort else ', NULL AS city'}
            FROM {qident(table)} a
            JOIN {qident(table)} b
              ON a.vendor_id < b.vendor_id
             AND a.{qident(street)} IS NOT NULL
             AND a.{qident(plz)} IS NOT NULL
             AND CAST(a.{qident(street)} AS VARCHAR) = CAST(b.{qident(street)} AS VARCHAR)
             AND CAST(a.{qident(plz)} AS VARCHAR) = CAST(b.{qident(plz)} AS VARCHAR)
        """
        try:
            for _, row in conn.execute(sql).fetchdf().iterrows():
                hits.append(
                    DetectorHit(
                        category="near_duplicate_entities",
                        title="Vendors share the same street address",
                        summary=(
                            f"Vendors {row['id1']} ({row['n1']}) and {row['id2']} ({row['n2']}) "
                            f"share address {row['street']}, {row['plz']}"
                            + (f" {row['city']}" if row.get("city") else "")
                            + ". Possible duplicate / related-party entity."
                        ),
                        base=base,
                        statistical_strength=22.0,
                        citations=[
                            Citation(
                                n=1,
                                file=f"duckdb:{table}",
                                locator=f"vendor_id={row['id1']},{row['id2']}",
                                quote=(
                                    f"{row['n1']} / {row['n2']}; "
                                    f"{row['street']}, {row['plz']}"
                                ),
                            )
                        ],
                        search_tokens=[
                            str(row["id1"]),
                            str(row["id2"]),
                            str(row["n1"]),
                            str(row["n2"]),
                            str(row["street"]),
                        ],
                        entity_keys=[f"vendor:{row['id1']}", f"vendor:{row['id2']}"],
                    )
                )
        except duckdb.Error:
            pass

    # 2) Same normalized base name (legal form stripped), or high Jaro with shared first token
    sql = f"""
        WITH base AS (
          SELECT
            vendor_id,
            {qident(name_col)} AS name,
            trim(regexp_replace(lower(CAST({qident(name_col)} AS VARCHAR)), '{legal_re}', '')) AS base_name
            {', ' + qident(ort) + ' AS city' if ort else ', NULL AS city'}
          FROM {qident(table)}
          WHERE {qident(name_col)} IS NOT NULL
        )
        SELECT
          a.vendor_id AS id1, b.vendor_id AS id2, a.name AS n1, b.name AS n2,
          a.base_name,
          jaro_winkler_similarity(lower(a.name), lower(b.name)) AS sim,
          CASE WHEN a.base_name = b.base_name AND length(a.base_name) > 5 THEN true ELSE false END AS same_base
        FROM base a
        JOIN base b ON a.vendor_id < b.vendor_id
        WHERE (a.base_name = b.base_name AND length(a.base_name) > 5)
           OR (
                jaro_winkler_similarity(lower(a.name), lower(b.name)) >= {sim_min}
                AND split_part(a.base_name, ' ', 1) = split_part(b.base_name, ' ', 1)
                AND length(split_part(a.base_name, ' ', 1)) >= 3
              )
        ORDER BY same_base DESC, sim DESC
        LIMIT {max_hits * 2}
    """
    try:
        rows = conn.execute(sql).fetchdf()
    except duckdb.Error:
        return hits[:max_hits]

    seen_pairs = {(h.entity_keys[0], h.entity_keys[1]) for h in hits if len(h.entity_keys) >= 2}
    for _, row in rows.iterrows():
        pair = (f"vendor:{row['id1']}", f"vendor:{row['id2']}")
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        same_base = bool(row["same_base"])
        sim = float(row["sim"])
        strength = 20.0 if same_base else 10.0 + 10.0 * sim
        hits.append(
            DetectorHit(
                category="near_duplicate_entities",
                title="Near-duplicate vendor names",
                summary=(
                    f"Vendors {row['id1']} ({row['n1']}) and {row['id2']} ({row['n2']}) "
                    + (
                        f"share normalized name '{row['base_name']}'"
                        if same_base
                        else f"have name similarity {sim:.3f}"
                    )
                    + ". Review for duplicate master data."
                ),
                base=base,
                statistical_strength=strength,
                citations=[
                    Citation(
                        n=1,
                        file=f"duckdb:{table}",
                        locator=f"vendor_id={row['id1']},{row['id2']}",
                        quote=f"{row['n1']} ≈ {row['n2']} (sim={sim:.3f})",
                    )
                ],
                search_tokens=[str(row["id1"]), str(row["id2"]), str(row["n1"]), str(row["n2"])],
                entity_keys=[f"vendor:{row['id1']}", f"vendor:{row['id2']}"],
            )
        )
        if len(hits) >= max_hits:
            break
    return hits[:max_hits]


def detect_unsupported_transaction(
    conn: duckdb.DuckDBPyConnection, cfg: dict[str, Any]
) -> list[DetectorHit]:
    un = cfg.get("unsupported_transaction") or {}
    base = float(un.get("base", 42))
    vat = float(un.get("vat_rate", 1.19))
    material_kw = [str(x).lower() for x in (un.get("material_keywords") or ["material"])]
    service_kw = [str(x).lower() for x in (un.get("service_keywords") or [])]
    min_service = float(un.get("min_service_amount_eur", 10000))
    new_fields = [str(x).lower() for x in (un.get("new_vendor_field_keywords") or ["neuanlage"])]
    new_days = int(un.get("new_vendor_payment_days", 60))
    new_min = float(un.get("new_vendor_min_amount_eur", 5000))
    require_risk = bool(un.get("new_vendor_require_risk_signal", True))
    hits: list[DetectorHit] = []

    vendors = first_table(conn, cfg_tables(cfg, "vendor_postings"))
    we = first_table(conn, cfg_tables(cfg, "goods_receipt"))
    if (
        vendors
        and we
        and has_columns(conn, vendors, {"vendor_id", "amount"})
        and has_columns(conn, we, {"vendor_id", "amount"})
    ):
        v_cols = {c.lower(): c for c in _cols(conn, vendors)}
        w_cols = {c.lower(): c for c in _cols(conn, we)}
        text_col = v_cols.get("booking_text")
        doc_col = v_cols.get("buchungsnummer")
        inv_col = w_cols.get("invoice_number")
        if text_col:
            mat_clause = " OR ".join(
                f"lower(CAST(k.{qident(text_col)} AS VARCHAR)) LIKE '%{kw}%'" for kw in material_kw
            )
            sql = f"""
                WITH we AS (
                  SELECT
                    CAST(vendor_id AS VARCHAR) AS v,
                    round(amount * {vat}, 2) AS gross,
                    CAST({qident(inv_col) if inv_col else 'NULL'} AS VARCHAR) AS inv
                  FROM {qident(we)}
                ),
                kb AS (
                  SELECT
                    CAST(vendor_id AS VARCHAR) AS v,
                    round(abs(amount), 2) AS amt,
                    CAST({qident(doc_col) if doc_col else 'NULL'} AS VARCHAR) AS doc,
                    {qident(text_col)} AS booking_text,
                    {qident(v_cols['booking_date']) if 'booking_date' in v_cols else 'NULL'} AS booking_date
                  FROM {qident(vendors)}
                  WHERE amount IS NOT NULL AND ({mat_clause})
                )
                SELECT k.v AS vendor_id, k.amt, k.doc, k.booking_text, k.booking_date
                FROM kb k
                LEFT JOIN we w
                  ON (w.v = k.v AND w.gross = k.amt)
                  OR (k.doc IS NOT NULL AND w.inv IS NOT NULL AND k.doc = w.inv)
                WHERE w.v IS NULL
                LIMIT 25
            """
            try:
                rows = conn.execute(sql).fetchdf()
                for _, row in rows.iterrows():
                    doc = str(row["doc"] or "")
                    vendor = str(row["vendor_id"])
                    hits.append(
                        DetectorHit(
                            category="unsupported_transaction",
                            title="Material purchase without matching goods receipt",
                            summary=(
                                f"Vendor {vendor} material posting {doc or ''} "
                                f"amount {row['amt']} has no matching goods-receipt line "
                                f"(matched on invoice number or vendor+gross@{vat})."
                            ),
                            base=base,
                            statistical_strength=16.0,
                            citations=[
                                Citation(
                                    n=1,
                                    file=f"duckdb:{vendors}",
                                    locator=f"vendor_id={vendor};doc={doc}",
                                    quote=str(row["booking_text"] or "")[:160],
                                )
                            ],
                            search_tokens=[vendor, doc, str(row["amt"])],
                            entity_keys=[f"vendor:{vendor}", f"doc:{doc}"] if doc else [f"vendor:{vendor}"],
                            expects_document=True,
                        )
                    )
            except duckdb.Error:
                pass

    # High-value service postings → expect Stage 2 document corroboration
    if vendors and service_kw and has_columns(conn, vendors, {"vendor_id", "amount"}):
        v_cols = {c.lower(): c for c in _cols(conn, vendors)}
        text_col = v_cols.get("booking_text")
        doc_col = v_cols.get("buchungsnummer")
        if text_col:
            svc = " OR ".join(
                f"lower(CAST({qident(text_col)} AS VARCHAR)) LIKE '%{kw}%'" for kw in service_kw
            )
            sql = f"""
                SELECT
                  vendor_id,
                  abs(amount) AS amt,
                  CAST({qident(doc_col) if doc_col else 'NULL'} AS VARCHAR) AS doc,
                  {qident(text_col)} AS booking_text,
                  {qident(v_cols['booking_date']) if 'booking_date' in v_cols else 'NULL'} AS booking_date
                FROM {qident(vendors)}
                WHERE amount IS NOT NULL AND abs(amount) >= {min_service}
                  AND ({svc})
                  AND lower(CAST({qident(text_col)} AS VARCHAR)) NOT LIKE '%eingangsrechnung rechts%'
                ORDER BY abs(amount) DESC
                LIMIT 20
            """
            try:
                # One finding per vendor (highest amount); Stage 2 handles doc support
                seen: set[str] = set()
                for _, row in conn.execute(sql).fetchdf().iterrows():
                    vendor = str(row["vendor_id"])
                    if vendor in seen:
                        continue
                    seen.add(vendor)
                    doc = str(row["doc"] or "")
                    hits.append(
                        DetectorHit(
                            category="unsupported_transaction",
                            title="High-value service posting needs supporting evidence",
                            summary=(
                                f"Vendor {vendor} service-related posting "
                                f"{doc or ''} for {row['amt']:,.2f} EUR "
                                f"('{row['booking_text']}'). "
                                "Stage 2 will check PDF/DOCX for contract/support references."
                            ),
                            base=base,
                            statistical_strength=min(20.0, 8.0 + float(row["amt"]) / 20000.0),
                            citations=[
                                Citation(
                                    n=1,
                                    file=f"duckdb:{vendors}",
                                    locator=f"vendor_id={vendor};doc={doc}",
                                    quote=str(row["booking_text"] or "")[:160],
                                )
                            ],
                            search_tokens=[vendor, doc, str(row["booking_text"] or "")],
                            entity_keys=[f"vendor:{vendor}"] + ([f"doc:{doc}"] if doc else []),
                            expects_document=True,
                        )
                    )
            except duckdb.Error:
                pass

    # New vendor + timely payment (optionally gated by SoD breach and/or missing GR)
    stam = first_table(conn, cfg_tables(cfg, "stammdaten"))
    if stam and vendors and has_columns(conn, stam, {"creator"}):
        s_cols = {c.lower(): c for c in _cols(conn, stam)}
        if "konto" in s_cols and "datum" in s_cols and "feld" in s_cols:
            field_clause = " OR ".join(
                f"lower(CAST({qident(s_cols['feld'])} AS VARCHAR)) LIKE '%{kw}%'" for kw in new_fields
            )
            art_filter = ""
            if "art" in s_cols:
                art_filter = f"AND lower(CAST({qident(s_cols['art'])} AS VARCHAR)) LIKE '%kredit%'"
            sod_select = "NULL AS creator, NULL AS approver"
            if "approver" in s_cols:
                sod_select = (
                    f"CAST({qident(s_cols['creator'])} AS VARCHAR) AS creator, "
                    f"CAST({qident(s_cols['approver'])} AS VARCHAR) AS approver"
                )
            v_cols = {c.lower(): c for c in _cols(conn, vendors)}
            we = first_table(conn, cfg_tables(cfg, "goods_receipt"))
            gr_join = ""
            gr_select = "0 AS gr_count"
            if we and has_columns(conn, we, {"vendor_id"}):
                gr_select = "coalesce(g.gr_count, 0) AS gr_count"
                gr_join = f"""
                LEFT JOIN (
                  SELECT CAST(vendor_id AS VARCHAR) AS vendor_id, count(*) AS gr_count
                  FROM {qident(we)}
                  GROUP BY 1
                ) g ON g.vendor_id = n.vendor_id
                """
            sql = f"""
                WITH new_vendors AS (
                  SELECT
                    CAST({qident(s_cols['konto'])} AS VARCHAR) AS vendor_id,
                    CAST({qident(s_cols['datum'])} AS DATE) AS created,
                    {qident(s_cols['name']) if 'name' in s_cols else 'NULL'} AS name,
                    {sod_select}
                  FROM {qident(stam)}
                  WHERE ({field_clause}) {art_filter}
                ),
                pay AS (
                  SELECT
                    CAST(vendor_id AS VARCHAR) AS vendor_id,
                    CAST({qident(v_cols['booking_date'])} AS DATE) AS d,
                    abs(amount) AS amt,
                    {qident(v_cols['booking_text']) if 'booking_text' in v_cols else 'NULL'} AS booking_text,
                    CAST({qident(v_cols['buchungsnummer']) if 'buchungsnummer' in v_cols else 'NULL'} AS VARCHAR) AS doc
                  FROM {qident(vendors)}
                  WHERE amount IS NOT NULL AND abs(amount) >= {new_min}
                )
                SELECT n.vendor_id, n.name, n.created, n.creator, n.approver,
                       p.d, p.amt, p.booking_text, p.doc,
                       date_diff('day', n.created, p.d) AS days_after,
                       {gr_select}
                FROM new_vendors n
                JOIN pay p ON n.vendor_id = p.vendor_id
                {gr_join}
                WHERE p.d >= n.created
                  AND date_diff('day', n.created, p.d) <= {new_days}
                ORDER BY days_after ASC, p.amt DESC
                LIMIT 30
            """
            try:
                seen_v: set[str] = set()
                for _, row in conn.execute(sql).fetchdf().iterrows():
                    vendor = str(row["vendor_id"])
                    if vendor in seen_v:
                        continue
                    creator = str(row["creator"] or "")
                    approver = str(row["approver"] or "")
                    sod_breach = bool(creator and approver and creator == approver)
                    gr_count = int(row["gr_count"] or 0)
                    if require_risk and not sod_breach and gr_count > 0:
                        # New vendor with four-eyes and goods receipts looks legitimate
                        continue
                    seen_v.add(vendor)
                    days = int(row["days_after"])
                    strength = max(5.0, 22.0 - days / 3.0)
                    if sod_breach:
                        strength += 8.0
                    if gr_count == 0:
                        strength += 6.0
                    risk_bits = []
                    if sod_breach:
                        risk_bits.append(f"creator=approver ({creator})")
                    if gr_count == 0:
                        risk_bits.append("no goods receipt")
                    hits.append(
                        DetectorHit(
                            category="unsupported_transaction",
                            title="New vendor paid shortly after master-data creation",
                            summary=(
                                f"Vendor {vendor} ({row['name']}) was created on {row['created'].date()} "
                                f"and paid {row['amt']:,.2f} EUR only {days} days later "
                                f"({row['booking_text']})"
                                + (f"; risk: {'; '.join(risk_bits)}" if risk_bits else "")
                                + ". Review supporting onboarding/contracts."
                            ),
                            base=base + 5,
                            statistical_strength=strength,
                            citations=[
                                Citation(
                                    n=1,
                                    file=f"duckdb:{stam}",
                                    locator=f"konto={vendor}",
                                    quote=(
                                        f"Neuanlage vendor={vendor}; created={row['created'].date()}"
                                        + (f"; creator={creator}; approver={approver}" if creator else "")
                                    ),
                                ),
                                Citation(
                                    n=2,
                                    file=f"duckdb:{vendors}",
                                    locator=f"vendor_id={vendor};doc={row['doc']}",
                                    quote=(
                                        f"payment={row['amt']}; date={row['d'].date()}; "
                                        f"text={row['booking_text']}"
                                    ),
                                ),
                            ],
                            search_tokens=[vendor, str(row["name"] or ""), str(row["doc"] or ""), creator],
                            entity_keys=[f"vendor:{vendor}"],
                            expects_document=True,
                        )
                    )
            except duckdb.Error:
                pass

    return hits


def _cols(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [str(r[0]) for r in conn.execute(f'DESCRIBE "{table}"').fetchall()]
