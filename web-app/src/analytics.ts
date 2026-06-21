import type { Budget, Transaction } from "./types";

export function summarize(transactions: Transaction[], budgets: Budget[]) {
  const confirmed = transactions.filter((item) => item.receiptStatus === "confirmed");
  const income = confirmed.filter((item) => item.type === "income").reduce((sum, item) => sum + Number(item.amount), 0);
  const expense = confirmed.filter((item) => item.type === "expense").reduce((sum, item) => sum + Number(item.amount), 0);
  const byCategory: Record<string, number> = {};
  const byDay: Record<string, number> = {};
  for (const item of confirmed.filter((entry) => entry.type === "expense")) {
    byCategory[item.majorCategory] = (byCategory[item.majorCategory] ?? 0) + Number(item.amount);
    byDay[item.date] = (byDay[item.date] ?? 0) + Number(item.amount);
  }
  const budgetByCategory = Object.fromEntries(budgets.map((budget) => [budget.category, Number(budget.amount)]));
  return { income, expense, balance: income - expense, byCategory, byDay, budgetByCategory };
}
