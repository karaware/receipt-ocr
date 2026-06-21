export type EntryType = "income" | "expense";
export type ReceiptStatus = "confirmed" | "needs_review";

export interface Transaction {
  id: string;
  type: EntryType;
  amount: number;
  date: string;
  majorCategory: string;
  minorCategory: string;
  itemName: string;
  memo: string;
  payer: string;
  shopName: string;
  source: "manual" | "ocr";
  receiptId?: string;
  receiptStatus: ReceiptStatus;
}

export interface Receipt {
  id: string;
  shopName: string;
  purchasedAt: string;
  totalAmount: number;
  payer: string;
  status: ReceiptStatus;
  reviewReason: string;
  difference: number;
}

export interface Category {
  id: string;
  name: string;
  type: EntryType;
  subcategories: string[];
}

export interface Budget { id: string; month: string; category: string; amount: number }
