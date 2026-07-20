import {
  addDoc, collection, deleteDoc, doc, getDoc, getDocs, orderBy, query,
  serverTimestamp, setDoc, updateDoc, where, writeBatch,
} from "firebase/firestore";
import { db, householdId } from "./firebase";
import type { Budget, Category, Receipt, SystemAlert, Transaction } from "./types";

const root = () => doc(db, "households", householdId);
const sub = (name: string) => collection(root(), name);
export const adjustmentMinorCategory = "値引き・税・手数料";
const values = <T>(snapshot: Awaited<ReturnType<typeof getDocs>>): T[] =>
  snapshot.docs.map((item) => Object.assign({ id: item.id }, item.data()) as T);

export async function loadMonth(month: string): Promise<Transaction[]> {
  const start = `${month}-01`;
  const [year, number] = month.split("-").map(Number);
  const endDate = new Date(Date.UTC(year, number, 1));
  const end = endDate.toISOString().slice(0, 10);
  const snapshot = await getDocs(query(sub("transactions"), where("date", ">=", start), where("date", "<", end), orderBy("date", "desc")));
  return values<Transaction>(snapshot);
}

export async function loadCategories(): Promise<Category[]> {
  return values<Category>(await getDocs(sub("categories"))).map((category) => category.type === "expense"
    ? { ...category, subcategories: [...new Set([...category.subcategories, adjustmentMinorCategory])] }
    : category);
}

export async function loadBudgets(month: string): Promise<Budget[]> {
  return values<Budget>(await getDocs(query(sub("budgets"), where("month", "==", month))));
}

export async function loadReviewReceipts(): Promise<Receipt[]> {
  return values<Receipt>(await getDocs(query(sub("receipts"), where("status", "==", "needs_review"), orderBy("purchasedAt", "desc"))));
}

export async function loadSystemAlerts(): Promise<SystemAlert[]> {
  const alerts = values<SystemAlert>(await getDocs(sub("system_alerts")));
  return alerts.filter((alert) => !alert.resolvedAt);
}

export async function loadReceiptItems(receiptId: string): Promise<Transaction[]> {
  return values<Transaction>(await getDocs(query(sub("transactions"), where("receiptId", "==", receiptId))));
}

/** Removes an unconfirmed OCR receipt and every record derived from it atomically. */
export async function removeReviewReceipt(receiptId: string): Promise<void> {
  const receiptRef = doc(sub("receipts"), receiptId);
  const receipt = await getDoc(receiptRef);
  if (!receipt.exists()) throw new Error("レシートが見つかりません");
  if (receipt.data().status !== "needs_review") throw new Error("確定済みレシートは削除できません");

  const [transactions, alerts] = await Promise.all([
    getDocs(query(sub("transactions"), where("receiptId", "==", receiptId))),
    getDocs(query(sub("system_alerts"), where("driveFileId", "==", receiptId))),
  ]);
  const batch = writeBatch(db);
  transactions.docs.forEach((item) => batch.delete(item.ref));
  alerts.docs
    .filter((alert) => alert.data().resolvedAt == null)
    .forEach((alert) => batch.update(alert.ref, { resolvedAt: serverTimestamp() }));
  batch.delete(receiptRef);
  await batch.commit();
}

export async function saveManualTransaction(value: Omit<Transaction, "id" | "source" | "receiptStatus">, id?: string): Promise<void> {
  const payload = { ...value, source: "manual", receiptStatus: "confirmed", updatedAt: serverTimestamp() };
  if (id) await updateDoc(doc(sub("transactions"), id), payload);
  else await addDoc(sub("transactions"), { ...payload, createdAt: serverTimestamp() });
}

export async function removeTransaction(id: string): Promise<void> {
  await deleteDoc(doc(sub("transactions"), id));
}

export async function saveBudget(month: string, category: string, amount: number): Promise<void> {
  await setDoc(doc(sub("budgets"), `${month}-${encodeURIComponent(category)}`), { month, category, amount, updatedAt: serverTimestamp() });
}

export async function saveCategory(category: Category): Promise<void> {
  const subcategories = category.type === "expense"
    ? [...new Set([...category.subcategories, adjustmentMinorCategory])]
    : category.subcategories;
  await setDoc(doc(sub("categories"), category.id), { ...category, subcategories }, { merge: true });
}

export function normalizeItemName(value: string): string {
  return value.trim().toLocaleLowerCase("ja-JP").replace(/\s+/g, "");
}

export async function confirmReceipt(receipt: Receipt, items: Transaction[]): Promise<void> {
  const sum = items.reduce((total, item) => total + Number(item.amount), 0);
  if (sum !== Number(receipt.totalAmount)) throw new Error(`明細合計とレシート合計の差額が${receipt.totalAmount - sum}円あります`);
  if (!receipt.shopName || !receipt.purchasedAt || items.some((item) => !item.majorCategory || item.majorCategory === "その他" && item.minorCategory === "未分類")) {
    throw new Error("必須項目または未分類の明細が残っています");
  }
  const batch = writeBatch(db);
  batch.update(doc(sub("receipts"), receipt.id), { ...receipt, status: "confirmed", difference: 0, reviewReason: "reconciled", updatedAt: serverTimestamp() });
  const stored = await getDocs(query(sub("transactions"), where("receiptId", "==", receipt.id)));
  const alerts = await getDocs(query(sub("system_alerts"), where("driveFileId", "==", receipt.id)));
  alerts.docs
    .filter((alert) => alert.data().resolvedAt == null)
    .forEach((alert) => batch.update(alert.ref, { resolvedAt: serverTimestamp() }));
  const retained = new Set(items.filter((item) => !item.id.startsWith("new-")).map((item) => item.id));
  stored.docs.filter((item) => !retained.has(item.id)).forEach((item) => batch.delete(item.ref));
  for (const item of items) {
    const { id, ...payload } = item;
    const itemRef = id.startsWith("new-") ? doc(sub("transactions")) : doc(sub("transactions"), id);
    batch.set(itemRef, { ...payload, receiptId: receipt.id, source: "ocr", receiptStatus: "confirmed", createdAt: serverTimestamp(), updatedAt: serverTimestamp() }, { merge: true });
    if (item.itemName && item.majorCategory !== "調整" && item.minorCategory !== adjustmentMinorCategory) {
      const normalized = normalizeItemName(item.itemName);
      batch.set(doc(sub("category_rules"), encodeURIComponent(normalized)), { normalized_name: normalized, category: item.majorCategory, minorCategory: item.minorCategory, updatedAt: serverTimestamp() });
    }
  }
  await batch.commit();
}

export async function updateReceiptDraft(receipt: Receipt, items: Transaction[]): Promise<void> {
  const batch = writeBatch(db);
  batch.update(doc(sub("receipts"), receipt.id), { shopName: receipt.shopName, purchasedAt: receipt.purchasedAt, totalAmount: Number(receipt.totalAmount), payer: receipt.payer, updatedAt: serverTimestamp() });
  const stored = await getDocs(query(sub("transactions"), where("receiptId", "==", receipt.id)));
  const retained = new Set(items.filter((item) => !item.id.startsWith("new-")).map((item) => item.id));
  stored.docs.filter((item) => !retained.has(item.id)).forEach((item) => batch.delete(item.ref));
  for (const item of items) {
    const { id, ...payload } = item;
    const itemRef = id.startsWith("new-") ? doc(sub("transactions")) : doc(sub("transactions"), id);
    batch.set(itemRef, { ...payload, receiptId: receipt.id, source: "ocr", receiptStatus: "needs_review", amount: Number(item.amount), date: receipt.purchasedAt, shopName: receipt.shopName, payer: receipt.payer, createdAt: serverTimestamp(), updatedAt: serverTimestamp() }, { merge: true });
  }
  await batch.commit();
}
