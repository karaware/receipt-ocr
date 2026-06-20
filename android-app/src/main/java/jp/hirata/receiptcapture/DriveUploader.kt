package jp.hirata.receiptcapture

import android.net.Uri
import org.json.JSONObject
import java.io.*
import java.net.HttpURLConnection
import java.net.URL

class DriveUploader(private val token: String, private val folderId: String) {
    fun upload(file: File, remoteName: String, uploadId: String): String {
        findExisting(uploadId)?.let { return it }
        val metadata = JSONObject().apply {
            put("name", remoteName)
            put("mimeType", "image/jpeg")
            put("parents", org.json.JSONArray().put(folderId))
            put("appProperties", JSONObject().put("receipt_upload_id", uploadId))
        }
        val start = connection(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true",
            "POST",
        ).apply {
            setRequestProperty("Content-Type", "application/json; charset=UTF-8")
            setRequestProperty("X-Upload-Content-Type", "image/jpeg")
            setRequestProperty("X-Upload-Content-Length", file.length().toString())
            doOutput = true
            outputStream.use { it.write(metadata.toString().toByteArray()) }
        }
        checkResponse(start, setOf(200, 201))
        val location = start.getHeaderField("Location") ?: error("Driveが再開用URLを返しませんでした")
        val upload = connection(location, "PUT").apply {
            setRequestProperty("Content-Type", "image/jpeg")
            setFixedLengthStreamingMode(file.length())
            doOutput = true
            outputStream.use { output -> file.inputStream().use { it.copyTo(output) } }
        }
        val body = checkResponse(upload, setOf(200, 201))
        return JSONObject(body).getString("id")
    }

    private fun findExisting(uploadId: String): String? {
        val escaped = uploadId.replace("'", "\\'")
        val query = "appProperties has { key='receipt_upload_id' and value='$escaped' } and trashed=false"
        val url = "https://www.googleapis.com/drive/v3/files?q=${Uri.encode(query)}&fields=files(id)&spaces=drive&supportsAllDrives=true&includeItemsFromAllDrives=true"
        val body = checkResponse(connection(url, "GET"), setOf(200))
        val files = JSONObject(body).getJSONArray("files")
        return if (files.length() == 0) null else files.getJSONObject(0).getString("id")
    }

    private fun connection(url: String, method: String) = (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = method
        connectTimeout = 30_000
        readTimeout = 120_000
        setRequestProperty("Authorization", "Bearer $token")
    }

    private fun checkResponse(connection: HttpURLConnection, allowed: Set<Int>): String {
        val code = connection.responseCode
        val body = try {
            (if (code in allowed) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        } finally {
            connection.disconnect()
        }
        if (code !in allowed) throw DriveException(code, body)
        return body
    }
}

class DriveException(val statusCode: Int, message: String) : IOException("Drive HTTP $statusCode: $message")
