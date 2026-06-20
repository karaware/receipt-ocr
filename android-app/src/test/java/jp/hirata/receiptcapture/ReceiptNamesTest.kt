package jp.hirata.receiptcapture

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.Base64

class ReceiptNamesTest {
    @Test fun payerRoundTripsAndFilenameIsSafe() {
        val payer = "妻 家計#1"
        val token = ReceiptNames.payerToken(payer)
        assertEquals(payer, String(Base64.getUrlDecoder().decode(token), Charsets.UTF_8))
        assertEquals(
            "receipt__${token}__20260620T010203Z__abc-123.jpg",
            ReceiptNames.fileName(payer, "abc-123", Instant.parse("2026-06-20T01:02:03Z")),
        )
    }
}
