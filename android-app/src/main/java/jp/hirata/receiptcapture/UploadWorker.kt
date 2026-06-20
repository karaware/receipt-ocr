package jp.hirata.receiptcapture

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.*
import jp.hirata.receiptcapture.data.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.time.Instant
import java.util.UUID

class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = ReceiptApplication.from(applicationContext)
        val dao = app.database.dao()
        val settings = app.settings
        if (!settings.configured) return@withContext Result.failure()
        val token = try { DriveAccess.silentToken(applicationContext, settings.accountName) } catch (_: Exception) { null }
        if (token == null) {
            notifyAuthorizationRequired()
            dao.nextPendingSession()?.let { dao.updateSession(it.copy(status = SessionStatus.FAILED, error = "Google認証を更新してください")) }
            return@withContext Result.failure()
        }
        val uploader = DriveUploader(token, settings.folderId)
        while (true) {
            val pending = dao.nextPendingSession() ?: break
            val group = dao.session(pending.id) ?: continue
            dao.updateSession(pending.copy(status = SessionStatus.UPLOADING, error = null))
            try {
                val payer = pending.payer ?: settings.payer
                if (pending.mode == CaptureMode.MULTIPLE_RECEIPTS) {
                    group.captures.sortedBy { it.position }.forEach { capture ->
                        if (capture.driveFileId == null) {
                            val name = ReceiptNames.fileName(payer, capture.id, Instant.ofEpochMilli(capture.createdAt))
                            val driveId = uploader.upload(File(capture.path), name, capture.id)
                            dao.updateCapture(capture.copy(driveFileId = driveId))
                        }
                    }
                } else {
                    val ordered = group.captures.sortedBy { it.position }
                    val output = File(applicationContext.filesDir, "uploads/${pending.id}.jpg")
                    if (!output.exists()) ImageFiles.stitchOrdered(ordered.map { File(it.path) }, output)
                    val name = ReceiptNames.fileName(payer, pending.id, Instant.ofEpochMilli(pending.createdAt))
                    uploader.upload(output, name, pending.id)
                    output.delete()
                }
                group.captures.forEach { File(it.path).delete() }
                dao.deleteSession(pending)
            } catch (error: DriveException) {
                val permanent = error.statusCode == 401 || error.statusCode == 403 || error.statusCode == 404
                dao.updateSession(pending.copy(status = if (permanent) SessionStatus.FAILED else SessionStatus.QUEUED, error = error.message))
                if (permanent) notifyAuthorizationRequired()
                return@withContext if (permanent) Result.failure() else Result.retry()
            } catch (error: Exception) {
                dao.updateSession(pending.copy(status = SessionStatus.QUEUED, error = error.message))
                return@withContext Result.retry()
            }
        }
        Result.success()
    }

    private fun notifyAuthorizationRequired() {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            applicationContext.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        val intent = PendingIntent.getActivity(
            applicationContext, 0, Intent(applicationContext, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(applicationContext, ReceiptApplication.AUTH_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle("レシートをアップロードできません")
            .setContentText("アプリを開いてGoogle認証と保存先を確認してください")
            .setContentIntent(intent).setAutoCancel(true).build()
        NotificationManagerCompat.from(applicationContext).notify(1001, notification)
    }

    companion object {
        private const val UNIQUE_NAME = "receipt-upload"
        fun enqueue(context: Context, replace: Boolean = false) {
            val request = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, java.util.concurrent.TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_NAME, if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, request
            )
        }
    }
}
