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
        get() = if (prefs.getBoolean("folder_name_verified", false)) {
            prefs.getString("folder_name", UNKNOWN_FOLDER_NAME) ?: UNKNOWN_FOLDER_NAME
        } else UNKNOWN_FOLDER_NAME
        set(value) { prefs.edit().putString("folder_name", value).putBoolean("folder_name_verified", true).apply() }

    // Picker can return a valid folder grant without including an account email.
    // The email is retained when available, but payer + folder grant are sufficient.
    val configured get() = payer.isNotBlank() && folderId.isNotBlank()

    companion object {
        const val UNKNOWN_FOLDER_NAME = "選択済み（フォルダ名を取得できません）"
    }
}
