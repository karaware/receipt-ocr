package jp.hirata.receiptcapture

import android.app.*
import android.content.Context
import androidx.room.Room
import jp.hirata.receiptcapture.data.ReceiptDatabase

class ReceiptApplication : Application() {
    val database by lazy {
        Room.databaseBuilder(this, ReceiptDatabase::class.java, "receipt-capture.db").build()
    }
    val settings by lazy { AppSettings(this) }

    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(
            AUTH_CHANNEL, "アップロードエラー", NotificationManager.IMPORTANCE_DEFAULT
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val AUTH_CHANNEL = "upload-auth-errors"
        fun from(context: Context) = context.applicationContext as ReceiptApplication
    }
}
