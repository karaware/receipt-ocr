import { FormEvent, useEffect, useMemo, useState } from "react";
import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { auth, provider } from "./firebase";
import {
  confirmReceipt, loadBudgets, loadCategories, loadMonth, loadReceiptItems,
  loadReviewReceipts, loadSystemAlerts, removeTransaction, saveBudget, saveCategory,
  saveManualTransaction, updateReceiptDraft,
} from "./data";
import { summarize } from "./analytics";
import type { Budget, Category, EntryType, Receipt, SystemAlert, Transaction } from "./types";

type Page = "dashboard" | "transactions" | "review" | "budgets" | "categories";
const yen = new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 });
const currentMonth = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" }).slice(0, 7);
const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [page, setPage] = useState<Page>("dashboard");
  const [month, setMonth] = useState(currentMonth());
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [reviews, setReviews] = useState<Receipt[]>([]);
  const [systemAlerts, setSystemAlerts] = useState<SystemAlert[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => onAuthStateChanged(auth, setUser), []);
  const refresh = async () => {
    if (!user) return;
    setBusy(true); setError("");
    try {
      const [nextTransactions, nextCategories, nextBudgets, nextReviews, nextAlerts] = await Promise.all([
        loadMonth(month), loadCategories(), loadBudgets(month), loadReviewReceipts(), loadSystemAlerts(),
      ]);
      setTransactions(nextTransactions); setCategories(nextCategories); setBudgets(nextBudgets); setReviews(nextReviews); setSystemAlerts(nextAlerts);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  useEffect(() => { void refresh(); }, [user, month]);

  if (user === undefined) return <div className="center">読み込み中…</div>;
  if (!user) return <Login onLogin={() => signInWithPopup(auth, provider).catch((reason) => setError(message(reason)))} error={error} />;

  return <div className="app-shell">
    <aside>
      <div className="brand"><span>¥</span><div>わが家の家計簿<small>Receipt OCR</small></div></div>
      <nav>
        <Nav active={page === "dashboard"} onClick={() => setPage("dashboard")} icon="⌂">ホーム</Nav>
        <Nav active={page === "transactions"} onClick={() => setPage("transactions")} icon="≡">取引</Nav>
        <Nav active={page === "review"} onClick={() => setPage("review")} icon="✓" badge={reviews.length}>確認</Nav>
        <Nav active={page === "budgets"} onClick={() => setPage("budgets")} icon="◎">予算</Nav>
        <Nav active={page === "categories"} onClick={() => setPage("categories")} icon="▦">カテゴリ</Nav>
      </nav>
      <button className="account" onClick={() => signOut(auth)}>{user.photoURL && <img src={user.photoURL} alt="" />}<span>{user.displayName}<small>ログアウト</small></span></button>
    </aside>
    <main>
      <header className="topbar">
        <div><h1>{pageTitle(page)}</h1><p>{page === "dashboard" ? "今月のお金の流れ" : "家計データを管理"}</p></div>
        <label className="month">対象月<input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
      </header>
      {error && <div className="alert">{error}<button onClick={() => setError("")}>×</button></div>}
      {busy ? <div className="loading">読み込み中…</div> : <>
        {page === "dashboard" && <Dashboard transactions={transactions} budgets={budgets} reviews={reviews.length} alerts={systemAlerts} />}
        {page === "transactions" && <Transactions entries={transactions} categories={categories} onChanged={refresh} onError={setError} />}
        {page === "review" && <Review receipts={reviews} categories={categories} onChanged={refresh} onError={setError} />}
        {page === "budgets" && <Budgets month={month} budgets={budgets} categories={categories} transactions={transactions} onChanged={refresh} onError={setError} />}
        {page === "categories" && <Categories categories={categories} onChanged={refresh} onError={setError} />}
      </>}
    </main>
    <div className="mobile-nav">
      <Nav active={page === "dashboard"} onClick={() => setPage("dashboard")} icon="⌂">ホーム</Nav>
      <Nav active={page === "transactions"} onClick={() => setPage("transactions")} icon="≡">取引</Nav>
      <Nav active={page === "review"} onClick={() => setPage("review")} icon="✓" badge={reviews.length}>確認</Nav>
      <Nav active={page === "budgets"} onClick={() => setPage("budgets")} icon="◎">予算</Nav>
    </div>
  </div>;
}

function Login({ onLogin, error }: { onLogin: () => void; error: string }) {
  return <div className="login"><div className="login-card"><div className="login-mark">¥</div><h1>わが家の家計簿</h1><p>レシートから、家計が見える。</p>{error && <div className="alert">{error}</div>}<button className="primary wide" onClick={onLogin}>Googleでログイン</button><small>許可された家族のアカウントだけが利用できます</small></div></div>;
}

function Nav({ active, onClick, icon, badge, children }: { active: boolean; onClick: () => void; icon: string; badge?: number; children: React.ReactNode }) {
  return <button className={active ? "active" : ""} onClick={onClick}><b>{icon}</b><span>{children}</span>{!!badge && <i>{badge}</i>}</button>;
}

function Dashboard({ transactions, budgets, reviews, alerts }: { transactions: Transaction[]; budgets: Budget[]; reviews: number; alerts: SystemAlert[] }) {
  const data = summarize(transactions, budgets);
  const maxDay = Math.max(...Object.values(data.byDay), 1);
  const categoryRows = Object.entries(data.byCategory).sort((a, b) => b[1] - a[1]);
  return <div className="stack">
    {alerts.length > 0 && <section className="panel system-alerts"><h2>システム警告</h2>{alerts.map((alert) => <article className={alert.severity} key={alert.id}><strong>{systemAlertLabel(alert.code)}</strong><span>{alert.message}</span>{alert.driveFileId && <small>対象: {alert.driveFileId}</small>}</article>)}</section>}
    {reviews > 0 && <div className="notice"><strong>{reviews}件のレシートが確認待ちです</strong><span>未確定データは集計に含まれていません。</span></div>}
    <section className="summary-grid">
      <Metric label="収入" value={data.income} tone="income" />
      <Metric label="支出" value={data.expense} tone="expense" />
      <Metric label="収支" value={data.balance} tone={data.balance >= 0 ? "balance" : "expense"} />
    </section>
    <div className="dashboard-grid">
      <section className="panel"><h2>カテゴリ別支出</h2>{categoryRows.length ? categoryRows.map(([name, value]) => <div className="bar-row" key={name}><div><span>{name}</span><strong>{yen.format(value)}</strong></div><div className="bar"><i style={{ width: `${data.expense ? value / data.expense * 100 : 0}%` }} /></div></div>) : <Empty />}</section>
      <section className="panel"><h2>日別支出</h2><div className="day-chart">{Object.entries(data.byDay).sort().map(([date, value]) => <div key={date} title={`${date}: ${yen.format(value)}`}><i style={{ height: `${value / maxDay * 100}%` }} /><small>{Number(date.slice(-2))}</small></div>)}</div>{!Object.keys(data.byDay).length && <Empty />}</section>
    </div>
    <section className="panel"><h2>予算の進捗</h2><div className="budget-grid">{Object.entries(data.budgetByCategory).map(([category, amount]) => { const actual = data.byCategory[category] ?? 0; const rate = amount ? actual / amount * 100 : 0; return <div className="budget-card" key={category}><div><strong>{category}</strong><span>{yen.format(actual)} / {yen.format(amount)}</span></div><div className="bar"><i className={rate > 100 ? "over" : ""} style={{ width: `${Math.min(rate, 100)}%` }} /></div><small>{Math.round(rate)}%</small></div>; })}</div>{!budgets.length && <Empty text="予算が設定されていません" />}</section>
  </div>;
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) { return <div className={`metric ${tone}`}><span>{label}</span><strong>{yen.format(value)}</strong></div>; }

function Transactions({ entries, categories, onChanged, onError }: { entries: Transaction[]; categories: Category[]; onChanged: () => Promise<void>; onError: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | undefined>();
  const [type, setType] = useState<"all" | EntryType>("all");
  const [category, setCategory] = useState("all");
  const visible = entries.filter((item) => (type === "all" || item.type === type) && (category === "all" || item.majorCategory === category));
  const edit = (item?: Transaction) => { setEditing(item); setOpen(true); };
  return <section className="panel">
    <div className="section-head"><div className="filters"><select value={type} onChange={(e) => setType(e.target.value as typeof type)}><option value="all">収支すべて</option><option value="expense">支出</option><option value="income">収入</option></select><select value={category} onChange={(e) => setCategory(e.target.value)}><option value="all">カテゴリすべて</option>{categories.map((item) => <option key={item.id}>{item.name}</option>)}</select></div><button className="primary" onClick={() => edit()}>＋ 手入力</button></div>
    <div className="transaction-list">{visible.map((item) => <article className="transaction" key={item.id}><div className={`tx-icon ${item.type}`}>{item.type === "income" ? "+" : "−"}</div><div className="tx-main"><strong>{item.itemName || item.shopName || item.majorCategory}</strong><span>{item.date} · {item.majorCategory} / {item.minorCategory} · {item.payer}</span></div><strong className={item.type}>{item.type === "income" ? "+" : "−"}{yen.format(Math.abs(item.amount))}</strong>{item.source === "manual" && <div className="row-actions"><button onClick={() => edit(item)}>編集</button><button onClick={async () => { if (confirm("この取引を削除しますか？")) { try { await removeTransaction(item.id); await onChanged(); } catch (e) { onError(message(e)); } } }}>削除</button></div>} {item.receiptStatus !== "confirmed" && <em>確認待ち</em>}</article>)}</div>{!visible.length && <Empty />}
    {open && <TransactionDialog item={editing} categories={categories} onClose={() => setOpen(false)} onSave={async (value) => { try { await saveManualTransaction(value, editing?.id); setOpen(false); await onChanged(); } catch (e) { onError(message(e)); } }} />}
  </section>;
}

function TransactionDialog({ item, categories, onClose, onSave }: { item?: Transaction; categories: Category[]; onClose: () => void; onSave: (value: Omit<Transaction, "id" | "source" | "receiptStatus">) => void }) {
  const [value, setValue] = useState({ type: item?.type ?? "expense" as EntryType, amount: item?.amount ?? 0, date: item?.date ?? today(), majorCategory: item?.majorCategory ?? "", minorCategory: item?.minorCategory ?? "", itemName: item?.itemName ?? "", memo: item?.memo ?? "", payer: item?.payer ?? "", shopName: item?.shopName ?? "" });
  const available = categories.filter((entry) => entry.type === value.type);
  const minors = available.find((entry) => entry.name === value.majorCategory)?.subcategories ?? [];
  return <Dialog title={item ? "取引を編集" : "取引を追加"} onClose={onClose}><form onSubmit={(event) => { event.preventDefault(); onSave(value); }} className="form-grid"><label>収支<select value={value.type} onChange={(e) => setValue({ ...value, type: e.target.value as EntryType, majorCategory: "", minorCategory: "" })}><option value="expense">支出</option><option value="income">収入</option></select></label><label>日付<input type="date" required value={value.date} onChange={(e) => setValue({ ...value, date: e.target.value })} /></label><label>金額<input type="number" min="1" required value={value.amount || ""} onChange={(e) => setValue({ ...value, amount: Number(e.target.value) })} /></label><label>支払者<input required value={value.payer} onChange={(e) => setValue({ ...value, payer: e.target.value })} /></label><label>大カテゴリ<select required value={value.majorCategory} onChange={(e) => setValue({ ...value, majorCategory: e.target.value, minorCategory: "" })}><option value="">選択</option>{available.map((entry) => <option key={entry.id}>{entry.name}</option>)}</select></label><label>小カテゴリ<select required value={value.minorCategory} onChange={(e) => setValue({ ...value, minorCategory: e.target.value })}><option value="">選択</option>{minors.map((name) => <option key={name}>{name}</option>)}</select></label><label className="full">内容<input required value={value.itemName} onChange={(e) => setValue({ ...value, itemName: e.target.value })} /></label><label>店名<input value={value.shopName} onChange={(e) => setValue({ ...value, shopName: e.target.value })} /></label><label>メモ<input value={value.memo} onChange={(e) => setValue({ ...value, memo: e.target.value })} /></label><div className="dialog-actions full"><button type="button" onClick={onClose}>キャンセル</button><button className="primary">保存</button></div></form></Dialog>;
}

function Review({ receipts, categories, onChanged, onError }: { receipts: Receipt[]; categories: Category[]; onChanged: () => Promise<void>; onError: (value: string) => void }) {
  const [selected, setSelected] = useState<Receipt>();
  return <div className="review-grid"><section className="panel"><h2>確認待ち</h2>{receipts.map((receipt) => <button className="receipt-card" key={receipt.id} onClick={() => setSelected(receipt)}><div><strong>{receipt.shopName || "店名なし"}</strong><span>{receipt.purchasedAt || "日付なし"} · {receipt.payer}</span></div><b>{yen.format(receipt.totalAmount)}</b><small>{reasonLabel(receipt.reviewReason)}</small></button>)}{!receipts.length && <Empty text="確認待ちのレシートはありません" />}</section>{selected ? <ReceiptEditor receipt={selected} categories={categories} onDone={async () => { setSelected(undefined); await onChanged(); }} onError={onError} /> : <section className="panel review-placeholder">レシートを選択してください</section>}</div>;
}

function ReceiptEditor({ receipt: initial, categories, onDone, onError }: { receipt: Receipt; categories: Category[]; onDone: () => Promise<void>; onError: (value: string) => void }) {
  const [receipt, setReceipt] = useState(initial);
  const [items, setItems] = useState<Transaction[]>([]);
  useEffect(() => { setReceipt(initial); loadReceiptItems(initial.id).then(setItems).catch((e) => onError(message(e))); }, [initial.id]);
  const difference = Number(receipt.totalAmount) - items.reduce((sum, item) => sum + Number(item.amount), 0);
  const updateItem = (id: string, patch: Partial<Transaction>) => setItems(items.map((item) => item.id === id ? { ...item, ...patch } : item));
  const addItem = () => setItems([...items, { id: `new-${crypto.randomUUID()}`, type: "expense", amount: difference, date: receipt.purchasedAt, majorCategory: "調整", minorCategory: "その他", itemName: "調整明細", memo: "", payer: receipt.payer, shopName: receipt.shopName, source: "ocr", receiptId: receipt.id, receiptStatus: "needs_review" }]);
  return <section className="panel receipt-editor"><h2>レシートを確認</h2><div className="form-grid compact"><label>店名<input value={receipt.shopName} onChange={(e) => setReceipt({ ...receipt, shopName: e.target.value })} /></label><label>日付<input type="date" value={receipt.purchasedAt} onChange={(e) => setReceipt({ ...receipt, purchasedAt: e.target.value })} /></label><label>支払者<input value={receipt.payer} onChange={(e) => setReceipt({ ...receipt, payer: e.target.value })} /></label><label>レシート合計<input type="number" value={receipt.totalAmount} onChange={(e) => setReceipt({ ...receipt, totalAmount: Number(e.target.value) })} /></label></div><div className="item-editor-head"><strong>明細</strong><div><span className={difference ? "difference bad" : "difference"}>差額 {yen.format(difference)}</span><button className="text-button" onClick={addItem}>＋ 明細追加</button></div></div><div className="item-edit-list">{items.map((item) => { const category = categories.find((entry) => entry.name === item.majorCategory); return <div className="item-edit" key={item.id}><input value={item.itemName} onChange={(e) => updateItem(item.id, { itemName: e.target.value })} /><input className="amount-input" type="number" value={item.amount} onChange={(e) => updateItem(item.id, { amount: Number(e.target.value) })} /><select value={item.majorCategory} onChange={(e) => updateItem(item.id, { majorCategory: e.target.value, minorCategory: "" })}><option value="">大カテゴリ</option>{categories.filter((entry) => entry.type === "expense").map((entry) => <option key={entry.id}>{entry.name}</option>)}</select><div className="minor-remove"><select value={item.minorCategory} onChange={(e) => updateItem(item.id, { minorCategory: e.target.value })}><option value="">小カテゴリ</option>{category?.subcategories.map((name) => <option key={name}>{name}</option>)}</select><button title="明細を削除" onClick={() => setItems(items.filter((entry) => entry.id !== item.id))}>×</button></div></div>; })}</div><div className="dialog-actions"><button onClick={async () => { try { await updateReceiptDraft(receipt, items); await onDone(); } catch (e) { onError(message(e)); } }}>下書き保存</button><button className="primary" disabled={difference !== 0} onClick={async () => { try { await confirmReceipt(receipt, items); await onDone(); } catch (e) { onError(message(e)); } }}>確定する</button></div></section>;
}

function Budgets({ month, budgets, categories, transactions, onChanged, onError }: { month: string; budgets: Budget[]; categories: Category[]; transactions: Transaction[]; onChanged: () => Promise<void>; onError: (value: string) => void }) {
  const data = summarize(transactions, budgets);
  return <section className="panel"><h2>{month.replace("-", "年")}月の予算</h2><div className="budget-table">{categories.filter((item) => item.type === "expense" && item.name !== "調整").map((category) => { const budget = budgets.find((item) => item.category === category.name)?.amount ?? 0; const actual = data.byCategory[category.name] ?? 0; return <BudgetRow key={category.id} category={category.name} initial={budget} actual={actual} onSave={async (amount) => { try { await saveBudget(month, category.name, amount); await onChanged(); } catch (e) { onError(message(e)); } }} />; })}</div></section>;
}

function BudgetRow({ category, initial, actual, onSave }: { category: string; initial: number; actual: number; onSave: (value: number) => void }) { const [amount, setAmount] = useState(initial); useEffect(() => setAmount(initial), [initial]); return <div className="budget-row"><strong>{category}</strong><span>実績 {yen.format(actual)}</span><input type="number" min="0" value={amount || ""} placeholder="0" onChange={(e) => setAmount(Number(e.target.value))} /><button onClick={() => onSave(amount)}>保存</button></div>; }

function Categories({ categories, onChanged, onError }: { categories: Category[]; onChanged: () => Promise<void>; onError: (value: string) => void }) {
  const [name, setName] = useState(""); const [type, setType] = useState<EntryType>("expense"); const [subs, setSubs] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await saveCategory({ id: encodeURIComponent(name.toLocaleLowerCase("ja-JP")), name, type, subcategories: subs.split(",").map((v) => v.trim()).filter(Boolean) }); setName(""); setSubs(""); await onChanged(); } catch (e) { onError(message(e)); } };
  return <div className="dashboard-grid"><section className="panel"><h2>カテゴリ一覧</h2>{categories.map((category) => <article className="category-row" key={category.id}><div className={`tx-icon ${category.type}`}>{category.type === "income" ? "+" : "−"}</div><div><strong>{category.name}</strong><span>{category.subcategories.join(" · ")}</span></div></article>)}</section><section className="panel"><h2>カテゴリ追加</h2><form className="form-grid" onSubmit={submit}><label>収支<select value={type} onChange={(e) => setType(e.target.value as EntryType)}><option value="expense">支出</option><option value="income">収入</option></select></label><label>大カテゴリ<input required value={name} onChange={(e) => setName(e.target.value)} /></label><label className="full">小カテゴリ（カンマ区切り）<input required value={subs} onChange={(e) => setSubs(e.target.value)} placeholder="食料品, 外食, その他" /></label><button className="primary full">追加</button></form></section></div>;
}

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="dialog-backdrop" onMouseDown={onClose}><div className="dialog" onMouseDown={(e) => e.stopPropagation()}><div className="dialog-head"><h2>{title}</h2><button onClick={onClose}>×</button></div>{children}</div></div>; }
function Empty({ text = "表示するデータがありません" }: { text?: string }) { return <div className="empty">{text}</div>; }
function message(reason: unknown) { return reason instanceof Error ? reason.message : String(reason); }
function pageTitle(page: Page) { return ({ dashboard: "ホーム", transactions: "取引一覧", review: "レシート確認", budgets: "予算", categories: "カテゴリ管理" })[page]; }
function reasonLabel(reason: string) { return ({ initial_migration: "初回移行", missing_required: "必須項目不足", unexplained_difference: "差額あり", uncategorized: "未分類あり" } as Record<string, string>)[reason] ?? "要確認"; }
function systemAlertLabel(code: string) { return ({ codex_auth_blocked: "Codex認証停止", codex_rate_limit_over_24h: "Codex利用上限", codex_worker_unavailable: "Codex worker停止", llm_exhausted: "自動解析できないレシート", spool_cleanup_failed: "一時データ削除失敗" } as Record<string, string>)[code] ?? "システム警告"; }
