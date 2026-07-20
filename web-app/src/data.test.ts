import { afterEach, describe, expect, it, vi } from "vitest";

const firestore = vi.hoisted(() => {
  const batch = { delete: vi.fn(), update: vi.fn(), commit: vi.fn() };
  const doc = vi.fn((parent: unknown, ...segments: string[]) => ({ path: "path" in Object(parent) ? `${(parent as { path: string }).path}/${segments.join("/")}` : segments.join("/") }));
  return {
    batch, doc, getDoc: vi.fn(), getDocs: vi.fn(), writeBatch: vi.fn(() => batch),
    collection: vi.fn((parent: { path: string }, name: string) => ({ path: `${parent.path}/${name}` })),
    query: vi.fn((reference: unknown) => reference), where: vi.fn(), serverTimestamp: vi.fn(() => "now"),
    addDoc: vi.fn(), deleteDoc: vi.fn(), orderBy: vi.fn(), setDoc: vi.fn(), updateDoc: vi.fn(),
  };
});

vi.mock("./firebase", () => ({ db: {}, householdId: "test-household" }));
vi.mock("firebase/firestore", () => firestore);

import { removeReviewReceipt } from "./data";

const snapshot = (...documents: Array<{ ref: unknown; data: () => Record<string, unknown> }>) => ({ docs: documents });

describe("removeReviewReceipt", () => {
  afterEach(() => vi.clearAllMocks());

  it("deletes every matching transaction, resolves alerts, and deletes the receipt in one batch", async () => {
    const receiptRef = { path: "receipts/receipt-1" };
    const firstTransaction = { ref: { path: "transactions/one" }, data: () => ({}) };
    const secondTransaction = { ref: { path: "transactions/two" }, data: () => ({}) };
    const unresolvedAlert = { ref: { path: "system_alerts/open" }, data: () => ({ resolvedAt: null }) };
    const resolvedAlert = { ref: { path: "system_alerts/closed" }, data: () => ({ resolvedAt: "already" }) };
    firestore.getDoc.mockResolvedValue({ exists: () => true, data: () => ({ status: "needs_review" }) });
    firestore.getDocs.mockResolvedValueOnce(snapshot(firstTransaction, secondTransaction)).mockResolvedValueOnce(snapshot(unresolvedAlert, resolvedAlert));
    firestore.batch.commit.mockResolvedValue(undefined);

    await removeReviewReceipt("receipt-1");

    expect(firestore.batch.delete).toHaveBeenCalledWith(firstTransaction.ref);
    expect(firestore.batch.delete).toHaveBeenCalledWith(secondTransaction.ref);
    expect(firestore.batch.update).toHaveBeenCalledWith(unresolvedAlert.ref, { resolvedAt: "now" });
    expect(firestore.batch.update).not.toHaveBeenCalledWith(resolvedAlert.ref, expect.anything());
    expect(firestore.batch.delete).toHaveBeenCalledWith(expect.objectContaining({ path: "households/test-household/receipts/receipt-1" }));
    expect(firestore.batch.commit).toHaveBeenCalledOnce();
  });

  it("propagates a batch failure without reporting a successful removal", async () => {
    firestore.getDoc.mockResolvedValue({ exists: () => true, data: () => ({ status: "needs_review" }) });
    firestore.getDocs.mockResolvedValue(snapshot());
    firestore.batch.commit.mockRejectedValue(new Error("permission-denied"));

    await expect(removeReviewReceipt("receipt-1")).rejects.toThrow("permission-denied");
  });
});
