import { describe, expect, it } from "vitest";
import { summarize } from "./analytics";
import type { Transaction } from "./types";

const entry = (patch: Partial<Transaction>): Transaction => ({ id: "1", type: "expense", amount: 100, date: "2026-06-20", majorCategory: "食費", minorCategory: "食料品", itemName: "パン", memo: "", payer: "me", shopName: "店", source: "manual", receiptStatus: "confirmed", ...patch });

describe("summarize", () => {
  it("aggregates only confirmed transactions", () => {
    const result = summarize([entry({ amount: 300 }), entry({ id: "2", amount: 900, receiptStatus: "needs_review" }), entry({ id: "3", type: "income", amount: 1000 })], []);
    expect(result.expense).toBe(300);
    expect(result.income).toBe(1000);
    expect(result.balance).toBe(700);
    expect(result.byCategory["食費"]).toBe(300);
  });
});
