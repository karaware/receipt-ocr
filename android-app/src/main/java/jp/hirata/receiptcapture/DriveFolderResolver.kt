package jp.hirata.receiptcapture

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Looks up the Picker-selected folder using the same drive.file grant used for uploads. */
class DriveFolderResolver(private val token: String) {
    fun name(folderId: String): String? {
        val url = "https://www.googleapis.com/drive/v3/files/$folderId?fields=id,name&supportsAllDrives=true"
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 30_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer $token")
        }
        return try {
            if (connection.responseCode != HttpURLConnection.HTTP_OK) return null
            JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                .optString("name")
                .trim()
                .ifBlank { null }
        } finally {
            connection.disconnect()
        }
    }
}
