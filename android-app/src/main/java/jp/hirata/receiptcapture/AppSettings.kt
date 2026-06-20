package jp.hirata.receiptcapture

import android.content.Context

class AppSettings(context: Context) {
    private val prefs = context.getSharedPreferences("receipt_capture", Context.MODE_PRIVATE)

    var payer: String
        get() = prefs.getString("payer", "") ?: ""
        set(value) { prefs.edit().putString("payer", value.trim()).apply() }
    var accountName: String
        get() = prefs.getString("account", "") ?: ""
        set(value) { prefs.edit().putString("account", value).apply() }
    var folderId: String
        get() = prefs.getString("folder_id", "") ?: ""
        set(value) { prefs.edit().putString("folder_id", value).apply() }
    var folderName: String
        get() = prefs.getString("folder_name", "receipt-inbox") ?: "receipt-inbox"
        set(value) { prefs.edit().putString("folder_name", value).apply() }

    val configured get() = payer.isNotBlank() && accountName.isNotBlank() && folderId.isNotBlank()
}
