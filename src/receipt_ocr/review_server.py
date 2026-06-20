from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs

from .config import load_config
from .db import connect
from .exporter import export_csv


UNCATEGORIZED = "未分類"


def run_review_server(config_path: str, host: str, port: int) -> None:
    server = ThreadingHTTPServer(
        (host, port), _handler_factory(Path(config_path), load_config(config_path))
    )
    print(f"review_url=http://{host}:{port}")
    server.serve_forever()


def get_uncategorized_items(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    conn = connect(config["paths"]["db_path"])
    rows = conn.execute(
        """
        SELECT
            i.id,
            i.item_name,
            i.amount,
            i.category,
            r.shop_name,
            r.purchased_at,
            r.payer
        FROM receipt_items i
        JOIN receipts r ON r.id = i.receipt_id
        WHERE i.category = ?
        ORDER BY r.purchased_at DESC, i.id DESC
        """,
        (UNCATEGORIZED,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_receipts(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    conn = connect(config["paths"]["db_path"])
    rows = conn.execute(
        """
        SELECT id, payer, shop_name, purchased_at, total_amount, source_path, created_at
        FROM receipts
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_items(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    conn = connect(config["paths"]["db_path"])
    rows = conn.execute(
        """
        SELECT
            r.id AS receipt_id,
            r.payer,
            r.shop_name,
            r.purchased_at,
            i.item_name,
            i.amount,
            i.category,
            i.confidence
        FROM receipt_items i
        JOIN receipts r ON r.id = i.receipt_id
        ORDER BY i.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def apply_category(
    config_path: Path,
    config: Dict[str, Any],
    item_id: int,
    category: str,
    keyword: str | None,
) -> None:
    categories = config.get("categories", {})
    if category not in categories:
        raise ValueError(f"Unknown category: {category}")

    conn = connect(config["paths"]["db_path"])
    row = conn.execute(
        "SELECT item_name FROM receipt_items WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Item not found: {item_id}")

    clean_keyword = (keyword or row["item_name"]).strip()
    if clean_keyword:
        keywords = categories.setdefault(category, [])
        if clean_keyword not in keywords:
            keywords.append(clean_keyword)
            _save_config(config_path, config)

    conn.execute(
        """
        UPDATE receipt_items
        SET category = ?, confidence = 1.0
        WHERE id = ?
        """,
        (category, item_id),
    )
    if clean_keyword:
        conn.execute(
            """
            UPDATE receipt_items
            SET category = ?, confidence = 1.0
            WHERE category = ? AND item_name LIKE ?
            """,
            (category, UNCATEGORIZED, f"%{clean_keyword}%"),
        )
    conn.commit()
    export_csv(conn, config["paths"]["export_dir"])


def _handler_factory(config_path: Path, config: Dict[str, Any]):
    class ReviewHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in {"/", "/review"}:
                self._send_html(_render_review_page(config))
                return
            if self.path == "/receipts":
                self._send_html(
                    _render_table_page(
                        title="レシート一覧",
                        active="receipts",
                        rows=get_receipts(config),
                        columns=[
                            ("id", "ID"),
                            ("payer", "支払者"),
                            ("shop_name", "店名"),
                            ("purchased_at", "日付"),
                            ("total_amount", "合計"),
                            ("source_path", "画像"),
                            ("created_at", "登録日時"),
                        ],
                    )
                )
                return
            if self.path == "/items":
                self._send_html(
                    _render_table_page(
                        title="明細一覧",
                        active="items",
                        rows=get_items(config),
                        columns=[
                            ("receipt_id", "レシートID"),
                            ("payer", "支払者"),
                            ("shop_name", "店名"),
                            ("purchased_at", "日付"),
                            ("item_name", "商品名"),
                            ("amount", "金額"),
                            ("category", "カテゴリ"),
                            ("confidence", "信頼度"),
                        ],
                    )
                )
                return
            else:
                self.send_error(404)
                return

        def do_POST(self) -> None:
            if self.path != "/categorize":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            data = parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                apply_category(
                    config_path,
                    config,
                    item_id=int(_first(data, "item_id")),
                    category=_first(data, "category"),
                    keyword=_first(data, "keyword"),
                )
            except Exception as error:
                self.send_error(400, str(error))
                return
            self.send_response(303)
            self.send_header("Location", "/review")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return ReviewHandler


def _render_review_page(config: Dict[str, Any]) -> str:
    items = get_uncategorized_items(config)
    categories = list(config.get("categories", {}).keys())
    rows = "\n".join(_render_item(item, categories) for item in items)
    empty = ""
    if not items:
        empty = '<section class="empty">未分類の商品はありません。</section>'
    return _page_shell(
        title="未分類レビュー",
        active="review",
        summary=f"{len(items)}件の確認待ち",
        content=f"{empty}\n{rows}",
    )


def _page_shell(title: str, active: str, summary: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Receipt OCR Review</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #232521;
      --muted: #697067;
      --line: #dfe3dc;
      --accent: #246b55;
      --accent-dark: #174b3b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      padding: 16px;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .wrap {{
      max-width: 920px;
      margin: 0 auto;
    }}
    h1 {{
      font-size: 22px;
      line-height: 1.2;
      margin: 0 0 4px;
      letter-spacing: 0;
    }}
    .summary {{
      color: var(--muted);
      font-size: 14px;
    }}
    nav {{
      display: flex;
      gap: 8px;
      margin-top: 12px;
      overflow-x: auto;
    }}
    nav a {{
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      text-decoration: none;
      white-space: nowrap;
      background: #fff;
      font-size: 14px;
    }}
    nav a.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 650;
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      padding: 16px;
    }}
    .item {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 10px;
      padding: 14px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 5px;
    }}
    .name {{
      font-size: 17px;
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .amount {{
      font-size: 16px;
      font-variant-numeric: tabular-nums;
    }}
    form {{
      display: grid;
      grid-template-columns: minmax(120px, 180px) minmax(160px, 1fr) auto;
      gap: 8px;
      align-items: end;
    }}
    label {{
      display: grid;
      gap: 4px;
      font-size: 12px;
      color: var(--muted);
    }}
    select, input, button {{
      min-height: 40px;
      border-radius: 6px;
      border: 1px solid var(--line);
      font: inherit;
      padding: 8px 10px;
      background: #fff;
      color: var(--text);
    }}
    button {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
      font-weight: 650;
      cursor: pointer;
      white-space: nowrap;
    }}
    button:hover {{
      background: var(--accent-dark);
    }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      color: var(--muted);
    }}
    .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f0f2ed;
      font-size: 12px;
      color: var(--muted);
      position: sticky;
      top: 0;
    }}
    td.number {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    td.path {{
      max-width: 360px;
      overflow-wrap: anywhere;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 680px) {{
      form {{
        grid-template-columns: 1fr;
      }}
      button {{
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>{html.escape(title)}</h1>
      <div class="summary">{html.escape(summary)}</div>
      <nav>
        {_nav_link("/review", "未分類レビュー", active == "review")}
        {_nav_link("/receipts", "レシート一覧", active == "receipts")}
        {_nav_link("/items", "明細一覧", active == "items")}
      </nav>
    </div>
  </header>
  <main>
    {content}
  </main>
</body>
</html>"""


def _render_table_page(
    title: str,
    active: str,
    rows: List[Dict[str, Any]],
    columns: List[tuple[str, str]],
) -> str:
    if not rows:
        content = '<section class="empty">表示するデータはありません。</section>'
    else:
        header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
        body = "\n".join(_render_table_row(row, columns) for row in rows)
        content = f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'
    return _page_shell(
        title=title,
        active=active,
        summary=f"{len(rows)}件",
        content=content,
    )


def _render_table_row(row: Dict[str, Any], columns: List[tuple[str, str]]) -> str:
    cells = []
    for key, _ in columns:
        value = row.get(key, "")
        css_class = ""
        if key in {"amount", "total_amount", "confidence", "id", "receipt_id"}:
            css_class = ' class="number"'
        elif key == "source_path":
            css_class = ' class="path"'
        cells.append(f"<td{css_class}>{_format_cell(key, value)}</td>")
    return f"<tr>{''.join(cells)}</tr>"


def _format_cell(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key in {"amount", "total_amount"}:
        return html.escape(f"{int(value):,}")
    if key == "confidence":
        return html.escape(f"{float(value):.1f}")
    return html.escape(str(value))


def _nav_link(path: str, label: str, active: bool) -> str:
    class_name = ' class="active"' if active else ""
    return f'<a href="{path}"{class_name}>{html.escape(label)}</a>'


def _render_item(item: Dict[str, Any], categories: List[str]) -> str:
    item_id = int(item["id"])
    options = "\n".join(
        f'<option value="{html.escape(category)}">{html.escape(category)}</option>'
        for category in categories
    )
    name = str(item["item_name"])
    return f"""<section class="item" data-item-id="{item_id}">
  <div>
    <div class="meta">{html.escape(str(item["shop_name"] or ""))} / {html.escape(str(item["purchased_at"] or ""))} / {html.escape(str(item["payer"] or ""))}</div>
    <div class="name">{html.escape(name)}</div>
    <div class="amount">{int(item["amount"]):,}円</div>
  </div>
  <form method="post" action="/categorize">
    <input type="hidden" name="item_id" value="{item_id}">
    <label>カテゴリ
      <select name="category">{options}</select>
    </label>
    <label>次回から使うキーワード
      <input name="keyword" value="{html.escape(name)}">
    </label>
    <button type="submit">登録</button>
  </form>
</section>"""


def _first(data: Dict[str, List[str]], key: str) -> str:
    values = data.get(key)
    if not values:
        return ""
    return values[0]


def _save_config(config_path: Path, config: Dict[str, Any]) -> None:
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
